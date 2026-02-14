from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dt_time, timedelta

import pytz
from telegram.ext import Application, ContextTypes

from bot import db
from bot.config import settings
from bot.services.sheets import sheets_service

logger = logging.getLogger(__name__)


def get_tz():
    return pytz.timezone(settings.timezone)


def today_str() -> str:
    return datetime.now(get_tz()).strftime("%Y-%m-%d")


def now_time_str() -> str:
    return datetime.now(get_tz()).strftime("%H:%M")


def register_jobs(application: Application) -> None:
    """Register all scheduled jobs."""
    tz = get_tz()
    jq = application.job_queue

    # Daily reminder at REMINDER_HOUR:REMINDER_MINUTE
    jq.run_daily(
        reminder_callback,
        time=dt_time(
            hour=settings.reminder_hour,
            minute=settings.reminder_minute,
            tzinfo=tz,
        ),
        name="daily_reminder",
    )

    # Daily flush at 23:59
    jq.run_daily(
        flush_callback,
        time=dt_time(hour=23, minute=59, tzinfo=tz),
        name="daily_flush",
    )

    # Retry unsynced entries every 30 minutes
    jq.run_repeating(
        retry_sync_callback,
        interval=1800,
        first=60,
        name="retry_sync",
    )

    logger.info(
        "Scheduled jobs: reminder at %02d:%02d, flush at 23:59, retry every 30min",
        settings.reminder_hour,
        settings.reminder_minute,
    )


async def reminder_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check all participants for missing diaries and send reminders."""
    date = today_str()
    participants = await db.get_all_active_participants()

    for p in participants:
        try:
            messages = await db.get_today_messages(p["id"], date)
            if not messages:
                # Send reminder mentioning participant
                try:
                    await context.bot.send_message(
                        chat_id=p["chat_id"],
                        text=(
                            f'<a href="tg://user?id={p["telegram_user_id"]}">'
                            f'{p["display_name"]}</a>, '
                            f"ты ещё не написал(а) дневник сегодня! ✏️"
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.exception(
                        "Failed to send reminder for participant %d in chat %d",
                        p["id"],
                        p["chat_id"],
                    )

                # Schedule escalation
                context.job_queue.run_once(
                    escalation_callback,
                    when=timedelta(minutes=settings.escalation_delay_minutes),
                    data={
                        "participant_id": p["id"],
                        "chat_id": p["chat_id"],
                        "admin_user_id": p["admin_user_id"],
                        "telegram_user_id": p["telegram_user_id"],
                        "display_name": p["display_name"],
                        "date": date,
                    },
                    name=f"escalation_{p['id']}_{date}",
                )
        except Exception:
            logger.exception("Error in reminder for participant %d", p["id"])


async def escalation_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Escalate to admin if diary is still missing."""
    data = context.job.data
    messages = await db.get_today_messages(data["participant_id"], data["date"])

    if not messages:
        try:
            await context.bot.send_message(
                chat_id=data["chat_id"],
                text=(
                    f'<a href="tg://user?id={data["admin_user_id"]}">Админ</a>, '
                    f'<a href="tg://user?id={data["telegram_user_id"]}">'
                    f'{data["display_name"]}</a> '
                    f"так и не написал(а) дневник! ⚠️"
                ),
                parse_mode="HTML",
            )
        except Exception:
            logger.exception(
                "Failed to send escalation for participant %d",
                data["participant_id"],
            )


async def flush_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Flush daily messages into diary entries and sync to Sheets."""
    date = today_str()
    tz = get_tz()
    reminder_time = dt_time(
        hour=settings.reminder_hour, minute=settings.reminder_minute
    )
    participants = await db.get_all_active_participants()

    for p in participants:
        try:
            messages = await db.get_today_messages(p["id"], date)

            if messages:
                full_text = "\n\n".join(m["message_text"] for m in messages)
                first_time_str = messages[0]["created_at"]
                # Parse time from SQLite datetime
                try:
                    first_dt = datetime.strptime(first_time_str, "%Y-%m-%d %H:%M:%S")
                    first_time = first_dt.time()
                    entry_time = first_dt.strftime("%H:%M")
                except ValueError:
                    first_time = None
                    entry_time = ""

                if first_time and first_time < reminder_time:
                    status = "вовремя"
                else:
                    status = "поздно"
            else:
                full_text = ""
                entry_time = ""
                status = "пропущено"

            entry_id = await db.upsert_diary_entry(
                participant_id=p["id"],
                entry_date=date,
                entry_time=entry_time,
                status=status,
                full_text=full_text,
            )

            # Sync to Google Sheets
            try:
                await asyncio.to_thread(
                    sheets_service.append_entry,
                    p["sheet_tab_name"],
                    date,
                    entry_time,
                    status,
                    full_text or "(пусто)",
                )
                await db.mark_synced(entry_id)
            except Exception:
                logger.exception(
                    "Failed to sync entry %d to Sheets", entry_id
                )

            # Clean up processed messages
            await db.delete_day_messages(p["id"], date)

        except Exception:
            logger.exception("Error flushing diary for participant %d", p["id"])


async def retry_sync_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retry syncing unsynced diary entries to Google Sheets."""
    entries = await db.get_unsynced_entries()
    if not entries:
        return

    logger.info("Retrying sync for %d entries", len(entries))

    for entry in entries:
        try:
            await asyncio.to_thread(
                sheets_service.append_entry,
                entry["sheet_tab_name"],
                entry["entry_date"],
                entry["entry_time"] or "",
                entry["status"],
                entry["full_text"] or "(пусто)",
            )
            await db.mark_synced(entry["id"])
            logger.info("Synced entry %d", entry["id"])
        except Exception:
            logger.exception("Failed to retry sync for entry %d", entry["id"])
