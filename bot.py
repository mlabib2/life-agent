import logging
import anthropic
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from config import settings
from context import build_context, build_messages, SYSTEM_PROMPT
from db import get_or_create_user, save_message
from tools import TOOLS, handle_tool_call

logger = logging.getLogger(__name__)
claude = anthropic.Anthropic(api_key=settings.anthropic_api_key)


async def _is_authorized(update: Update) -> bool:
    user_id = update.effective_user.id if update.effective_user else None
    if user_id != settings.telegram_user_id:
        logger.warning("Unauthorized message from user_id=%s", user_id)
        return False
    return True


def _call_claude(system: str, messages: list[dict], user_id: int) -> str:
    while True:
        response = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system,
            messages=messages,
            tools=TOOLS,
        )

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    logger.info("Tool call: %s — %s", block.name, block.input)
                    result = handle_tool_call(block.name, block.input, user_id)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
        else:
            return next(
                block.text for block in response.content if hasattr(block, "text")
            )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _is_authorized(update):
        return

    user_text = update.message.text or ""
    if not user_text.strip():
        return

    await update.message.chat.send_action("typing")

    user = get_or_create_user(settings.telegram_user_id)
    user_id = user["id"]

    db_context = build_context(user)
    system = f"{SYSTEM_PROMPT}\n\n{db_context}"
    messages = build_messages(user, user_text)

    reply = _call_claude(system, messages, user_id)

    await update.message.reply_text(reply)

    save_message(user_id, "user", user_text)
    save_message(user_id, "assistant", reply)


def build_app() -> Application:
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(MessageHandler(filters.TEXT, handle_message))
    return app
