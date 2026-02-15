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


async def run_bot(stop_event: asyncio.Event) -> None:
    """Run Telegram bot with automatic retry on conflict errors."""
    bot_app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    bot_app.add_handler(CommandHandler("setup", setup_command))
    bot_app.add_handler(CommandHandler("list", list_command))
    bot_app.add_handler(CommandHandler("status", status_command))
    bot_app.add_handler(
        MessageHandler(
            filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND,
            collect_message,
        )
    )

    retry_delay = 5
    while not stop_event.is_set():
        try:
            async with bot_app:
                await bot_app.start()
                logger.info("Telegram bot polling started.")
                await bot_app.updater.start_polling(
                    allowed_updates=Update.ALL_TYPES,
                    drop_pending_updates=True,
                )
                await stop_event.wait()
                logger.info("Shutting down bot...")
                await bot_app.updater.stop()
                await bot_app.stop()
            break
        except Exception as exc:
            logger.error("Telegram bot error: %s. Retrying in %ds...", exc, retry_delay)
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)


async def run_all() -> None:
    """Run both Telegram bot and web admin panel concurrently."""
    logger.info("Starting diary bot + web panel...")

    await db.init_db()

    # Create and start web admin panel
    web_app = create_web_app()
    web_runner = await start_web_app(web_app)

    # Set up stop event for graceful shutdown
    stop_event = asyncio.Event()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    # Run bot in background — web panel stays alive even if bot fails
    bot_task = asyncio.create_task(run_bot(stop_event))

    await stop_event.wait()
    logger.info("Shutting down...")

    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        pass

    await web_runner.cleanup()
    await db.close_db()
    logger.info("All services stopped.")


def main() -> None:
    asyncio.run(run_all())


if __name__ == "__main__":
    main()
