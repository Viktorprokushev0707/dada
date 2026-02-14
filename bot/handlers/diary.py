from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot import db

logger = logging.getLogger(__name__)


async def collect_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Collect text messages from registered participants."""
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat

    if not message or not user or not chat:
        return

    if not message.text:
        return

    participant = db.get_participant_cached(user.id, chat.id)
    if participant is None:
        return

    await db.save_message(
        participant_id=participant["id"],
        chat_id=chat.id,
        message_text=message.text,
        telegram_msg_id=message.message_id,
    )
