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
