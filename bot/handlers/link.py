from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot import db

logger = logging.getLogger(__name__)


async def link_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /link command. Links this group to a study.

    Usage:
        /link          — show current link and available studies
        /link <id>     — link this group to study with given ID
        /unlink        — remove link
    """
    message = update.effective_message
    chat = update.effective_chat

    if chat.type not in ("group", "supergroup"):
        await message.reply_text("Эта команда работает только в группах.")
        return

    # Check if sender is admin
    admin_user = update.effective_user
    try:
        member = await context.bot.get_chat_member(chat.id, admin_user.id)
        if member.status not in ("administrator", "creator"):
            await message.reply_text("Только администратор может выполнить /link.")
            return
    except Exception:
        logger.exception("Failed to check admin status")
        await message.reply_text("Не удалось проверить права администратора.")
        return

    args = context.args

    # No args — show current link + list of available studies
    if not args:
        current_study = await db.get_study_for_chat(chat.id)
        active_studies = await db.get_active_studies()

        lines = []
        if current_study:
            lines.append(
                f"Группа привязана к: <b>{current_study['name']}</b> "
                f"(ID: {current_study['id']})\n"
            )
        else:
            lines.append("Группа не привязана к исследованию.\n")

        if active_studies:
            lines.append("<b>Доступные исследования:</b>")
            for s in active_studies:
                marker = " ← текущее" if current_study and s["id"] == current_study["id"] else ""
                lines.append(f"  /link {s['id']} — {s['name']}{marker}")
        else:
            lines.append("Нет активных исследований. Создайте в админ-панели.")

        await message.reply_html("\n".join(lines))
        return

    # Parse study ID
    try:
        study_id = int(args[0])
    except (ValueError, IndexError):
        await message.reply_text("Использование: /link <ID исследования>")
        return

    # Check study exists and is active
    study = await db.get_study_by_id(study_id)
    if not study:
        await message.reply_text(f"Исследование с ID {study_id} не найдено.")
        return
    if not study["is_active"]:
        await message.reply_text(
            f"Исследование «{study['name']}» завершено. "
            "Выберите активное исследование."
        )
        return

    await db.link_group_to_study(study_id, chat.id)

    await message.reply_html(
        f"Группа привязана к исследованию: <b>{study['name']}</b>\n"
        f"Теперь используйте /setup для регистрации участников."
    )
    logger.info(
        "Group %d linked to study %d (%s) by admin %d",
        chat.id, study_id, study["name"], admin_user.id,
    )


async def unlink_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /unlink command. Removes group-study link."""
    message = update.effective_message
    chat = update.effective_chat

    if chat.type not in ("group", "supergroup"):
        await message.reply_text("Эта команда работает только в группах.")
        return

    admin_user = update.effective_user
    try:
        member = await context.bot.get_chat_member(chat.id, admin_user.id)
        if member.status not in ("administrator", "creator"):
            await message.reply_text("Только администратор может выполнить /unlink.")
            return
    except Exception:
        logger.exception("Failed to check admin status")
        await message.reply_text("Не удалось проверить права администратора.")
        return

    current_study = await db.get_study_for_chat(chat.id)
    if not current_study:
        await message.reply_text("Группа и так не привязана к исследованию.")
        return

    await db.unlink_group(chat.id)
    await message.reply_html(
        f"Группа отвязана от исследования «{current_study['name']}».\n"
        f"Участники останутся, но новые /setup не будут работать."
    )
