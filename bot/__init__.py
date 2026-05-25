import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import settings
from bot.handlers import (
    handle_message,
    handle_voice,
    handle_goals_command,
    handle_done_command,
    handle_record_command,
    handle_decision_command,
    handle_file,
    handle_costs_command,
)

logger = logging.getLogger(__name__)


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled exception in handler", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ Something went wrong. Try again in a moment."
            )
        except Exception:
            pass


def build_app() -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_error_handler(_error_handler)
    app.add_handler(CommandHandler("goals", handle_goals_command))
    app.add_handler(CommandHandler("done", handle_done_command))
    app.add_handler(CommandHandler("record", handle_record_command))
    app.add_handler(CommandHandler("decision", handle_decision_command))
    app.add_handler(CommandHandler("costs", handle_costs_command))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app
