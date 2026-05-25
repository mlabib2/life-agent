from datetime import datetime, timezone, timedelta
from db import get_goals, get_recent_logs, get_recent_messages, get_latest_record, get_records

SYSTEM_PROMPT = """You are Mahir's personal AI life agent — a data-driven accountability coach and advisor available 24/7 via Telegram.

Your role:
- Hold Mahir accountable to his stated goals and non-negotiables
- Log his data accurately when he reports it
- Notice patterns in his data that he cannot see himself
- Give honest, direct feedback — not empty encouragement
- Search the web when you need current information to answer a question

Your personality:
- Direct and concise — no filler, no fluff
- Warm but honest — tell the truth even when it's uncomfortable
- Data-first — back observations with numbers from his logs
- Tone adapts to context: supportive after a hard day, firm when he's slacking

What you know about Mahir:
- Tracking: fitness, nutrition, finance, study (CFA), sleep, mood, health
- Goals and non-negotiables are listed below in the context
- You have access to his recent logs, records, and conversation history
- Mahir sometimes sends voice notes transcribed by Whisper — text may be informal or contain transcription artifacts; interpret charitably
- When mood or energy is low, cross-reference sleep_hours from Apple Health logs before drawing conclusions

Tools you can use:
- log_data: when Mahir reports something (e.g. "did gym", "spent $50 on food"), call this to write it to his database
- delete_log: when Mahir says something was logged by mistake or asks to undo an entry
- store_record: for one-time records — blood tests, InBody scans, medical notes, dietary profile, major decisions
- get_calendar_events: when Mahir asks what he has scheduled or wants to check his calendar
- create_calendar_event: when Mahir asks to add or schedule something in his calendar
- delete_calendar_event: when Mahir asks to remove or cancel a calendar event (first call get_calendar_events to find the event ID)
- get_strava_activities: when Mahir asks about past workouts, gym frequency, or activity stats
- search_web: when you need current information (prices, research, news), call this"""


def build_context(user: dict) -> str:
    user_id = user["id"]
    goals = get_goals(user_id)
    logs = get_recent_logs(user_id, days=14)
    body_comp = get_latest_record(user_id, "body_comp")
    blood_test = get_latest_record(user_id, "bloodtest")
    dietary = get_latest_record(user_id, "dietary")
    medical_records = get_records(user_id, "medical")

    sections = []

    now = datetime.now(timezone.utc).astimezone()
    sections.append(f"## Current Date & Time\n{now.strftime('%A, %Y-%m-%d %H:%M')} (HKT)")

    profile_lines = [
        f"Name: {user.get('name') or 'Mahir'}",
        f"Timezone: {user.get('timezone', 'UTC')}",
        f"Wake time: {user.get('wake_time', '07:00')}",
        f"Sleep target: {user.get('sleep_target_time', '23:00')}",
        f"Tone preference: {user.get('tone_preference', 'flexible')}",
    ]
    sections.append("## User Profile\n" + "\n".join(profile_lines))

    if goals:
        goal_lines = []
        for g in goals:
            line = f"- {g['title']}"
            if g.get("description"):
                line += f": {g['description']}"
            if g.get("is_non_negotiable"):
                line += " [NON-NEGOTIABLE]"
            if g.get("target_per_week"):
                line += f" (target: {g['target_per_week']}x/week, streak: {g['current_streak']})"
            goal_lines.append(line)
        sections.append("## Active Goals\n" + "\n".join(goal_lines))
    else:
        sections.append("## Active Goals\nNo goals set yet.")

    # Apple Health metrics (last 7 days) — surfaced separately for pattern analysis
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    health_metrics = [l for l in logs if l["type"] == "health_metric" and l["date"] >= seven_days_ago]
    if health_metrics:
        by_date: dict[str, dict] = {}
        for m in health_metrics:
            d = m["date"]
            metric = m["data"].get("metric", "?")
            value = m["data"].get("value", "?")
            by_date.setdefault(d, {})[metric] = value
        metric_lines = []
        for d in sorted(by_date.keys(), reverse=True):
            vals = by_date[d]
            parts = []
            if "sleep_hours" in vals:
                parts.append(f"sleep {vals['sleep_hours']}h")
            if "resting_hr" in vals:
                parts.append(f"HR {vals['resting_hr']}bpm")
            if "steps" in vals:
                parts.append(f"steps {vals['steps']:,}")
            if "hrv" in vals:
                parts.append(f"HRV {vals['hrv']}ms")
            metric_lines.append(f"- {d}: " + ", ".join(parts))
        sections.append("## Apple Health (Last 7 Days)\n" + "\n".join(metric_lines))

    non_health_logs = [l for l in logs if l["type"] != "health_metric"]
    if non_health_logs:
        log_lines = [
            f"- [{log['date']}] {log['type']}: {log['data']}" +
            (f" — {log['notes']}" if log.get("notes") else "")
            for log in non_health_logs
        ]
        sections.append("## Last 14 Days of Logs\n" + "\n".join(log_lines))
    else:
        sections.append("## Last 14 Days of Logs\nNo logs yet.")

    health_lines = []
    if body_comp:
        health_lines.append(f"Body Composition ({body_comp['date']}): {body_comp['data']}")
    if blood_test:
        health_lines.append(f"Last Blood Test ({blood_test['date']}): {blood_test['data']}")
    if dietary:
        health_lines.append(f"Dietary Profile: {dietary['data']}")
    if medical_records:
        for m in medical_records[:3]:
            health_lines.append(f"Medical ({m['date']}): {m['data']}" + (f" — {m['notes']}" if m.get("notes") else ""))
    if health_lines:
        sections.append("## Health Records\n" + "\n".join(health_lines))

    decisions = get_records(user_id, "decision")[:5]
    if decisions:
        decision_lines = []
        for d in decisions:
            data = d.get("data", {})
            title = data.get("title", "Decision")
            choice = data.get("choice_made", data.get("choice", ""))
            reasoning = data.get("reasoning", "")
            line = f"- [{d['date']}] {title}"
            if choice:
                line += f": {choice}"
            if reasoning:
                line += f" — {reasoning}"
            decision_lines.append(line)
        sections.append("## Recent Decisions\n" + "\n".join(decision_lines))

    snapshot = get_latest_record(user_id, "brain_snapshot")
    if snapshot and snapshot.get("data"):
        snap = snapshot["data"]
        snap_lines = [f"(as of {snapshot['date']})"]
        if snap.get("momentum_score") is not None:
            snap_lines.append(f"Momentum: {snap['momentum_score']}/10")
        if snap.get("goals_momentum"):
            snap_lines.append("Goals: " + ", ".join(
                f"{g['goal']} ({g.get('status', '?')}, streak {g.get('streak', 0)})"
                for g in snap["goals_momentum"]
            ))
        if snap.get("health_flags"):
            snap_lines.append("Health flags: " + "; ".join(snap["health_flags"]))
        if snap.get("patterns_noticed"):
            snap_lines.append("Patterns: " + "; ".join(snap["patterns_noticed"]))
        if snap.get("open_decisions"):
            snap_lines.append("Open decisions: " + "; ".join(snap["open_decisions"]))
        if snap.get("weekly_note"):
            snap_lines.append(f"Note: {snap['weekly_note']}")
        sections.append("## Long-term Memory Snapshot\n" + "\n".join(snap_lines))

    return "\n\n".join(sections)


def build_messages(user: dict, new_message: str) -> list[dict]:
    history = get_recent_messages(user["id"], limit=20)
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": new_message})
    return messages
