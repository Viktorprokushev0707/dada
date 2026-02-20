# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Telegram diary bot ("DADA") that collects daily diary entries from participants in Telegram group chats and syncs them to Google Sheets. Includes a web admin panel for managing studies and participants.

## Running the Project

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot + web panel (single process)
python -m bot

# The app starts both Telegram polling and aiohttp web server on port 8080
```

Required environment: copy `.env.example` to `.env` and fill in values. For Railway/cloud, set `GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT` with raw JSON instead of a file path.

## Architecture

### Dual-service single-process design

`bot/__main__.py` runs both services concurrently via `asyncio`:
- **Telegram bot** — python-telegram-bot 21.6 with polling (auto-retries on crash)
- **Web admin panel** — aiohttp + Jinja2 on configurable port

The web panel survives bot crashes (separate asyncio task). Graceful shutdown via `asyncio.Event` + signal handlers.

### Data flow: message → diary entry → Google Sheets

1. Participants send text messages in linked Telegram groups
2. `handlers/diary.py` stores each message in `messages` table
3. At 23:59 daily, `services/scheduler.py` flushes all messages into consolidated `diary_entries` (one per participant per day)
4. Entry is appended to participant's tab in Google Sheets via `services/sheets.py`
5. Messages table is cleared for the next day
6. Unsynced entries retry every 30 minutes

### Multi-study model

- Studies are independent research projects created via web panel
- Telegram groups link to a study via `/link <study_id>` command
- Each participant gets their own Google Sheets tab within the study's spreadsheet

### Key modules

| Module | Responsibility |
|--------|---------------|
| `bot/db.py` | SQLite via aiosqlite. Schema (7 tables), all queries, in-memory participant cache |
| `bot/config.py` | Pydantic Settings — loads from `.env` or environment variables |
| `bot/services/scheduler.py` | Daily flush (23:59), reminders, escalation to admin, retry sync |
| `bot/services/sheets.py` | Google Sheets API via gspread — tab creation, row append, access checks |
| `bot/handlers/` | Telegram command handlers: `/setup`, `/link`, `/unlink`, `/list`, `/status` |
| `bot/web/` | Admin panel: login auth, dashboard, study/participant management, settings |

### Database

SQLite at `data/diary_bot.sqlite3`. Key tables: `studies`, `participants`, `messages`, `diary_entries`, `study_groups`, `bot_settings`. On Railway, the `data/` directory is a persistent volume.

### Reminder & escalation pipeline

1. At configurable time (default 20:00) — remind participants with no entries
2. After `ESCALATION_DELAY_MINUTES` (default 60) — notify admin
3. Entries before reminder = "вовремя", after = "поздно", none = "пропущено"

## Deployment

Deployed on Railway via Dockerfile. `railway.toml` configures persistent volume at `/app/data` for SQLite. The `Procfile` runs `python -m bot`.

## Language

The bot interface and user-facing strings are in **Russian**. Status values: "вовремя" (on-time), "поздно" (late), "пропущено" (missed).
