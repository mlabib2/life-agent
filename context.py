from db import get_goals, get_recent_logs

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

Tools you can use:
- log_data: when Mahir reports something (e.g. "did gym", "spent $50 on food"), call this to write it to his database
- search_web: when you need current information (prices, research, news), call this

Rules:
- Never make up data — only reference what is in the context
- If you don't know something, say so and offer to search
- Keep replies concise — this is Telegram, not a report
- Always log data when Mahir reports an activity, don't just acknowledge it"""


def build_context(user: dict) -> str:
    user_id = user["id"]

    goals = get_goals(user_id)
    logs = get_recent_logs(user_id, days=14)

    sections = []

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

    if logs:
        log_lines = []
        for log in logs:
            line = f"- [{log['date']}] {log['type']}: {log['data']}"
            if log.get("notes"):
                line += f" — {log['notes']}"
            log_lines.append(line)
        sections.append("## Last 14 Days of Logs\n" + "\n".join(log_lines))
    else:
        sections.append("## Last 14 Days of Logs\nNo logs yet.")

    return "\n\n".join(sections)
