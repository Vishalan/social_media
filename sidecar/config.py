"""
Sidecar configuration.

Loads settings from a .env file (mounted at /env/.env in the container) into
a typed Pydantic Settings model. Failure isolation: if the file is missing
or required fields are absent, `load_settings` raises a clear ValueError and
the caller (app.py lifespan) logs it and keeps the FastAPI app running so
/health can still report 503. The app never crashes on startup.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_ENV_PATH = "/env/.env"


class Settings(BaseSettings):
    """Typed view of the sidecar's environment.

    Required fields are declared without defaults; pydantic will raise on
    `load_settings` if they are missing. Optional fields carry safe defaults
    so the app can start in degraded mode for development.
    """

    model_config = SettingsConfigDict(
        env_file=None,  # we pass the file explicitly in load_settings
        extra="ignore",
        case_sensitive=False,
    )

    # --- Required ----------------------------------------------------------
    ANTHROPIC_API_KEY: str = Field(..., min_length=1)
    SIDECAR_ADMIN_PASSWORD: str = Field(..., min_length=1)

    # --- Postiz ------------------------------------------------------------
    POSTIZ_BASE_URL: str = "http://postiz:5000"
    POSTIZ_API_KEY: str = ""

    # --- Pipeline external APIs (passed through to subprocess) -------------
    ELEVENLABS_API_KEY: str = ""
    VEED_API_KEY: str = ""
    FAL_API_KEY: str = ""
    PEXELS_API_KEY: str = ""

    # --- Telegram ----------------------------------------------------------
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # --- Gmail -------------------------------------------------------------
    GMAIL_OAUTH_PATH: str = "/secrets/gmail_oauth.json"

    # --- Schedule ----------------------------------------------------------
    PIPELINE_TRIGGER_TIME: str = "05:00"
    PIPELINE_SLOT_MORNING: str = "09:00"
    PIPELINE_SLOT_EVENING: str = "19:00"
    PIPELINE_AUTO_APPROVE_OFFSET_MIN: int = 30
    PIPELINE_RETENTION_DAYS: int = 14

    # --- Sidecar runtime paths --------------------------------------------
    SIDECAR_DB_PATH: str = "/app/db/sidecar.sqlite3"
    PIPELINE_SCRIPTS_PATH: str = "/app/scripts"
    PIPELINE_OUTPUT_PATH: str = "/app/output"
    DOCKER_SOCKET_PATH: str = "/var/run/docker.sock"


def _parse_env_file(path: str) -> dict:
    """Minimal .env parser: KEY=VALUE per line, # comments, no shell expansion.

    Using a local parser instead of delegating to pydantic-settings' file
    loader so we can re-read on demand (reload) without relying on global
    process env state.
    """
    data: dict = {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"env file not found: {path}")
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        data[key] = value
    return data


class SettingsManager:
    """Holds the current Settings and supports reload()."""

    def __init__(self, env_path: str = DEFAULT_ENV_PATH) -> None:
        self.env_path = env_path
        self._settings: Optional[Settings] = None

    @property
    def settings(self) -> Optional[Settings]:
        return self._settings

    def load(self) -> Settings:
        data = _parse_env_file(self.env_path)
        try:
            self._settings = Settings(**data)
        except ValidationError as ve:
            # Translate pydantic's noisy error into a single clear ValueError
            missing = [
                ".".join(str(x) for x in err["loc"])
                for err in ve.errors()
                if err["type"] in ("missing", "string_too_short", "value_error")
            ]
            raise ValueError(
                f"Sidecar config invalid: missing/empty required fields: {missing}"
            ) from ve
        return self._settings

    def reload(self) -> Settings:
        """Re-read the .env file and replace the cached Settings."""
        return self.load()


def load_settings(env_path: str = DEFAULT_ENV_PATH) -> Settings:
    """Convenience one-shot loader used by app bootstrap and tests."""
    mgr = SettingsManager(env_path=env_path)
    return mgr.load()


# Module-level singleton manager, populated by app.py lifespan.
settings_manager = SettingsManager(env_path=os.environ.get("SIDECAR_ENV_PATH", DEFAULT_ENV_PATH))
