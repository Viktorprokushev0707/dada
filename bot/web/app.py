from __future__ import annotations

import base64
import logging
from pathlib import Path

import aiohttp_jinja2
import jinja2
from aiohttp import web
from aiohttp_session import setup as session_setup
from aiohttp_session.cookie_storage import EncryptedCookieStorage
from bot.config import settings
from bot.web.routes import setup_routes

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _make_cookie_key(secret: str) -> bytes:
    """Derive a 32-byte key from the secret string for cookie encryption."""
    raw = secret.encode("utf-8")
    # Pad or hash to get exactly 32 bytes
    key = (raw * 3)[:32]
    return base64.urlsafe_b64encode(key)


def create_web_app() -> web.Application:
    app = web.Application()

    # Session middleware (encrypted cookies)
    cookie_key = _make_cookie_key(settings.secret_key)
    session_setup(app, EncryptedCookieStorage(cookie_key, max_age=86400))

    # Jinja2 templates
    aiohttp_jinja2.setup(
        app,
        loader=jinja2.FileSystemLoader(str(TEMPLATES_DIR)),
    )

    setup_routes(app)

    logger.info("Web admin panel created on port %d", settings.get_web_port())
    return app


async def start_web_app(app: web.Application) -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.get_web_port())
    await site.start()
    logger.info("Web admin panel started at http://0.0.0.0:%d", settings.get_web_port())
    return runner
