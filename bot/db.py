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
        CREATE TABLE IF NOT EXISTS studies (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT    NOT NULL,
            spreadsheet_id  TEXT    NOT NULL,
            chat_id         INTEGER,
            is_active       INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS participants (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id INTEGER NOT NULL,
            chat_id         INTEGER NOT NULL,
            admin_user_id   INTEGER NOT NULL,
            display_name    TEXT    NOT NULL,
            sheet_tab_name  TEXT    NOT NULL,
            study_id        INTEGER REFERENCES studies(id),
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

        CREATE TABLE IF NOT EXISTS bot_settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_messages_participant_date
            ON messages(participant_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_diary_sync
            ON diary_entries(synced_to_sheet) WHERE synced_to_sheet = 0;
        """
    )
    await db.commit()

    # Migrate: add study_id column if missing
    try:
        await db.execute("SELECT study_id FROM participants LIMIT 1")
    except Exception:
        await db.execute(
            "ALTER TABLE participants ADD COLUMN study_id INTEGER REFERENCES studies(id)"
        )
        await db.commit()

    await _seed_default_settings()
    await _load_cache()


# ─── Settings helpers ─────────────────────────────────────────────

DEFAULT_SETTINGS = {
    "reminder_hour": str(settings.reminder_hour),
    "reminder_minute": str(settings.reminder_minute),
    "escalation_delay_minutes": str(settings.escalation_delay_minutes),
    "reminder_text": "ты ещё не написал(а) дневник сегодня! ✏️",
    "escalation_text": "так и не написал(а) дневник! ⚠️",
}


async def _seed_default_settings() -> None:
    db = await get_db()
    for key, value in DEFAULT_SETTINGS.items():
        await db.execute(
            "INSERT OR IGNORE INTO bot_settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    await db.commit()


async def get_setting(key: str) -> str:
    db = await get_db()
    async with db.execute(
        "SELECT value FROM bot_settings WHERE key = ?", (key,)
    ) as cursor:
        row = await cursor.fetchone()
    if row:
        return row["value"]
    return DEFAULT_SETTINGS.get(key, "")


async def get_all_settings() -> dict[str, str]:
    db = await get_db()
    async with db.execute("SELECT key, value FROM bot_settings") as cursor:
        rows = await cursor.fetchall()
    return {r["key"]: r["value"] for r in rows}


async def update_setting(key: str, value: str) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO bot_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await db.commit()


# ─── Studies ──────────────────────────────────────────────────────

async def create_study(
    name: str, spreadsheet_id: str, chat_id: int | None = None
) -> dict[str, Any]:
    db = await get_db()
    await db.execute("UPDATE studies SET is_active = 0")
    await db.execute(
        "INSERT INTO studies (name, spreadsheet_id, chat_id, is_active) VALUES (?, ?, ?, 1)",
        (name, spreadsheet_id, chat_id),
    )
    await db.commit()
    async with db.execute(
        "SELECT * FROM studies ORDER BY id DESC LIMIT 1"
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row)


async def get_active_study() -> dict[str, Any] | None:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM studies WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else None


async def get_all_studies() -> list[dict[str, Any]]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM studies ORDER BY created_at DESC"
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_study_by_id(study_id: int) -> dict[str, Any] | None:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM studies WHERE id = ?", (study_id,)
    ) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else None


async def finish_study(study_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE studies SET is_active = 0 WHERE id = ?", (study_id,)
    )
    await db.commit()


async def get_study_participants(study_id: int) -> list[dict[str, Any]]:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM participants WHERE study_id = ? AND active = 1",
        (study_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


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
    study_id: int | None = None,
) -> dict[str, Any]:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO participants
            (telegram_user_id, chat_id, admin_user_id, display_name, sheet_tab_name, study_id)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(telegram_user_id, chat_id) DO UPDATE SET
            admin_user_id = excluded.admin_user_id,
            display_name = excluded.display_name,
            sheet_tab_name = excluded.sheet_tab_name,
            study_id = excluded.study_id,
            active = 1
        """,
        (telegram_user_id, chat_id, admin_user_id, display_name, sheet_tab_name, study_id),
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
        SELECT de.*, p.sheet_tab_name, p.display_name, p.study_id
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
