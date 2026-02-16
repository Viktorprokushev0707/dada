from __future__ import annotations

import asyncio
import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

import gspread

from bot import db
from bot.services.sheets import sheets_service

logger = logging.getLogger(__name__)


def _sanitize_tab_name(name: str) -> str:
    """Make a valid Google Sheets tab name (max 100 chars, no special chars)."""
    name = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE)
    return name[:100].strip() or "participant"


async def setup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /setup command. Must be a reply to the participant's message."""
    message = update.effective_message
    chat = update.effective_chat

    if chat.type not in ("group", "supergroup"):
        await message.reply_text("Эта команда работает только в группах.")
        return

    if not message.reply_to_message:
        await message.reply_text(
            "Ответьте (Reply) на сообщение участника и напишите /setup"
        )
        return

    admin_user = update.effective_user
    target_user = message.reply_to_message.from_user

    if target_user.is_bot:
        await message.reply_text("Нельзя зарегистрировать бота как участника.")
        return

    # Check if sender is admin
    try:
        member = await context.bot.get_chat_member(chat.id, admin_user.id)
        if member.status not in ("administrator", "creator"):
            await message.reply_text("Только администратор может выполнить /setup.")
            return
    except Exception:
        logger.exception("Failed to check admin status")
        await message.reply_text("Не удалось проверить права администратора.")
        return

    display_name = target_user.full_name or target_user.username or str(target_user.id)
    tab_name = _sanitize_tab_name(display_name)

    # Ensure unique tab name by appending user_id if needed
    tab_name_final = f"{tab_name}_{target_user.id}"

    # Get study linked to this group
    study = await db.get_study_for_chat(chat.id)
    if not study:
        await message.reply_text(
            "Эта группа не привязана к исследованию.\n"
            "Сначала привяжите группу: /link <ID исследования>\n"
            "Список исследований можно посмотреть в админ-панели."
        )
        return

    spreadsheet_id = study["spreadsheet_id"]
    study_id = study["id"]

    # Create Google Sheets tab in study's spreadsheet
    try:
        await asyncio.to_thread(sheets_service.ensure_tab, tab_name_final, spreadsheet_id)
    except gspread.SpreadsheetNotFound:
        try:
            email = sheets_service.get_service_account_email()
        except Exception:
            email = "(не удалось получить)"
        logger.exception("Spreadsheet %s not found or no access", spreadsheet_id)
        await message.reply_html(
            "Таблица не найдена или нет доступа.\n\n"
            "Откройте Google таблицу → Настройки доступа → "
            "добавьте как <b>Редактор</b>:\n"
            f"<code>{email}</code>\n\n"
            "После этого повторите /setup."
        )
        return
    except gspread.exceptions.APIError as e:
        logger.exception("Google API error for spreadsheet %s", spreadsheet_id)
        await message.reply_text(
            f"Ошибка Google API: {e}\n"
            "Возможно, нет прав на редактирование таблицы."
        )
        return
    except Exception as e:
        logger.exception("Failed to create Sheets tab for spreadsheet %s", spreadsheet_id)
        await message.reply_text(
            f"Не удалось создать вкладку: {type(e).__name__}: {e}\n"
            "Попробуйте /setup ещё раз."
        )
        return

    # Save to DB
    participant = await db.add_participant(
        telegram_user_id=target_user.id,
        chat_id=chat.id,
        admin_user_id=admin_user.id,
        display_name=display_name,
        sheet_tab_name=tab_name_final,
        study_id=study_id,
    )

    logger.info(
        "Registered participant %s (id=%d) in chat %d for study %d by admin %d",
        display_name,
        target_user.id,
        chat.id,
        study_id,
        admin_user.id,
    )

    target_mention = target_user.mention_html()
    await message.reply_html(
        f"Готово! Дневник для {target_mention} активирован.\n"
        f"Исследование: <b>{study['name']}</b>\n"
        f"Все текстовые сообщения будут записываться в дневник.\n"
        f"Вкладка в таблице: <b>{tab_name_final}</b>"
    )
