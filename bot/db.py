from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from bot.config import settings

logger = logging.getLogger(__name__)

# In-memory cache: (telegram_user_id, chat_id) -> participant row
_participant_cache: dict[tuple[int, int], dict[str, Any]] = {}

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        Path(settings.db_path).parent.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(str(settings.db_path))
        _db.row_factory = aiosqlite.Row
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def init_db() -> None:
    db = await get_db()
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS participants (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            chat_id         INTEGER NOT NULL,
            admin_user_id   INTEGER NOT NULL,
            display_name    TEXT    NOT NULL,
            sheet_tab_name  TEXT    NOT NULL,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            active          INTEGER NOT NULL DEFAULT 1,
            UNIQUE(telegram_user_id, chat_id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            participant_id  INTEGER NOT NULL REFERENCES participants(id),
            chat_id         INTEGER NOT NULL,
            message_text    TEXT    NOT NULL,
            telegram_msg_id INTEGER,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS diary_entries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            participant_id  INTEGER NOT NULL REFERENCES participants(id),
            entry_date      TEXT    NOT NULL,
            entry_time      TEXT,
            status          TEXT    NOT NULL DEFAULT 'pending',
            full_text       TEXT,
            synced_to_sheet INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE(participant_id, entry_date)
        );

        CREATE INDEX IF NOT EXISTS idx_messages_participant_date
            ON messages(participant_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_diary_sync
            ON diary_entries(synced_to_sheet) WHERE synced_to_sheet = 0;
        """
    )
    await db.commit()
    await _load_cache()


async def _load_cache() -> None:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM participants WHERE active = 1"
    ) as cursor:
        rows = await cursor.fetchall()
    _participant_cache.clear()
    for row in rows:
        key = (row["telegram_user_id"], row["chat_id"])
        _participant_cache[key] = dict(row)
    logger.info("Loaded %d participants into cache", len(_participant_cache))


async def add_participant(
    telegram_user_id: int,
    chat_id: int,
    admin_user_id: int,
    display_name: str,
    sheet_tab_name: str,
) -> dict[str, Any]:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO participants
            (telegram_user_id, chat_id, admin_user_id, display_name, sheet_tab_name)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(telegram_user_id, chat_id) DO UPDATE SET
            admin_user_id = excluded.admin_user_id,
            display_name = excluded.display_name,
            sheet_tab_name = excluded.sheet_tab_name,
            active = 1
        """,
        (telegram_user_id, chat_id, admin_user_id, display_name, sheet_tab_name),
    )
    await db.commit()

    async with db.execute(
        "SELECT * FROM participants WHERE telegram_user_id = ? AND chat_id = ?",
        (telegram_user_id, chat_id),
    ) as cursor:
        row = await cursor.fetchone()

    participant = dict(row)
    _participant_cache[(telegram_user_id, chat_id)] = participant
    return participant


def get_participant_cached(
    telegram_user_id: int, chat_id: int
) -> dict[str, Any] | None:
    return _participant_cache.get((telegram_user_id, chat_id))


async def get_all_active_participants() -> list[dict[str, Any]]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM participants WHERE active = 1"
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def save_message(
    participant_id: int,
    chat_id: int,
    message_text: str,
    telegram_msg_id: int | None = None,
) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO messages (participant_id, chat_id, message_text, telegram_msg_id)
        VALUES (?, ?, ?, ?)
        """,
        (participant_id, chat_id, message_text, telegram_msg_id),
    )
    await db.commit()


async def get_today_messages(
    participant_id: int, date_str: str
) -> list[dict[str, Any]]:
    db = await get_db()
    async with db.execute(
        """
        SELECT * FROM messages
        WHERE participant_id = ? AND date(created_at) = ?
        ORDER BY created_at ASC
        """,
        (participant_id, date_str),
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def upsert_diary_entry(
    participant_id: int,
    entry_date: str,
    entry_time: str | None,
    status: str,
    full_text: str | None,
) -> int:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO diary_entries (participant_id, entry_date, entry_time, status, full_text)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(participant_id, entry_date) DO UPDATE SET
            entry_time = excluded.entry_time,
            status = excluded.status,
            full_text = excluded.full_text,
            synced_to_sheet = 0
        """,
        (participant_id, entry_date, entry_time, status, full_text),
    )
    await db.commit()

    async with db.execute(
        "SELECT id FROM diary_entries WHERE participant_id = ? AND entry_date = ?",
        (participant_id, entry_date),
    ) as cursor:
        row = await cursor.fetchone()
    return row["id"]


async def get_unsynced_entries() -> list[dict[str, Any]]:
    db = await get_db()
    async with db.execute(
        """
        SELECT de.*, p.sheet_tab_name, p.display_name
        FROM diary_entries de
        JOIN participants p ON de.participant_id = p.id
        WHERE de.synced_to_sheet = 0 AND de.status != 'pending'
        """
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def mark_synced(entry_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE diary_entries SET synced_to_sheet = 1 WHERE id = ?",
        (entry_id,),
    )
    await db.commit()


async def delete_day_messages(participant_id: int, date_str: str) -> None:
    db = await get_db()
    await db.execute(
        "DELETE FROM messages WHERE participant_id = ? AND date(created_at) = ?",
        (participant_id, date_str),
    )
    await db.commit()
