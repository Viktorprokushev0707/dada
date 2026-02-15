from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str

    db_path: Path = Path("./data/diary_bot.sqlite3")

    google_spreadsheet_id: str = ""
    google_service_account_json: Path = Path("./service-account.json")
    # For cloud deployments: paste JSON content directly
    google_service_account_json_content: str = ""

    timezone: str = "Europe/Moscow"

    reminder_hour: int = 20
    reminder_minute: int = 0
    escalation_delay_minutes: int = 60

    # Web admin panel
    admin_username: str = "admin"
    admin_password: str = "changeme"
    port: int = 8080  # Railway sets PORT automatically
    web_port: int = 0  # If set, overrides PORT
    secret_key: str = "change-this-secret-key-in-production"

    def get_web_port(self) -> int:
        return self.web_port if self.web_port else self.port

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def get_google_credentials_path(self) -> str:
        """Return path to Google service account JSON.

        If GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT is set (Railway),
        write it to a temp file and return that path.
        Otherwise return GOOGLE_SERVICE_ACCOUNT_JSON path.
        """
        if self.google_service_account_json_content:
            # Validate it's real JSON
            json.loads(self.google_service_account_json_content)
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            )
            tmp.write(self.google_service_account_json_content)
            tmp.close()
            return tmp.name
        return str(self.google_service_account_json)


settings = Settings()
