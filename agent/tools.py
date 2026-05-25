from datetime import date
from tavily import TavilyClient
from config import settings
from db import write_log, write_record, delete_log, get_user, get_strava_logs, get_goal_by_name
from integrations.google import create_event_for_user, get_events_range_for_user, delete_event_for_user

_tavily: TavilyClient | None = None


def _get_tavily() -> TavilyClient:
    global _tavily
    if _tavily is None:
        _tavily = TavilyClient(api_key=settings.tavily_api_key)
    return _tavily


TOOLS = [
    {
        "name": "log_data",
        "description": (
            "Log structured data to the database when Mahir reports an activity, "
            "habit, mood, meal, spend, workout, or any other trackable event. "
            "Always call this when Mahir reports something — do not just acknowledge it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "Category of log. One of: habit, mood, food, finance, study, sleep, social, reflection, health_metric, strava_activity",
                },
                "data": {
                    "type": "object",
                    "description": "Structured data for this log entry. Include all relevant fields e.g. {name: gym, duration_min: 60} or {amount: 200, category: groceries}",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional freeform notes to attach to this log entry",
                },
                "date": {
                    "type": "string",
                    "description": "Date of the activity in YYYY-MM-DD format. Defaults to today if not specified.",
                },
            },
            "required": ["type", "data"],
        },
    },
    {
        "name": "delete_log",
        "description": (
            "Delete the most recent log entry of a given type on a given date. "
            "Use when Mahir says something was logged by mistake, asks to undo a log, or wants to remove an entry."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "The log type to delete (e.g. habit, food, finance, mood, sleep)",
                },
                "date": {
                    "type": "string",
                    "description": "Date of the log to delete in YYYY-MM-DD format. Defaults to today if not specified.",
                },
            },
            "required": ["type"],
        },
    },
    {
        "name": "store_record",
        "description": (
            "Store a one-time health or life record — not a daily log, but a measurement or document. "
            "Use for blood tests, body composition (InBody), medical notes, dietary profiles, decisions. "
            "Always call this when the user provides a health record or uploads health data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "Record type: bloodtest, body_comp, medical, dietary, decision, note",
                },
                "data": {
                    "type": "object",
                    "description": "Structured data extracted from the record. Include all key measurements, values, and labels.",
                },
                "notes": {
                    "type": "string",
                    "description": "Short summary or observations about this record",
                },
            },
            "required": ["type", "data"],
        },
    },
    {
        "name": "get_calendar_events",
        "description": (
            "Fetch Mahir's Google Calendar events for a date or date range. "
            "Use when he asks what he has scheduled, what's coming up, or to check his calendar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Start date in YYYY-MM-DD format",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date in YYYY-MM-DD format. Defaults to start_date if omitted (single day).",
                },
            },
            "required": ["start_date"],
        },
    },
    {
        "name": "delete_calendar_event",
        "description": (
            "Delete an event from Mahir's Google Calendar by event ID. "
            "First call get_calendar_events to find the event and its ID, then call this to delete it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "The Google Calendar event ID (returned by get_calendar_events)",
                },
                "title": {
                    "type": "string",
                    "description": "Event title — for confirmation in the reply only",
                },
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "create_calendar_event",
        "description": (
            "Create an event in Mahir's Google Calendar. Use when he asks to add, schedule, "
            "or block time for something. Always confirm the details in your reply after creating."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Event title",
                },
                "date": {
                    "type": "string",
                    "description": "Date in YYYY-MM-DD format",
                },
                "start_time": {
                    "type": "string",
                    "description": "Start time in HH:MM 24-hour format (HKT). Omit for all-day events.",
                },
                "end_time": {
                    "type": "string",
                    "description": "End time in HH:MM 24-hour format (HKT). Defaults to 1 hour after start if omitted.",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional description or notes to attach to the event",
                },
            },
            "required": ["title", "date"],
        },
    },
    {
        "name": "search_web",
        "description": (
            "Search the web for current information. Use this when Mahir asks about "
            "something that requires up-to-date data: prices, research, news, recommendations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to send to Tavily",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_strava_activities",
        "description": (
            "Fetch Mahir's Strava workout history from the database. "
            "Use when he asks about past workouts, gym frequency, running distance, "
            "heart rate trends, or activity stats over a time period."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "How many days back to look (default 30, max 90)",
                },
                "sport_type": {
                    "type": "string",
                    "description": "Optional filter by sport type e.g. WeightTraining, Run, Ride",
                },
            },
            "required": [],
        },
    },
]


def handle_tool_call(tool_name: str, tool_input: dict, user_id: int) -> str:
    if tool_name == "delete_log":
        log_date = date.fromisoformat(tool_input["date"]) if tool_input.get("date") else date.today()
        deleted = delete_log(user_id, tool_input["type"], log_date)
        if deleted:
            return f"Deleted most recent {tool_input['type']} log for {log_date}."
        return f"No {tool_input['type']} log found for {log_date} to delete."

    if tool_name == "delete_calendar_event":
        user = get_user(settings.telegram_user_id)
        if not user:
            return "User not found."
        event_id = tool_input["event_id"]
        title = tool_input.get("title", "event")
        import logging
        logging.getLogger(__name__).info("Deleting calendar event id=%s title=%s", event_id, title)
        result = delete_event_for_user(user, event_id)
        return f"Deleted '{title}' from Google Calendar." if result == "Event deleted." else result

    if tool_name == "get_calendar_events":
        start = date.fromisoformat(tool_input["start_date"])
        end = date.fromisoformat(tool_input["end_date"]) if tool_input.get("end_date") else start
        user = get_user(settings.telegram_user_id)
        if not user:
            return "User not found."
        events = get_events_range_for_user(user, start, end)
        if not events:
            return f"No events found between {start} and {end}."
        return "\n".join(
            f"[{e['date']}] {e['title']} — {e['time']} (id: {e['id']})"
            for e in events
        )

    if tool_name == "create_calendar_event":
        user = get_user(settings.telegram_user_id)
        if not user:
            return "User not found."
        link = create_event_for_user(
            user,
            title=tool_input["title"],
            event_date=tool_input["date"],
            start_time=tool_input.get("start_time"),
            end_time=tool_input.get("end_time"),
            notes=tool_input.get("notes"),
        )
        result = f"Created: {tool_input['title']} on {tool_input['date']}"
        if tool_input.get("start_time"):
            result += f" at {tool_input['start_time']}"
        if link.startswith("http"):
            result += f" — {link}"
        return result

    if tool_name == "store_record":
        write_record(
            user_id=user_id,
            record_type=tool_input["type"],
            data=tool_input["data"],
            notes=tool_input.get("notes", ""),
        )
        return f"Stored {tool_input['type']} record: {tool_input['data']}"

    if tool_name == "log_data":
        log_date = date.fromisoformat(tool_input["date"]) if tool_input.get("date") else date.today()
        goal_id = None
        if tool_input["type"] == "habit":
            habit_name = tool_input["data"].get("name", "")
            if habit_name:
                goal = get_goal_by_name(user_id, habit_name)
                if goal:
                    goal_id = goal["id"]
        write_log(
            user_id=user_id,
            log_type=tool_input["type"],
            data=tool_input["data"],
            notes=tool_input.get("notes", ""),
            log_date=log_date,
            goal_id=goal_id,
        )
        return f"Logged: {tool_input['type']} — {tool_input['data']}"

    if tool_name == "search_web":
        response = _get_tavily().search(tool_input["query"], max_results=5)
        results = response.get("results", [])
        formatted = "\n\n".join(
            f"**{r['title']}**\n{r['content']}\nSource: {r['url']}"
            for r in results
        )
        return formatted or "No results found."

    if tool_name == "get_strava_activities":
        days = min(int(tool_input.get("days", 30)), 90)
        sport_filter = tool_input.get("sport_type", "").lower()
        logs = get_strava_logs(user_id, days)
        if sport_filter:
            logs = [l for l in logs if sport_filter in (l.get("data", {}).get("sport_type") or "").lower()]
        if not logs:
            return f"No Strava activities found in the last {days} days."
        lines = []
        for l in logs:
            d = l.get("data", {})
            line = f"[{l['date']}] {d.get('name', 'Activity')} ({d.get('sport_type', '?')})"
            if d.get("duration_min"):
                line += f" — {d['duration_min']} min"
            if d.get("distance_km"):
                line += f", {d['distance_km']} km"
            if d.get("avg_hr"):
                line += f", HR {d['avg_hr']}"
            if d.get("calories"):
                line += f", {d['calories']} kcal"
            lines.append(line)
        return "\n".join(lines)

    return f"Unknown tool: {tool_name}"
