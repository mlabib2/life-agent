import logging
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
