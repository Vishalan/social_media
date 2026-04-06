"""
Sidecar FastAPI entrypoint.

Uses the modern lifespan context manager (not deprecated on_event) so we
can bootstrap DB, load settings, and reserve slots for APScheduler and the
Telegram bot — both of which land in later units. Failure isolation: if
settings fail to load, we log the error but still start the app so the
/health endpoint can return 503 with a clear body.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
from . import db as db_module
from .config import settings_manager
from .routes import health as health_routes


logger = logging.getLogger("sidecar")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Load settings (non-fatal) ----------------------------------------
    try:
        settings_manager.load()
        logger.info("sidecar settings loaded from %s", settings_manager.env_path)
    except Exception as exc:
        logger.error("sidecar settings failed to load: %s", exc)

    # --- Bootstrap SQLite (non-fatal) -------------------------------------
    try:
        s = settings_manager.settings
        if s is not None:
            db_module.init_db(s.SIDECAR_DB_PATH)
            logger.info("sidecar sqlite initialized at %s", s.SIDECAR_DB_PATH)
    except Exception as exc:
        logger.error("sidecar db init failed: %s", exc)

    # --- Reserved slots ---------------------------------------------------
    # TODO: Unit 3 — start APScheduler with the newsletter fetch job.
    # TODO: Unit 6 — launch the Telegram bot polling task.

    yield

    # --- Shutdown ---------------------------------------------------------
    logger.info("sidecar shutting down")


app = FastAPI(
    title="CommonCreed Sidecar",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(health_routes.router)
