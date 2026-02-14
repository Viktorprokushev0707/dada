from __future__ import annotations

import logging

import gspread

from bot.config import settings

logger = logging.getLogger(__name__)


class SheetsService:
    """Google Sheets integration for diary entries."""

    def __init__(self) -> None:
        self._spreadsheet: gspread.Spreadsheet | None = None

    def _get_spreadsheet(self) -> gspread.Spreadsheet:
        if self._spreadsheet is None:
            creds_path = settings.get_google_credentials_path()
            gc = gspread.service_account(filename=creds_path)
            self._spreadsheet = gc.open_by_key(settings.google_spreadsheet_id)
        return self._spreadsheet

    def ensure_tab(self, tab_name: str) -> None:
        """Create worksheet tab if it doesn't exist, with header row."""
        spreadsheet = self._get_spreadsheet()
        try:
            spreadsheet.worksheet(tab_name)
            logger.info("Tab '%s' already exists", tab_name)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(
                title=tab_name, rows=1000, cols=5
            )
            ws.update([["Дата", "Время", "Статус", "Дневник"]], "A1:D1")
            ws.format("A1:D1", {"textFormat": {"bold": True}})
            logger.info("Created tab '%s'", tab_name)

    def append_entry(
        self,
        tab_name: str,
        date: str,
        time: str,
        status: str,
        text: str,
    ) -> None:
        """Append a diary entry row to the participant's tab."""
        spreadsheet = self._get_spreadsheet()
        ws = spreadsheet.worksheet(tab_name)
        ws.append_row(
            [date, time, status, text],
            value_input_option="USER_ENTERED",
        )
        logger.info("Appended entry to tab '%s': date=%s status=%s", tab_name, date, status)


sheets_service = SheetsService()
