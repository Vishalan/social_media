"""
Dashboard routes (Unit 8 SHELL).

All pages render via Jinja2. Auth is enforced by the ``require_auth``
dependency declared on each route. Real DB wire-up exists for runs/approvals
(Unit 5/6 already define the tables); summary cards still use mock values
for Gmail-trigger and cost — these become real after Unit 7 ships.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .. import db as db_module
from ..auth import require_auth
from ..config import settings_manager


logger = logging.getLogger("sidecar.dashboard")
router = APIRouter()

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# --- Settings groups for the settings page --------------------------------
# Static map: key → (group_name, hint about which container is affected).
SETTINGS_GROUPS: dict[str, tuple[str, str]] = {
    "ANTHROPIC_API_KEY":      ("Sidecar (re-read at use)", "Read by sidecar at use; no restart."),
    "SIDECAR_ADMIN_PASSWORD": ("Sidecar (re-read at use)", "Login password; takes effect on next sign-in."),
    "TELEGRAM_BOT_TOKEN":     ("Sidecar (re-read at use)", "Telegram bot token; no restart."),
    "TELEGRAM_CHAT_ID":       ("Sidecar (re-read at use)", "Telegram owner chat id."),
    "GMAIL_OAUTH_PATH":       ("Sidecar (re-read at use)", "Path to gmail OAuth json."),
    "POSTIZ_BASE_URL":        ("Postiz (restart on change)", "Restarts the postiz container."),
    "POSTIZ_API_KEY":         ("Postiz (restart on change)", "Restarts the postiz container."),
    "ELEVENLABS_API_KEY":     ("Subprocess only (next run)", "Picked up by next pipeline subprocess."),
    "VEED_API_KEY":           ("Subprocess only (next run)", "Picked up by next pipeline subprocess."),
    "FAL_API_KEY":            ("Subprocess only (next run)", "Picked up by next pipeline subprocess."),
    "PEXELS_API_KEY":         ("Subprocess only (next run)", "Picked up by next pipeline subprocess."),
}


def _get_db_conn():
    s = settings_manager.settings
    if s is None:
        raise HTTPException(status_code=503, detail="settings not loaded")
    return db_module.connect(s.SIDECAR_DB_PATH)


def _mask(value: Optional[str]) -> str:
    if not value:
        return ""
    return "***"


# --- GET / ----------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
def summary(request: Request, _: bool = Depends(require_auth)):
    runs_this_week = 0
    approval_queue_count = 0
    try:
        conn = _get_db_conn()
        try:
            runs_this_week = len(db_module.get_recent_pipeline_runs(conn, limit=50))
            approval_queue_count = db_module.count_approvals_by_status(conn, "pending")
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("summary db read failed: %s", exc)

    ctx = {
        "request": request,
        "runs_this_week": runs_this_week,
        "approval_queue_count": approval_queue_count,
        # Mock fields — real wire-up after Unit 7.
        "last_gmail_success": "(mock) 2026-04-06 05:00 UTC",
        "cost_this_month": "0.00",
    }
    return templates.TemplateResponse("summary.html", ctx)


# --- GET /runs ------------------------------------------------------------
@router.get("/runs", response_class=HTMLResponse)
def runs_page(
    request: Request,
    status: str = "all",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    _: bool = Depends(require_auth),
):
    rows: list[dict] = []
    try:
        conn = _get_db_conn()
        try:
            rows = db_module.get_recent_pipeline_runs(conn, limit=100)
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("runs page db read failed: %s", exc)

    if status and status != "all":
        rows = [r for r in rows if r.get("status") == status]

    ctx = {
        "request": request,
        "runs": rows,
        "status": status,
        "date_from": date_from,
        "date_to": date_to,
        "status_options": [
            "all", "pending_generation", "generated", "failed",
            "approved", "rejected", "published",
        ],
    }
    template = (
        "_partials/runs_table.html"
        if request.headers.get("HX-Request", "").lower() == "true"
        else "runs.html"
    )
    return templates.TemplateResponse(template, ctx)


# --- GET /runs/{id} -------------------------------------------------------
@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(
    request: Request, run_id: int, _: bool = Depends(require_auth)
):
    try:
        conn = _get_db_conn()
        try:
            run = db_module.get_pipeline_run(conn, run_id)
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("run detail db read failed: %s", exc)
        run = None

    if run is None:
        raise HTTPException(status_code=404, detail=f"run {run_id} not found")

    captions_pretty = "(none)"
    raw = run.get("captions_json")
    if raw:
        try:
            captions_pretty = json.dumps(json.loads(raw), indent=2)
        except Exception:
            captions_pretty = str(raw)

    return templates.TemplateResponse(
        "run_detail.html",
        {"request": request, "run": run, "captions_pretty": captions_pretty},
    )


# --- GET /approvals -------------------------------------------------------
@router.get("/approvals", response_class=HTMLResponse)
def approvals_page(request: Request, _: bool = Depends(require_auth)):
    rows: list[dict] = []
    try:
        conn = _get_db_conn()
        try:
            rows = db_module.get_pending_approvals(conn)
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("approvals page db read failed: %s", exc)

    return templates.TemplateResponse(
        "approvals.html", {"request": request, "approvals": rows}
    )


# --- GET /settings --------------------------------------------------------
@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, _: bool = Depends(require_auth)):
    s = settings_manager.settings
    grouped: dict[str, list[dict]] = {}
    for key, (group, hint) in SETTINGS_GROUPS.items():
        current = getattr(s, key, "") if s is not None else ""
        grouped.setdefault(group, []).append(
            {"key": key, "masked": _mask(current), "hint": hint}
        )
    return templates.TemplateResponse(
        "settings.html", {"request": request, "groups": grouped}
    )
