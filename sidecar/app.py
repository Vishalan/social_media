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
from .routes import dashboard as dashboard_routes
from .routes import settings_api as settings_api_routes
from .routes import approvals_api as approvals_api_routes
from . import auth as auth_module


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

    # --- APScheduler (Unit 4) --------------------------------------------
    scheduler = None
    try:
        scheduler = _start_scheduler()
        app.state.scheduler = scheduler
    except Exception as exc:
        logger.error("sidecar scheduler failed to start: %s", exc)
        app.state.scheduler = None

    # --- Telegram bot (Unit 6) -------------------------------------------
    app.state.telegram_bot = None
    app.state.telegram_task = None
    try:
        s = settings_manager.settings
        if s is None or not getattr(s, "TELEGRAM_BOT_TOKEN", ""):
            logger.info("sidecar telegram bot: no token configured, skipping")
        else:
            from .telegram_bot import build_application as _build_tg

            tg_app = _build_tg(s)
            await tg_app.initialize()
            await tg_app.start()
            await tg_app.updater.start_polling()
            app.state.telegram_bot = tg_app
            logger.info("sidecar telegram bot: polling started")
    except ImportError as exc:
        logger.warning("sidecar telegram bot: SDK not installed (%s)", exc)
        app.state.telegram_bot = None
    except Exception as exc:
        logger.error("sidecar telegram bot: failed to start: %s", exc)
        app.state.telegram_bot = None

    yield

    # --- Shutdown ---------------------------------------------------------
    try:
        if getattr(app.state, "scheduler", None) is not None:
            app.state.scheduler.shutdown(wait=False)
    except Exception as exc:
        logger.warning("sidecar scheduler shutdown error: %s", exc)
    try:
        tg_app = getattr(app.state, "telegram_bot", None)
        if tg_app is not None:
            try:
                await tg_app.updater.stop()
            except Exception:
                pass
            try:
                await tg_app.stop()
            except Exception:
                pass
            try:
                await tg_app.shutdown()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("sidecar telegram bot shutdown error: %s", exc)
    logger.info("sidecar shutting down")


def _start_scheduler():
    """Start an APScheduler AsyncIOScheduler with SQLite jobstore fallback.

    Wire-up decisions:
    - ``AsyncIOScheduler`` so jobs share the FastAPI event loop — required by
      the async ``process_pending_runs`` coroutine.
    - SQLite jobstore at ``<SIDECAR_DB_PATH parent>/scheduler.sqlite3`` so
      one-shot jobs (auto-approve timers added in later units) survive
      restarts. If the jobstore DB is corrupt / unwritable, fall back to the
      default in-memory jobstore — the sidecar must start either way.
    - One job: ``process_pending_runs`` every 30 seconds, picking up newly
      inserted pending rows shortly after the daily trigger writes them.

    Returns the running scheduler instance, or raises if APScheduler is not
    installed (caller logs + continues).
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    from .jobs.run_pipeline import process_pending_runs
    from .jobs.retention import run_retention_job
    from .jobs.health_ping import run_health_pings
    from .jobs.cost_report import send_weekly_cost_report

    jobstore_path: str = ""
    try:
        s = settings_manager.settings
        if s is not None:
            from pathlib import Path as _P
            jobstore_path = str(_P(s.SIDECAR_DB_PATH).parent / "scheduler.sqlite3")
    except Exception:
        jobstore_path = ""

    sched = None
    if jobstore_path:
        try:
            sched = AsyncIOScheduler(
                jobstores={
                    "default": SQLAlchemyJobStore(url=f"sqlite:///{jobstore_path}")
                }
            )
        except Exception as exc:
            logger.warning(
                "sidecar scheduler: SQLite jobstore unavailable (%s), "
                "falling back to in-memory jobstore",
                exc,
            )
            sched = None
    if sched is None:
        sched = AsyncIOScheduler()

    sched.add_job(
        process_pending_runs,
        trigger=IntervalTrigger(seconds=30),
        id="process_pending_runs",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # Unit 9 — operational jobs
    try:
        sched.add_job(
            run_retention_job,
            trigger=CronTrigger(hour=3, minute=0),
            id="retention_job",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    except Exception as exc:
        logger.warning("sidecar scheduler: retention job wire-up failed: %s", exc)

    try:
        sched.add_job(
            run_health_pings,
            trigger=IntervalTrigger(hours=1),
            id="health_ping",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    except Exception as exc:
        logger.warning("sidecar scheduler: health ping wire-up failed: %s", exc)

    try:
        sched.add_job(
            send_weekly_cost_report,
            trigger=CronTrigger(day_of_week="mon", hour=9, minute=0),
            id="weekly_cost_report",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    except Exception as exc:
        logger.warning("sidecar scheduler: cost report wire-up failed: %s", exc)

    sched.start()
    logger.info("sidecar scheduler started (jobstore=%s)", jobstore_path or "memory")
    return sched


app = FastAPI(
    title="CommonCreed Sidecar",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(health_routes.router)
app.include_router(auth_module.router)
app.include_router(dashboard_routes.router)
app.include_router(settings_api_routes.router)
app.include_router(approvals_api_routes.router)
auth_module.install_redirect_handler(app)
