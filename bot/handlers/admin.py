from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot import db
from bot.services.scheduler import today_str

logger = logging.getLogger(__name__)


async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all registered participants in this group."""
    chat = update.effective_chat
    message = update.effective_message

    if chat.type not in ("group", "supergroup"):
        await message.reply_text("Эта команда работает только в группах.")
        return

    participants = await db.get_all_active_participants()
    group_participants = [p for p in participants if p["chat_id"] == chat.id]

    if not group_participants:
        await message.reply_text("В этой группе нет зарегистрированных участников.")
        return

    lines = ["<b>Участники:</b>"]
    for i, p in enumerate(group_participants, 1):
        lines.append(
            f'{i}. <a href="tg://user?id={p["telegram_user_id"]}">'
            f'{p["display_name"]}</a>'
        )

    await message.reply_html("\n".join(lines))


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show today's diary status for all participants in this group."""
    chat = update.effective_chat
    message = update.effective_message

    if chat.type not in ("group", "supergroup"):
        await message.reply_text("Эта команда работает только в группах.")
        return

    participants = await db.get_all_active_participants()
    group_participants = [p for p in participants if p["chat_id"] == chat.id]

    if not group_participants:
        await message.reply_text("В этой группе нет зарегистрированных участников.")
        return

    date = today_str()
    lines = [f"<b>Статус дневников за {date}:</b>"]

    for p in group_participants:
        messages = await db.get_today_messages(p["id"], date)
        if messages:
            count = len(messages)
            status = f"✅ {count} сообщ."
        else:
            status = "❌ нет записей"

        lines.append(
            f'• <a href="tg://user?id={p["telegram_user_id"]}">'
            f'{p["display_name"]}</a>: {status}'
        )

    await message.reply_html("\n".join(lines))
