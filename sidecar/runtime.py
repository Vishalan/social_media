"""Process-wide runtime registry for long-lived components.

Lets job handlers (pipeline_runner, publish, etc.) reach the long-lived
Telegram Application and APScheduler without importing app.py — which would
pull the FastAPI app graph into every scheduler context and create circular
import pain.

app.py writes into this module at startup; readers tolerate None so that
local unit tests and one-shot exec scripts still work without a full app.
"""
from __future__ import annotations

from typing import Any, Optional

# python-telegram-bot Application, set by sidecar.app lifespan after build.
telegram_app: Optional[Any] = None

# APScheduler AsyncIOScheduler, set by sidecar.app lifespan after start.
scheduler: Optional[Any] = None
