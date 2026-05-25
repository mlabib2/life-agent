import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone, date

import uvicorn
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from bot import build_app
from config import settings
from db import init_db, get_or_create_user, update_user, write_log
from integrations.google import get_auth_url as google_auth_url, exchange_code as google_exchange_code
from integrations.strava import get_auth_url as strava_auth_url, exchange_code as strava_exchange_code
from scheduler.jobs import build_scheduler

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    telegram_app = build_app()
    scheduler = build_scheduler(telegram_app.bot)

    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    scheduler.start()
    logger.info("Bot polling started")
    logger.info("Scheduler started — 5 jobs registered")
    yield

    scheduler.shutdown()
    await telegram_app.updater.stop()
    await telegram_app.stop()
    await telegram_app.shutdown()
    logger.info("Bot stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/auth/google")
def auth_google():
    if not settings.google_client_id:
        raise HTTPException(status_code=501, detail="Google Calendar not configured — set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env")
    return RedirectResponse(google_auth_url())


@app.get("/auth/google/callback")
def auth_google_callback(code: str):
    try:
        tokens = google_exchange_code(code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {e}")
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token returned. Revoke app access in Google account settings and try again.")
    user = get_or_create_user(settings.telegram_user_id)
    update_user(user["id"], {"google_refresh_token": refresh_token})
    logger.info("Google Calendar connected for user_id=%s", user["id"])
    return {"status": "Google Calendar connected successfully."}


@app.get("/auth/strava")
def auth_strava():
    if not settings.strava_client_id:
        raise HTTPException(status_code=501, detail="Strava not configured — set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET in .env")
    return RedirectResponse(strava_auth_url())


@app.get("/auth/strava/callback")
def auth_strava_callback(code: str, scope: str = ""):
    if "activity:read_all" not in scope:
        raise HTTPException(status_code=400, detail="Missing required scope activity:read_all. Please re-authorize.")
    try:
        tokens = strava_exchange_code(code)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {e}")
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token returned.")
    user = get_or_create_user(settings.telegram_user_id)
    update_user(user["id"], {"strava_refresh_token": refresh_token})
    logger.info("Strava connected for user_id=%s", user["id"])
    return {"status": "Strava connected successfully."}


class _AppleHealthPayload(BaseModel):
    sleep_hours: float | None = None
    resting_hr: int | None = None
    steps: int | None = None
    hrv: float | None = None
    date: str  # YYYY-MM-DD


@app.post("/health/apple")
def apple_health(payload: _AppleHealthPayload, authorization: str = Header(default="")):
    token = settings.apple_health_token
    if not token or token == "your_static_secret_here":
        raise HTTPException(status_code=501, detail="Apple Health not configured — set APPLE_HEALTH_TOKEN in .env")
    if authorization != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        log_date = date.fromisoformat(payload.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")

    user = get_or_create_user(settings.telegram_user_id)
    user_id = user["id"]

    logged: list[str] = []
    for metric, value in [
        ("sleep_hours", payload.sleep_hours),
        ("resting_hr", payload.resting_hr),
        ("steps", payload.steps),
        ("hrv", payload.hrv),
    ]:
        if value is not None:
            write_log(
                user_id=user_id,
                log_type="health_metric",
                data={"metric": metric, "value": value},
                log_date=log_date,
            )
            logged.append(metric)

    logger.info("Apple Health synced %d metrics for %s: %s", len(logged), payload.date, logged)
    return {"status": "logged", "metrics": logged, "date": payload.date}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
