from __future__ import annotations

import logging

import gspread

from bot.config import settings

logger = logging.getLogger(__name__)


class SheetsService:
    """Google Sheets integration for diary entries."""

    def __init__(self) -> None:
        self._gc: gspread.Client | None = None
        self._spreadsheets: dict[str, gspread.Spreadsheet] = {}

    def _get_client(self) -> gspread.Client:
        if self._gc is None:
            creds_path = settings.get_google_credentials_path()
            self._gc = gspread.service_account(filename=creds_path)
        return self._gc

    def _get_spreadsheet(self, spreadsheet_id: str | None = None) -> gspread.Spreadsheet:
        sid = spreadsheet_id or settings.google_spreadsheet_id
        if sid not in self._spreadsheets:
            gc = self._get_client()
            self._spreadsheets[sid] = gc.open_by_key(sid)
        return self._spreadsheets[sid]

    def get_service_account_email(self) -> str:
        """Return the service account email for sharing instructions."""
        gc = self._get_client()
        return gc.auth.service_account_email

    def check_access(self, spreadsheet_id: str) -> tuple[bool, str]:
        """Check if service account can access the spreadsheet.

        Returns (success, message).
        """
        try:
            gc = self._get_client()
            sp = gc.open_by_key(spreadsheet_id)
            title = sp.title
            # Cache it for later use
            self._spreadsheets[spreadsheet_id] = sp
            return True, f"Доступ к таблице «{title}» подтверждён."
        except gspread.SpreadsheetNotFound:
            email = self.get_service_account_email()
            return False, (
                f"Таблица не найдена или нет доступа.\n"
                f"Откройте таблицу в Google Sheets и дайте доступ "
                f"(Редактор) этому email:\n\n"
                f"<code>{email}</code>"
            )
        except gspread.exceptions.APIError as e:
            return False, f"Ошибка Google API: {e}"
        except Exception as e:
            return False, f"Ошибка подключения: {type(e).__name__}: {e}"

    def ensure_tab(self, tab_name: str, spreadsheet_id: str | None = None) -> None:
        """Create worksheet tab if it doesn't exist, with header row."""
        spreadsheet = self._get_spreadsheet(spreadsheet_id)
        try:
            spreadsheet.worksheet(tab_name)
            logger.info("Tab '%s' already exists in spreadsheet %s", tab_name, spreadsheet_id)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(
                title=tab_name, rows=1000, cols=5
            )
            ws.update([["Дата", "Время", "Статус", "Дневник"]], "A1:D1")
            ws.format("A1:D1", {"textFormat": {"bold": True}})
            logger.info("Created tab '%s' in spreadsheet %s", tab_name, spreadsheet_id)

    def append_entry(
        self,
        tab_name: str,
        date: str,
        time: str,
        status: str,
        text: str,
        spreadsheet_id: str | None = None,
    ) -> None:
        """Append a diary entry row to the participant's tab."""
        spreadsheet = self._get_spreadsheet(spreadsheet_id)
        ws = spreadsheet.worksheet(tab_name)
        ws.append_row(
            [date, time, status, text],
            value_input_option="USER_ENTERED",
        )
        logger.info("Appended entry to tab '%s': date=%s status=%s", tab_name, date, status)


sheets_service = SheetsService()
