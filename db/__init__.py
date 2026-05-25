import logging
from datetime import date, datetime, timezone, timedelta
from supabase import create_client, Client
from config import settings

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_db() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _client


def reset_db() -> None:
    global _client
    _client = None


def init_db() -> None:
    get_db().table("users").select("id").limit(1).execute()
    logger.info("Database connected")


# --- User ---

def get_or_create_user(telegram_user_id: int) -> dict:
    db = get_db()
    result = db.table("users").select("*").eq("telegram_user_id", telegram_user_id).execute()
    if result.data:
        return result.data[0]
    new_user = db.table("users").insert({"telegram_user_id": telegram_user_id}).execute()
    logger.info("Created new user telegram_user_id=%s", telegram_user_id)
    return new_user.data[0]


def get_user(telegram_user_id: int) -> dict | None:
    db = get_db()
    result = db.table("users").select("*").eq("telegram_user_id", telegram_user_id).execute()
    return result.data[0] if result.data else None


def update_user(user_id: int, fields: dict) -> None:
    get_db().table("users").update(fields).eq("id", user_id).execute()


# --- Conversations ---

def save_message(user_id: int, role: str, content: str) -> None:
    get_db().table("conversations").insert({
        "user_id": user_id,
        "role": role,
        "content": content,
    }).execute()


def get_recent_messages(user_id: int, limit: int = 20) -> list[dict]:
    result = get_db().table("conversations") \
        .select("role, content, timestamp") \
        .eq("user_id", user_id) \
        .order("timestamp", desc=True) \
        .limit(limit) \
        .execute()
    return list(reversed(result.data))


# --- Logs ---

def write_log(user_id: int, log_type: str, data: dict, notes: str = "", log_date: date | None = None, goal_id: int | None = None) -> dict:
    row = {
        "user_id": user_id,
        "type": log_type,
        "date": (log_date or date.today()).isoformat(),
        "data": data,
        "notes": notes,
    }
    if goal_id is not None:
        row["goal_id"] = goal_id
    result = get_db().table("logs").insert(row).execute()
    return result.data[0]


def delete_log(user_id: int, log_type: str, log_date: date) -> bool:
    result = get_db().table("logs") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("type", log_type) \
        .eq("date", log_date.isoformat()) \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute()
    if not result.data:
        return False
    get_db().table("logs").delete().eq("id", result.data[0]["id"]).execute()
    return True


def get_recent_logs(user_id: int, days: int = 14) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    result = get_db().table("logs") \
        .select("*") \
        .eq("user_id", user_id) \
        .gte("date", since) \
        .order("date", desc=True) \
        .execute()
    return result.data


# --- Records ---

def write_record(user_id: int, record_type: str, data: dict, notes: str = "", source: str = "manual") -> dict:
    row = {
        "user_id": user_id,
        "type": record_type,
        "date": date.today().isoformat(),
        "data": data,
        "notes": notes,
        "source": source,
    }
    result = get_db().table("records").insert(row).execute()
    return result.data[0]


def get_records(user_id: int, record_type: str) -> list[dict]:
    result = get_db().table("records") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("type", record_type) \
        .order("date", desc=True) \
        .execute()
    return result.data


# --- Records (extended) ---

def get_latest_record(user_id: int, record_type: str) -> dict | None:
    result = get_db().table("records") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("type", record_type) \
        .order("date", desc=True) \
        .limit(1) \
        .execute()
    return result.data[0] if result.data else None


def upload_to_storage(path: str, file_bytes: bytes, content_type: str = "application/octet-stream") -> str:
    get_db().storage.from_("health-files").upload(
        path, file_bytes,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    return path


# --- Goals ---

def get_goals(user_id: int, active_only: bool = True) -> list[dict]:
    query = get_db().table("goals").select("*").eq("user_id", user_id)
    if active_only:
        query = query.eq("active", True)
    return query.order("created_at").execute().data


def get_goal_by_name(user_id: int, name: str) -> dict | None:
    goals = get_goals(user_id)
    name_lower = name.lower()
    for g in goals:
        if name_lower in g["title"].lower():
            return g
    return None


def update_goal_streak(goal_id: int, current: int, longest: int) -> None:
    get_db().table("goals").update({
        "current_streak": current,
        "longest_streak": longest,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", goal_id).execute()


def deactivate_goal(goal_id: int) -> None:
    get_db().table("goals").update({
        "active": False,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", goal_id).execute()


# --- Events ---

def get_events_for_date(user_id: int, target_date: date) -> list[dict]:
    result = get_db().table("events") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("date", target_date.isoformat()) \
        .order("id") \
        .execute()
    return result.data


def replace_events_for_date(user_id: int, target_date: date, source: str, events: list[dict]) -> None:
    db = get_db()
    db.table("events") \
        .delete() \
        .eq("user_id", user_id) \
        .eq("date", target_date.isoformat()) \
        .eq("source", source) \
        .execute()
    for ev in events:
        db.table("events").insert({
            "user_id": user_id,
            "title": ev["title"],
            "date": target_date.isoformat(),
            "type": "calendar",
            "source": source,
            "notes": ev.get("time", ""),
        }).execute()


def is_goal_logged_today(user_id: int, goal_id: int) -> bool:
    result = get_db().table("logs") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("goal_id", goal_id) \
        .eq("date", date.today().isoformat()) \
        .limit(1) \
        .execute()
    return bool(result.data)


def delete_strava_logs_for_date(user_id: int, target_date: date) -> None:
    get_db().table("logs") \
        .delete() \
        .eq("user_id", user_id) \
        .eq("type", "strava_activity") \
        .eq("date", target_date.isoformat()) \
        .execute()


def delete_habit_logs_for_goal_date(user_id: int, goal_id: int, target_date: date) -> int:
    result = get_db().table("logs") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("type", "habit") \
        .eq("goal_id", goal_id) \
        .eq("date", target_date.isoformat()) \
        .execute()
    count = len(result.data)
    if count:
        get_db().table("logs") \
            .delete() \
            .eq("user_id", user_id) \
            .eq("type", "habit") \
            .eq("goal_id", goal_id) \
            .eq("date", target_date.isoformat()) \
            .execute()
    return count


def has_strava_gym_log(user_id: int, target_date: date) -> bool:
    result = get_db().table("logs") \
        .select("id, data") \
        .eq("user_id", user_id) \
        .eq("type", "strava_activity") \
        .eq("date", target_date.isoformat()) \
        .execute()
    return any(row.get("data", {}).get("is_gym") for row in result.data)


def count_user_messages_today(user_id: int) -> int:
    today = date.today().isoformat()
    result = get_db().table("conversations") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("role", "user") \
        .gte("timestamp", today) \
        .execute()
    return len(result.data)


def rate_limit_notified_today(user_id: int) -> bool:
    today = date.today().isoformat()
    result = get_db().table("logs") \
        .select("id") \
        .eq("user_id", user_id) \
        .eq("type", "rate_limit_hit") \
        .eq("date", today) \
        .limit(1) \
        .execute()
    return bool(result.data)


def mark_rate_limit_hit(user_id: int) -> None:
    write_log(user_id=user_id, log_type="rate_limit_hit", data={"limit": 50})


def get_logs_by_type(user_id: int, log_type: str, days: int = 30) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    result = get_db().table("logs") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("type", log_type) \
        .gte("date", since) \
        .order("date", desc=True) \
        .execute()
    return result.data


def get_strava_logs(user_id: int, days: int = 30) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    result = get_db().table("logs") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("type", "strava_activity") \
        .gte("date", since) \
        .order("date", desc=True) \
        .execute()
    return result.data
