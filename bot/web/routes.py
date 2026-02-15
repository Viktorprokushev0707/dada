from __future__ import annotations

import logging

import aiohttp_jinja2
from aiohttp import web
from aiohttp_session import get_session

from bot import db
from bot.services.scheduler import today_str
from bot.web.auth import check_credentials, login_required

logger = logging.getLogger(__name__)


def setup_routes(app: web.Application) -> None:
    app.router.add_get("/", dashboard)
    app.router.add_get("/login", login_page)
    app.router.add_post("/login", login_post)
    app.router.add_get("/logout", logout)
    app.router.add_get("/participant/{pid}", participant_detail)


@aiohttp_jinja2.template("login.html")
async def login_page(request: web.Request) -> dict:
    session = await get_session(request)
    if session.get("authenticated"):
        raise web.HTTPFound("/")
    return {"error": None}


async def login_post(request: web.Request) -> web.Response:
    data = await request.post()
    username = data.get("username", "")
    password = data.get("password", "")

    if check_credentials(username, password):
        session = await get_session(request)
        session["authenticated"] = True
        raise web.HTTPFound("/")

    context = {"error": "Неверный логин или пароль"}
    return aiohttp_jinja2.render_template("login.html", request, context)


async def logout(request: web.Request) -> web.Response:
    session = await get_session(request)
    session.invalidate()
    raise web.HTTPFound("/login")


@login_required
@aiohttp_jinja2.template("dashboard.html")
async def dashboard(request: web.Request) -> dict:
    participants = await db.get_all_active_participants()
    date = today_str()

    participant_data = []
    for p in participants:
        messages = await db.get_today_messages(p["id"], date)
        participant_data.append({
            "id": p["id"],
            "display_name": p["display_name"],
            "telegram_user_id": p["telegram_user_id"],
            "chat_id": p["chat_id"],
            "sheet_tab_name": p["sheet_tab_name"],
            "today_messages": len(messages),
            "created_at": p["created_at"],
        })

    return {
        "participants": participant_data,
        "today": date,
        "total_participants": len(participants),
    }


@login_required
@aiohttp_jinja2.template("participant.html")
async def participant_detail(request: web.Request) -> dict:
    pid = int(request.match_info["pid"])
    date = today_str()

    # Get participant info
    conn = await db.get_db()
    async with conn.execute(
        "SELECT * FROM participants WHERE id = ?", (pid,)
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        raise web.HTTPNotFound()

    participant = dict(row)

    # Get today's messages
    today_messages = await db.get_today_messages(pid, date)

    # Get recent diary entries (last 30)
    async with conn.execute(
        """
        SELECT * FROM diary_entries
        WHERE participant_id = ?
        ORDER BY entry_date DESC
        LIMIT 30
        """,
        (pid,),
    ) as cursor:
        entries = [dict(r) for r in await cursor.fetchall()]

    return {
        "participant": participant,
        "today_messages": today_messages,
        "entries": entries,
        "today": date,
    }
