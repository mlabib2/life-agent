import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
import anthropic
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import settings
from agent.context import build_context, SYSTEM_PROMPT
from db import (
    get_user, write_record, get_events_for_date, replace_events_for_date,
    write_log, get_goal_by_name,
    delete_strava_logs_for_date, delete_habit_logs_for_goal_date,
)
from integrations.google import get_events_for_user
from integrations.strava import get_activities_for_user

logger = logging.getLogger(__name__)
claude = anthropic.Anthropic(api_key=settings.anthropic_api_key)

_SNAPSHOT_SCHEMA = """{
  "goals_momentum": [{"goal": "goal title", "streak": 0, "status": "on_track|behind|ahead"}],
  "open_decisions": ["pending decision or open question"],
  "health_flags": ["notable health observation"],
  "momentum_score": 7,
  "patterns_noticed": ["behavioral pattern observed in logs"],
  "weekly_note": "one honest sentence about the week"
}"""


def _extract_json(text: str) -> dict:
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if match:
            return json.loads(match.group(1).strip())
        raise ValueError("no valid JSON found")


def _ask_claude(prompt: str, user: dict) -> str:
    system = f"{SYSTEM_PROMPT}\n\n{build_context(user)}"
    response = claude.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return next(block.text for block in response.content if hasattr(block, "text"))


async def _send(bot: Bot, text: str) -> None:
    await bot.send_message(chat_id=settings.telegram_user_id, text=text)


async def sync_strava(bot: Bot) -> None:
    user = get_user(settings.telegram_user_id)
    if not user or not user.get("strava_refresh_token"):
        return

    yesterday = date.today() - timedelta(days=1)
    # Go back 2 days in UTC to cover HKT offset when filtering by local date
    since = datetime.now(timezone.utc) - timedelta(days=2)

    try:
        activities = get_activities_for_user(user, since)
    except Exception as e:
        logger.error("Strava sync failed: %s", e)
        return

    # Clean slate for yesterday then re-insert
    delete_strava_logs_for_date(user["id"], yesterday)

    gym_activities = []
    for act in activities:
        act_date_str = act.get("date")
        if not act_date_str:
            continue
        act_date = date.fromisoformat(act_date_str)
        if act_date != yesterday:
            continue
        write_log(
            user_id=user["id"],
            log_type="strava_activity",
            data={
                "strava_id": act["id"],
                "name": act["name"],
                "sport_type": act["sport_type"],
                "duration_min": act["duration_min"],
                "distance_km": act["distance_km"],
                "avg_hr": act["avg_hr"],
                "calories": act["calories"],
                "is_gym": act["is_gym"],
            },
            notes=act["sport_type"],
            log_date=act_date,
        )
        if act["is_gym"]:
            gym_activities.append(act)

    # Segment 4: if Strava logged gym, remove any manual habit log for same day
    deduped = 0
    if gym_activities:
        gym_goal = get_goal_by_name(user["id"], "gym")
        if gym_goal:
            deduped = delete_habit_logs_for_goal_date(user["id"], gym_goal["id"], yesterday)
            if deduped:
                logger.info("Deduped %d manual gym log(s) for %s — Strava data preferred", deduped, yesterday)

    synced_count = len([a for a in activities if a.get("date") == yesterday.isoformat()])
    logger.info(
        "Strava synced — %d activities for %s, %d gym, %d manual logs removed",
        synced_count, yesterday, len(gym_activities), deduped,
    )


async def sync_google_calendar(bot: Bot) -> None:
    user = get_user(settings.telegram_user_id)
    if not user or not user.get("google_refresh_token"):
        return
    tomorrow = date.today() + timedelta(days=1)
    try:
        events = get_events_for_user(user, tomorrow)
        replace_events_for_date(user["id"], tomorrow, "google_calendar", events)
        logger.info("Google Calendar synced — %d events for %s", len(events), tomorrow)
    except Exception as e:
        logger.error("Google Calendar sync failed: %s", e)


async def morning_checkin(bot: Bot) -> None:
    user = get_user(settings.telegram_user_id)
    if not user:
        return

    today_events = get_events_for_date(user["id"], date.today())
    schedule_text = ""
    if today_events:
        lines = [f"- {e['title']}" + (f" ({e['notes']})" if e.get("notes") else "") for e in today_events]
        schedule_text = "Today's schedule:\n" + "\n".join(lines) + "\n\n"

    prompt = (
        f"{schedule_text}"
        "Generate a concise morning check-in message for Mahir. "
        "Summarise what he logged yesterday, note any missed habits, "
        + ("weave in today's schedule above, " if schedule_text else "")
        + "and ask what his top 1-2 priorities are for today. "
        "Keep it under 150 words. Be direct, not cheerful."
    )
    message = _ask_claude(prompt, user)
    await _send(bot, message)
    logger.info("Morning check-in sent")


async def evening_review(bot: Bot) -> None:
    user = get_user(settings.telegram_user_id)
    if not user:
        return
    prompt = (
        "Generate an evening review message for Mahir. "
        "Go through his active tracking areas: gym, food, mood, spending, study. "
        "Call out what was logged today and what is missing. "
        "End with one honest observation about the day. "
        "Keep it under 200 words."
    )
    message = _ask_claude(prompt, user)
    await _send(bot, message)
    logger.info("Evening review sent")


async def brain_snapshot(bot: Bot) -> None:
    user = get_user(settings.telegram_user_id)
    if not user:
        return
    system = f"{SYSTEM_PROMPT}\n\n{build_context(user)}"
    prompt = (
        "Generate a brain snapshot based on this week's data. "
        f"Return ONLY valid JSON matching this schema exactly:\n{_SNAPSHOT_SCHEMA}\n"
        "Use real values from the context. goals_momentum should cover all active goals. "
        "No text outside the JSON block."
    )
    response = claude.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = next(block.text for block in response.content if hasattr(block, "text"))
    try:
        snap = _extract_json(raw)
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Brain snapshot parse failed: %s — raw: %.200s", e, raw)
        return
    write_record(user["id"], "brain_snapshot", snap)
    logger.info("Brain snapshot saved — momentum: %s/10", snap.get("momentum_score"))


async def weekly_summary(bot: Bot) -> None:
    user = get_user(settings.telegram_user_id)
    if not user:
        return
    prompt = (
        "Generate a weekly summary for Mahir covering the past 7 days. "
        "Include: habit completion rate, mood trend, study hours, spend pattern. "
        "Call out the biggest win and the biggest slip. "
        "End with one honest forward-looking observation. "
        "Keep it under 300 words."
    )
    message = _ask_claude(prompt, user)
    await _send(bot, message)
    logger.info("Weekly summary sent")
    await brain_snapshot(bot)


def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    tz = "Asia/Hong_Kong"
    scheduler = AsyncIOScheduler(timezone=tz)

    scheduler.add_job(
        sync_google_calendar, "cron",
        hour=0, minute=5,
        kwargs={"bot": bot},
    )
    scheduler.add_job(
        sync_strava, "cron",
        hour=0, minute=10,
        kwargs={"bot": bot},
    )
    scheduler.add_job(
        morning_checkin, "cron",
        hour=6, minute=40,
        day_of_week="mon-fri",
        kwargs={"bot": bot},
    )
    scheduler.add_job(
        evening_review, "cron",
        hour=21, minute=0,
        kwargs={"bot": bot},
    )
    scheduler.add_job(
        weekly_summary, "cron",
        hour=20, minute=0,
        day_of_week="sun",
        kwargs={"bot": bot},
    )

    return scheduler
