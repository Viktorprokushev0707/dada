from __future__ import annotations

import functools

from aiohttp import web
from aiohttp_session import get_session

from bot.config import settings


def login_required(handler):
    """Decorator that redirects to /login if user is not authenticated."""

    @functools.wraps(handler)
    async def wrapper(request: web.Request) -> web.StreamResponse:
        session = await get_session(request)
        if not session.get("authenticated"):
            raise web.HTTPFound("/login")
        return await handler(request)

    return wrapper


def check_credentials(username: str, password: str) -> bool:
    return username == settings.admin_username and password == settings.admin_password
