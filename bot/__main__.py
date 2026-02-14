from __future__ import annotations

import logging
import sys

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot import db
from bot.config import settings
from bot.handlers.admin import list_command, status_command
from bot.handlers.diary import collect_message
from bot.handlers.setup import setup_command
from bot.services.scheduler import register_jobs

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def post_init(application) -> None:
    """Run after Application.initialize(), before polling starts."""
    await db.init_db()
    register_jobs(application)
    logger.info("Bot initialized. DB ready, jobs scheduled.")


async def post_shutdown(application) -> None:
    """Clean up on shutdown."""
    await db.close_db()
    logger.info("Bot shut down. DB closed.")


def main() -> None:
    logger.info("Starting diary bot...")

    app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Command handlers
    app.add_handler(CommandHandler("setup", setup_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("status", status_command))

    # Message handler: collect text from groups (non-commands only)
    app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            collect_message,
        )
    )

    logger.info("Polling started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
