import base64
import io
import logging
import smtplib
import uuid
from datetime import date
from email.message import EmailMessage
import anthropic
import openai
from telegram import Update
from telegram.ext import ContextTypes
from config import settings
from agent.context import build_context, build_messages, SYSTEM_PROMPT
from agent.tools import TOOLS, handle_tool_call
from db import (
    get_or_create_user, save_message,
    get_goals, get_goal_by_name, update_goal_streak, is_goal_logged_today,
    write_log, write_record, upload_to_storage, has_strava_gym_log, reset_db,
    count_user_messages_today, rate_limit_notified_today, mark_rate_limit_hit,
    get_logs_by_type,
)

_DAILY_LIMIT = 50

# Pricing per million tokens (USD)
_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00, "cache_read": 0.08, "cache_write": 1.00},
}


def _log_api_cost(user_id: int, model: str, input_t: int, output_t: int,
                  cache_read: int = 0, cache_write: int = 0) -> None:
    p = _PRICING.get(model, _PRICING["claude-sonnet-4-6"])
    cost = (
        input_t * p["input"] / 1_000_000 +
        output_t * p["output"] / 1_000_000 +
        cache_read * p["cache_read"] / 1_000_000 +
        cache_write * p["cache_write"] / 1_000_000
    )
    write_log(user_id=user_id, log_type="api_cost", data={
        "model": model,
        "input_tokens": input_t,
        "output_tokens": output_t,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "cost_usd": round(cost, 6),
    })


_WHISPER_PRICE_PER_SEC = 0.006 / 60  # $0.006/minute


def _log_whisper_cost(user_id: int, duration_seconds: int) -> None:
    cost = max(duration_seconds, 1) * _WHISPER_PRICE_PER_SEC
    write_log(user_id=user_id, log_type="api_cost", data={
        "model": "whisper-1",
        "duration_seconds": duration_seconds,
        "cost_usd": round(cost, 6),
    })


def _send_rate_limit_email(count: int) -> None:
    if not settings.smtp_user or not settings.smtp_password:
        logger.warning("Rate limit hit (%d msgs) but SMTP not configured — skipping email", count)
        return
    recipient = settings.notification_email or settings.smtp_user
    try:
        msg = EmailMessage()
        msg["Subject"] = "Life Agent: daily message limit reached"
        msg["From"] = settings.smtp_user
        msg["To"] = recipient
        msg.set_content(
            f"Your Life Agent bot processed {count} messages today and hit the daily cap of {_DAILY_LIMIT}.\n\n"
            "This may indicate a loop or unexpected usage. The bot will resume accepting messages tomorrow.\n\n"
            "Check the Supabase logs table (type='rate_limit_hit') for context."
        )
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        logger.info("Rate limit email sent to %s", recipient)
    except Exception as e:
        logger.error("Failed to send rate limit email: %s", e)

logger = logging.getLogger(__name__)
claude = anthropic.Anthropic(api_key=settings.anthropic_api_key)
_openai: openai.OpenAI | None = None


def _get_openai() -> openai.OpenAI:
    global _openai
    if _openai is None:
        _openai = openai.OpenAI(api_key=settings.openai_api_key)
    return _openai


def _transcribe(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename
    result = _get_openai().audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        language="en",
    )
    return result.text


async def _is_authorized(update: Update) -> bool:
    user_id = update.effective_user.id if update.effective_user else None
    if user_id != settings.telegram_user_id:
        logger.warning("Unauthorized message from user_id=%s", user_id)
        return False
    return True


def _call_claude(system: str, messages: list[dict], user_id: int, tools: list | None = None) -> str:
    active_tools = tools if tools is not None else TOOLS
    total_input = total_output = total_cache_read = total_cache_write = 0
    while True:
        response = claude.messages.create(
            model=settings.claude_model,
            max_tokens=1024,
            system=system,
            messages=messages,
            tools=active_tools,
        )
        u = response.usage
        total_input += u.input_tokens
        total_output += u.output_tokens
        total_cache_read += getattr(u, "cache_read_input_tokens", 0) or 0
        total_cache_write += getattr(u, "cache_creation_input_tokens", 0) or 0

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info("Tool call: %s — %s", block.name, block.input)
                    result = handle_tool_call(block.name, block.input, user_id)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            _log_api_cost(user_id, settings.claude_model, total_input, total_output,
                          total_cache_read, total_cache_write)
            return next(
                block.text for block in response.content if hasattr(block, "text")
            )


# --- Two-step extraction pipeline ---

_EXTRACTION_MODEL = "claude-haiku-4-5-20251001"


def _extraction_system() -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).astimezone()
    today = now.strftime("%Y-%m-%d")
    weekday = now.strftime("%A")
    return (
        f"Today is {weekday} {today} (HKT). Use this to resolve relative dates "
        f"('yesterday', 'last night', 'this morning').\n\n"
        "You are a data extraction assistant. Read the user's message and call log_data "
        "for every trackable lifestyle item that DEFINITELY HAPPENED.\n\n"
        "Valid log types and when to use them:\n"
        "- sleep: bedtime, wake time, hours — use for any sleep report\n"
        "- habit: gym sessions, supplements taken, hydration, any recurring tracked behaviour. "
        "For gym: name='gym', include muscle groups and sets. For supplements: name=supplement name.\n"
        "- food: every meal and snack separately — breakfast, lunch, dinner, snack\n"
        "- mood: score 1-10 and brief note\n"
        "- finance: every confirmed spend — amount, currency (default HKD), category, description\n"
        "- study: subject (default CFA), duration_min, topic\n"
        "- social: events, meetups, calls with people\n"
        "- health_metric: measurable body stats — weight, heart rate, blood pressure (NOT gym sessions)\n"
        "- strava_activity: only for activities explicitly synced from Strava\n\n"
        "ONLY log definite past facts. "
        "Do NOT log plans, intentions, or uncertainties ('I might', 'maybe', 'I think', 'I'm going to', 'I'm not sure'). "
        "Make one log_data call per distinct item. "
        "If the message has no confirmed past trackable data, call nothing_to_log."
    )

_NOTHING_TO_LOG_TOOL = {
    "name": "nothing_to_log",
    "description": "Call this when the message is a greeting, question, or chat with no confirmed past trackable data to log.",
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

_EXTRACTION_TOOLS = [
    next(t for t in TOOLS if t["name"] == "log_data"),
    _NOTHING_TO_LOG_TOOL,
]

# Step 2 tools: everything EXCEPT log_data — data capture is step 1's job
STEP2_TOOLS = [t for t in TOOLS if t["name"] != "log_data"]


def _run_extraction(message: str, user_id: int) -> int:
    """Step 1: force-extract and log all confirmed data. Returns items logged."""
    logged = 0
    messages = [{"role": "user", "content": message}]
    total_input = total_output = 0

    for round_num in range(3):
        response = claude.messages.create(
            model=_EXTRACTION_MODEL,
            max_tokens=4096,
            system=_extraction_system(),
            messages=messages,
            tools=_EXTRACTION_TOOLS,
            tool_choice={"type": "any"} if round_num == 0 else {"type": "auto"},
        )
        total_input += response.usage.input_tokens
        total_output += response.usage.output_tokens

        if response.stop_reason != "tool_use":
            break

        tool_results = []
        hit_nothing = False
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "nothing_to_log":
                hit_nothing = True
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": "ok"})
            elif block.name == "log_data":
                result = handle_tool_call("log_data", block.input, user_id)
                logged += 1
                logger.info("Extraction logged: %s — %s", block.input.get("type"), block.input.get("data"))
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

        if hit_nothing:
            break

    _log_api_cost(user_id, _EXTRACTION_MODEL, total_input, total_output)
    return logged


def _claude_error_message(e: Exception) -> str:
    if isinstance(e, anthropic.AuthenticationError):
        return "⚠️ Bot error: API key invalid. Check ANTHROPIC_API_KEY in .env."
    if isinstance(e, anthropic.PermissionDeniedError):
        return "⚠️ Bot error: API key blocked or billing issue. Check console.anthropic.com."
    if isinstance(e, anthropic.RateLimitError):
        return "⚠️ Rate limit hit — try again in a moment."
    return f"⚠️ Something went wrong reaching my brain: {type(e).__name__}. Try again."


async def handle_goals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return

    user = get_or_create_user(settings.telegram_user_id)
    goals = get_goals(user["id"])

    if not goals:
        await update.message.reply_text("No active goals set.")
        return

    lines = []
    for g in goals:
        streak = g.get("current_streak", 0)
        target = g.get("target_per_week")
        line = f"• {g['title']}"
        if g.get("is_non_negotiable"):
            line += " [NON-NEG]"
        if target:
            line += f" — streak {streak}, target {target}x/week"
        elif streak:
            line += f" — {streak} day streak"
        if g.get("description"):
            line += f"\n  {g['description']}"
        lines.append(line)

    await update.message.reply_text("Active Goals:\n\n" + "\n\n".join(lines))


async def handle_done_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /done <goal name>\nExample: /done gym")
        return

    goal_name = " ".join(args)
    user = get_or_create_user(settings.telegram_user_id)
    user_id = user["id"]

    goal = get_goal_by_name(user_id, goal_name)
    if not goal:
        await update.message.reply_text(
            f"No active goal matching '{goal_name}'. Use /goals to see your goals."
        )
        return

    if is_goal_logged_today(user_id, goal["id"]):
        await update.message.reply_text(
            f"Already marked {goal['title']} done today. Streak: {goal['current_streak']}."
        )
        return

    # Strava guard: if this is a gym-type goal and Strava already logged a gym session today, skip
    if goal.get("is_gym") or "gym" in goal["title"].lower():
        if has_strava_gym_log(user_id, date.today()):
            await update.message.reply_text(
                f"Strava already logged a gym session today — no need to double-count. Streak: {goal['current_streak']}."
            )
            return

    write_log(
        user_id=user_id,
        log_type="habit",
        data={"name": goal["title"], "completed": True},
        goal_id=goal["id"],
    )

    current = goal["current_streak"] + 1
    longest = max(goal["longest_streak"], current)
    update_goal_streak(goal["id"], current, longest)

    await update.message.reply_text(
        f"Done: {goal['title']} — day {current} streak."
        + (" Personal best." if current == longest and current > 1 else "")
    )


_RECORD_TYPES = {"bloodtest", "body_comp", "medical", "dietary", "decision", "note"}


async def handle_record_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return

    args = context.args
    if not args or args[0].lower() not in _RECORD_TYPES:
        await update.message.reply_text(
            "Usage: /record <type> <data>\n"
            f"Types: {', '.join(sorted(_RECORD_TYPES))}\n\n"
            "Example: /record bloodtest Hemoglobin 14.5 g/dL, Ferritin 25 ng/mL"
        )
        return

    record_type = args[0].lower()
    data_text = " ".join(args[1:])

    if not data_text:
        await update.message.reply_text(
            f"Please include the data after /record {record_type}\n"
            f"Example: /record {record_type} <paste your data here>"
        )
        return

    try:
        await update.message.chat.send_action("typing")
    except Exception:
        pass

    user = get_or_create_user(settings.telegram_user_id)
    user_id = user["id"]

    prompt = (
        f"The user is logging a {record_type} record. "
        f"Extract the structured data, call store_record with type='{record_type}', "
        f"then reply with a short confirmation listing the key values you stored. "
        f"Raw input: '{data_text}'"
    )

    system = f"{SYSTEM_PROMPT}\n\n{build_context(user)}"
    messages = [{"role": "user", "content": prompt}]
    try:
        reply = _call_claude(system, messages, user_id)
    except anthropic.APIError as e:
        logger.error("Anthropic API error in handle_record_command: %s", e)
        await update.message.reply_text(_claude_error_message(e))
        return

    await update.message.reply_text(reply)
    save_message(user_id, "user", f"/record {record_type} {data_text}")
    save_message(user_id, "assistant", reply)


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return

    message = update.message
    caption = message.caption or ""

    if message.photo:
        tg_file_obj = message.photo[-1]
        file_id = tg_file_obj.file_id
        mime_type = "image/jpeg"
        filename = f"{file_id}.jpg"
    elif message.document:
        doc = message.document
        file_id = doc.file_id
        mime_type = doc.mime_type or "application/octet-stream"
        filename = doc.file_name or f"{file_id}.bin"
    else:
        return

    try:
        await message.chat.send_action("typing")
    except Exception:
        pass

    tg_file = await context.bot.get_file(file_id)
    file_bytes = bytes(await tg_file.download_as_bytearray())

    storage_path = None
    try:
        storage_path = f"{uuid.uuid4()}/{filename}"
        upload_to_storage(storage_path, file_bytes, mime_type)
        logger.info("Uploaded to storage: %s", storage_path)
    except Exception as e:
        logger.warning("Storage upload failed: %s", e)

    user = get_or_create_user(settings.telegram_user_id)
    user_id = user["id"]

    is_image = mime_type.startswith("image/")

    if is_image:
        b64 = base64.standard_b64encode(file_bytes).decode("utf-8")
        user_content = [
            {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": b64}},
            {
                "type": "text",
                "text": (
                    f"The user sent an image. Caption: '{caption}'. "
                    "Analyse it. If it's a health document (InBody, blood test result), call store_record with the extracted data. "
                    "If it's food, call log_data with type='food'. "
                    "Then give a brief summary of what you stored."
                ),
            },
        ]
    else:
        user_content = (
            f"The user uploaded a file: '{filename}' ({mime_type}). "
            + (f"Caption: '{caption}'. " if caption else "No caption provided. ")
            + (f"It was saved to storage at path: {storage_path}. " if storage_path else "Storage upload failed. ")
            + "If the caption contains health or record data, extract it and call store_record. "
            + "Otherwise acknowledge receipt and ask for details about what this file contains."
        )

    system = f"{SYSTEM_PROMPT}\n\n{build_context(user)}"
    messages = [{"role": "user", "content": user_content}]
    try:
        reply = _call_claude(system, messages, user_id)
    except anthropic.APIError as e:
        logger.error("Anthropic API error in handle_file: %s", e)
        await message.reply_text(_claude_error_message(e))
        return

    await message.reply_text(reply)
    save_message(user_id, "user", f"[File: {filename}] {caption}")
    save_message(user_id, "assistant", reply)


async def handle_decision_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Describe the decision after /decision.\n"
            "Example: /decision I'm dropping side projects for 3 months to focus on CFA."
        )
        return

    decision_text = " ".join(args)

    try:
        await update.message.chat.send_action("typing")
    except Exception:
        pass

    user = get_or_create_user(settings.telegram_user_id)
    user_id = user["id"]

    prompt = (
        f"The user is logging a major life decision. "
        f"Extract these fields and call store_record with type='decision': "
        f"title (short label for the decision), "
        f"context (the situation that led to this), "
        f"options_considered (list of alternatives they weighed), "
        f"choice_made (what they decided), "
        f"reasoning (the key reason). "
        f"Then reply with one sentence confirming it's logged and one sentence acknowledging the decision. "
        f"Raw input: '{decision_text}'"
    )

    system = f"{SYSTEM_PROMPT}\n\n{build_context(user)}"
    messages = [{"role": "user", "content": prompt}]
    try:
        reply = _call_claude(system, messages, user_id)
    except anthropic.APIError as e:
        logger.error("Anthropic API error in handle_decision_command: %s", e)
        await update.message.reply_text(_claude_error_message(e))
        return

    await update.message.reply_text(reply)
    save_message(user_id, "user", f"/decision {decision_text}")
    save_message(user_id, "assistant", reply)


async def handle_costs_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return

    user = get_or_create_user(settings.telegram_user_id)
    cost_logs = get_logs_by_type(user["id"], "api_cost", days=30)

    if not cost_logs:
        await update.message.reply_text("No API cost data yet — tracked automatically from the next message.")
        return

    whisper_logs = [l for l in cost_logs if l["data"].get("model") == "whisper-1"]
    claude_logs  = [l for l in cost_logs if l["data"].get("model") != "whisper-1"]

    claude_cost   = sum(l["data"].get("cost_usd", 0) for l in claude_logs)
    whisper_cost  = sum(l["data"].get("cost_usd", 0) for l in whisper_logs)
    total_cost    = claude_cost + whisper_cost

    claude_input  = sum(l["data"].get("input_tokens", 0) for l in claude_logs)
    claude_output = sum(l["data"].get("output_tokens", 0) for l in claude_logs)

    whisper_secs  = sum(l["data"].get("duration_seconds", 0) for l in whisper_logs)
    whisper_mins  = whisper_secs / 60

    by_date: dict[str, float] = {}
    for l in cost_logs:
        d = l["date"]
        by_date[d] = by_date.get(d, 0.0) + l["data"].get("cost_usd", 0)

    days_active = len(by_date)
    avg_daily = total_cost / max(days_active, 1)
    projected_monthly = avg_daily * 30

    recent = sorted(by_date.items(), reverse=True)[:7]
    daily_lines = "\n".join(f"  {d}: ${cost:.4f}" for d, cost in recent)

    claude_line  = f"Claude: ${claude_cost:.4f} ({claude_input:,} in / {claude_output:,} out tokens)"
    whisper_line = (
        f"Whisper: ${whisper_cost:.4f} ({whisper_mins:.1f} min transcribed)"
        if whisper_logs else "Whisper: $0.0000 (no voice messages yet)"
    )

    await update.message.reply_text(
        f"API Costs — Last 30 Days\n\n"
        f"{claude_line}\n"
        f"{whisper_line}\n\n"
        f"Total: ${total_cost:.4f}\n"
        f"Daily avg: ${avg_daily:.4f}\n"
        f"Projected/month: ${projected_monthly:.2f}\n\n"
        f"Last 7 days:\n{daily_lines}"
    )


async def _process_message(update: Update, user_text: str) -> None:
    """Shared two-step pipeline for both text and transcribed voice messages."""
    user = get_or_create_user(settings.telegram_user_id)
    user_id = user["id"]

    # Rate limit check
    msg_count = count_user_messages_today(user_id)
    if msg_count >= _DAILY_LIMIT:
        if not rate_limit_notified_today(user_id):
            _send_rate_limit_email(msg_count)
            mark_rate_limit_hit(user_id)
        await update.message.reply_text(
            f"Daily message limit of {_DAILY_LIMIT} reached. Bot resumes tomorrow."
        )
        return

    # Step 1 — forced extraction
    try:
        logged_count = _run_extraction(user_text, user_id)
        logger.info("Extraction complete — %d items logged", logged_count)
    except anthropic.APIError as e:
        logger.error("Extraction step failed: %s", e)
        await update.message.reply_text(_claude_error_message(e))
        return
    except Exception as e:
        logger.error("Extraction step failed (non-API): %s", e, exc_info=True)
        await update.message.reply_text("⚠️ Extraction step failed — data may not have been logged. Try again.")
        return

    # Reset Supabase connection: extraction holds it open for potentially long periods,
    # which can trigger server-side HTTP/2 timeout. Fresh connection for step 2 reads.
    reset_db()

    # Step 2 — conversation with fresh context
    extraction_note = (
        f"\n\n## This Message\nData extraction already ran: {logged_count} item(s) logged. "
        "If items were logged, confirm them briefly in your reply so Mahir can verify. "
        "Do not re-log anything — focus on the conversational response."
        if logged_count > 0 else
        "\n\n## This Message\nNo new data was extracted from this message."
    )

    try:
        system = f"{SYSTEM_PROMPT}\n\n{build_context(user)}{extraction_note}"
        messages = build_messages(user, user_text)
        reply = _call_claude(system, messages, user_id, tools=STEP2_TOOLS)
    except anthropic.APIError as e:
        logger.error("Anthropic API error in step 2: %s", e)
        await update.message.reply_text(_claude_error_message(e))
        return
    except Exception as e:
        logger.error("Step 2 failed: %s", e, exc_info=True)
        await update.message.reply_text("⚠️ Something went wrong building my response. Try again.")
        return

    await update.message.reply_text(reply)
    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", reply)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return

    user_text = update.message.text or ""
    if not user_text.strip():
        return

    try:
        await update.message.chat.send_action("typing")
    except Exception:
        pass

    await _process_message(update, user_text)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return

    if not settings.openai_api_key:
        await update.message.reply_text("⚠️ Voice transcription is not configured (OPENAI_API_KEY missing).")
        return

    try:
        await update.message.chat.send_action("typing")
    except Exception:
        pass

    voice = update.message.voice or update.message.audio
    if not voice:
        return

    duration_seconds: int = getattr(voice, "duration", 0) or 0

    try:
        tg_file = await context.bot.get_file(voice.file_id)
        audio_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        logger.error("Failed to download voice file: %s", e)
        await update.message.reply_text("⚠️ Couldn't download the voice message. Try again.")
        return

    try:
        user_text = _transcribe(audio_bytes)
        logger.info("Transcribed voice message (%ds): %s", duration_seconds, user_text[:100])
    except Exception as e:
        logger.error("Whisper transcription failed: %s", e)
        await update.message.reply_text("⚠️ Transcription failed. Try again or send as text.")
        return

    if not user_text.strip():
        await update.message.reply_text("Couldn't make out anything in that voice message.")
        return

    user_obj = get_or_create_user(settings.telegram_user_id)
    _log_whisper_cost(user_obj["id"], duration_seconds)

    # Echo the transcription so Mahir can verify what was heard
    await update.message.reply_text(f"_{user_text}_", parse_mode="Markdown")

    await _process_message(update, user_text)
