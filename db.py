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


def init_db() -> None:
    client = get_db()
    client.table("users").select("id").limit(1).execute()
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

def write_log(user_id: int, log_type: str, data: dict, notes: str = "", log_date: date | None = None) -> dict:
    row = {
        "user_id": user_id,
        "type": log_type,
        "date": (log_date or date.today()).isoformat(),
        "data": data,
        "notes": notes,
    }
    result = get_db().table("logs").insert(row).execute()
    return result.data[0]


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


# --- Goals ---

def get_goals(user_id: int, active_only: bool = True) -> list[dict]:
    query = get_db().table("goals").select("*").eq("user_id", user_id)
    if active_only:
        query = query.eq("active", True)
    return query.order("created_at").execute().data
