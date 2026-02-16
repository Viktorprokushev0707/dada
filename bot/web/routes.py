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
    app.router.add_post("/study/create", study_create)
    app.router.add_post("/study/{sid}/finish", study_finish)
    app.router.add_post("/settings", settings_save)


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
    date = today_str()

    # Get all active studies with their participants and group links
    active_studies = await db.get_active_studies()
    studies_data = []
    total_participants = 0

    for study in active_studies:
        participants = await db.get_study_participants(study["id"])
        groups = await db.get_study_groups(study["id"])
        study_parts = []
        for p in participants:
            messages = await db.get_today_messages(p["id"], date)
            study_parts.append({
                "id": p["id"],
                "display_name": p["display_name"],
                "telegram_user_id": p["telegram_user_id"],
                "chat_id": p["chat_id"],
                "sheet_tab_name": p["sheet_tab_name"],
                "today_messages": len(messages),
                "created_at": p["created_at"],
            })
        total_participants += len(study_parts)
        studies_data.append({
            "study": study,
            "participants": study_parts,
            "groups": groups,
        })

    all_studies = await db.get_all_studies()
    bot_settings = await db.get_all_settings()

    return {
        "active_studies": studies_data,
        "all_studies": all_studies,
        "settings": bot_settings,
        "today": date,
        "total_participants": total_participants,
    }


@login_required
async def study_create(request: web.Request) -> web.Response:
    data = await request.post()
    name = data.get("name", "").strip()
    spreadsheet_id = data.get("spreadsheet_id", "").strip()

    if not name or not spreadsheet_id:
        raise web.HTTPFound("/")

    await db.create_study(name=name, spreadsheet_id=spreadsheet_id)
    raise web.HTTPFound("/")


@login_required
async def study_finish(request: web.Request) -> web.Response:
    sid = int(request.match_info["sid"])
    await db.finish_study(sid)
    raise web.HTTPFound("/")


@login_required
async def settings_save(request: web.Request) -> web.Response:
    data = await request.post()

    for key in ("reminder_hour", "reminder_minute", "escalation_delay_minutes",
                "reminder_text", "escalation_text"):
        value = data.get(key, "").strip()
        if value:
            await db.update_setting(key, value)

    raise web.HTTPFound("/")


@login_required
@aiohttp_jinja2.template("participant.html")
async def participant_detail(request: web.Request) -> dict:
    pid = int(request.match_info["pid"])
    date = today_str()

    conn = await db.get_db()
    async with conn.execute(
        "SELECT * FROM participants WHERE id = ?", (pid,)
    ) as cursor:
        row = await cursor.fetchone()

    if not row:
        raise web.HTTPNotFound()

    participant = dict(row)
    today_messages = await db.get_today_messages(pid, date)

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
