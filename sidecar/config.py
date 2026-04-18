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
    # Comma-separated list of enabled topic sources — see
    # sidecar/topic_sources/__init__.py for the registry. Unknown names
    # are logged and skipped; order determines fetch order only. Sources
    # that aren't yet configured (e.g. Gmail without its OAuth token) are
    # also skipped silently so adding one to this list never breaks the
    # daily run.
    PIPELINE_TOPIC_SOURCES: str = "gmail,hackernews,github_trending,huggingface_trending,arxiv,lobsters"
    # Hacker News source knobs (ignored when "hackernews" isn't in the list)
    HACKERNEWS_MAX_ITEMS: int = 20
    HACKERNEWS_MIN_SCORE: int = 50
    # GitHub Trending source knobs (ignored when "github_trending" isn't in the list)
    GITHUB_TRENDING_MAX_ITEMS: int = 15
    GITHUB_TRENDING_MIN_STARS_TODAY: int = 10
    # Hugging Face trending source knobs
    HUGGINGFACE_MAX_ITEMS: int = 20
    HUGGINGFACE_MIN_DOWNLOADS: int = 1000
    HUGGINGFACE_MIN_LIKES: int = 5
    # arXiv source knobs (categories is comma-separated)
    ARXIV_MAX_ITEMS: int = 15
    ARXIV_CATEGORIES: str = "cs.AI,cs.CL"
    # Lobste.rs source knobs
    LOBSTERS_MAX_ITEMS: int = 15
    LOBSTERS_MIN_SCORE: int = 10
    # Meme reposter v0 (Reddit)
    MEME_SOURCES: str = (
        "reddit_programmerhumor,reddit_techhumor,"
        "reddit_cscareerquestions,reddit_webdev,"
        "reddit_dataisbeautiful,reddit_homelab,"
        "reddit_mechanicalkeyboards"
    )
    MEME_SUBREDDIT_MAP: str = (
        "reddit_programmerhumor:ProgrammerHumor,"
        "reddit_techhumor:techhumor,"
        "reddit_cscareerquestions:cscareerquestions,"
        "reddit_webdev:webdev,"
        "reddit_dataisbeautiful:DataIsBeautiful,"
        "reddit_homelab:homelab,"
        "reddit_mechanicalkeyboards:MechanicalKeyboards"
    )
    # Per-media-type surface limits for Telegram previews (Unit 2)
    MEME_DAILY_SURFACE_LIMIT: int = 2          # images per trigger run
    MEME_VIDEO_DAILY_SURFACE_LIMIT: int = 2    # videos per trigger run
    REDDIT_MEME_TIME_FILTER: str = "day"
    REDDIT_MEME_MAX_ITEMS: int = 25
    REDDIT_MEME_MIN_SCORE: int = 500
    # Quality thresholds for Haiku scoring (Unit 1) — both humor and
    # relevance must be >= 7/10 for a candidate to surface.
    MEME_MIN_HUMOR_SCORE: int = 7
    MEME_MIN_RELEVANCE_SCORE: int = 7
    # Meme autopilot — fires at slot-offset if no human tap landed
    MEME_AUTO_APPROVE_ENABLED: bool = True
    MEME_AUTO_APPROVE_OFFSET_MIN: int = 30
    MEME_DAILY_AUTO_APPROVE_COUNT: int = 1
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
