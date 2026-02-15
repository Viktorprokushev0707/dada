from __future__ import annotations

import asyncio
import logging
import signal
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
from bot.web.app import create_web_app, start_web_app

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


async def run_all() -> None:
    """Run both Telegram bot and web admin panel concurrently."""
    logger.info("Starting diary bot + web panel...")

    # Build Telegram bot application
    bot_app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Command handlers
    bot_app.add_handler(CommandHandler("setup", setup_command))
    bot_app.add_handler(CommandHandler("list", list_command))
    bot_app.add_handler(CommandHandler("status", status_command))

    # Message handler: collect text from groups (non-commands only)
    bot_app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            collect_message,
        )
    )

    # Create and start web admin panel
    web_app = create_web_app()
    web_runner = await start_web_app(web_app)

    # Start bot using lower-level API (so we can run alongside web server)
    async with bot_app:
        await bot_app.start()
        logger.info("Polling started.")
        await bot_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

        # Wait until interrupted
        stop_event = asyncio.Event()
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        await stop_event.wait()

        logger.info("Shutting down...")
        await bot_app.updater.stop()
        await bot_app.stop()

    # Cleanup web server
    await web_runner.cleanup()
    logger.info("All services stopped.")


def main() -> None:
    asyncio.run(run_all())


if __name__ == "__main__":
    main()
