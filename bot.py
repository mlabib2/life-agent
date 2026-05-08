import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from config import settings

logger = logging.getLogger(__name__)


async def _is_authorized(update: Update) -> bool:
    user_id = update.effective_user.id if update.effective_user else None
    if user_id != settings.telegram_user_id:
        logger.warning("Unauthorized message from user_id=%s", user_id)
        return False
    return True


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return
    await update.message.reply_text(f"Echo: {update.message.text}")


def build_app() -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    return app
