import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI

from bot import build_app
from db import init_db

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

telegram_app = build_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling()
    logger.info("Bot polling started")
    yield
    await telegram_app.updater.stop()
    await telegram_app.stop()
    await telegram_app.shutdown()
    logger.info("Bot stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
