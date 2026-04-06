"""
Approval action endpoints (Unit 7 wired).

These endpoints provide the dashboard's path to the same actions Telegram
exposes, and they MUST produce identical DB state. On approve we also fire
the Unit 7 publish job.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse

from .. import db as db_module
from ..auth import require_auth
from ..config import settings_manager


logger = logging.getLogger("sidecar.approvals_api")
router = APIRouter()


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _open_conn():
    s = settings_manager.settings
    if s is None:
        raise RuntimeError("settings not loaded")
    return db_module.connect(s.SIDECAR_DB_PATH)


@router.post("/approvals/{approval_id}/approve")
async def approve(
    approval_id: int, request: Request, _: bool = Depends(require_auth)
):
    try:
        conn = _open_conn()
        try:
            row = conn.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
            if row is None:
                return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
            db_module.update_approval_status(
                conn, approval_id, "approved", _now_iso()
            )
            run_id = int(row["pipeline_run_id"])
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("approve failed: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    try:
        from sidecar.jobs.publish import schedule_publish

        res = schedule_publish(run_id)
        if asyncio.iscoroutine(res):
            await res
    except Exception as exc:
        logger.warning("schedule_publish failed: %s", exc)

    return JSONResponse(
        {"ok": True, "id": approval_id, "action": "approve", "run_id": run_id}
    )


@router.post("/approvals/{approval_id}/reject")
async def reject(
    approval_id: int, request: Request, _: bool = Depends(require_auth)
):
    try:
        conn = _open_conn()
        try:
            row = conn.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
            if row is None:
                return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
            db_module.update_approval_status(
                conn, approval_id, "rejected", _now_iso()
            )
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("reject failed: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return JSONResponse({"ok": True, "id": approval_id, "action": "reject"})


@router.post("/approvals/{approval_id}/reschedule")
async def reschedule(
    approval_id: int,
    proposed_time: str = Form(default=""),
    _: bool = Depends(require_auth),
):
    try:
        conn = _open_conn()
        try:
            row = conn.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
            if row is None:
                return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
            db_module.update_approval_status(
                conn,
                approval_id,
                "rescheduled",
                _now_iso(),
                proposed_time=proposed_time or None,
            )
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("reschedule failed: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return JSONResponse(
        {
            "ok": True,
            "id": approval_id,
            "action": "reschedule",
            "proposed_time": proposed_time,
        }
    )


@router.post("/approvals/{approval_id}/edit_caption")
async def edit_caption(
    approval_id: int,
    caption: str = Form(default=""),
    _: bool = Depends(require_auth),
):
    try:
        conn = _open_conn()
        try:
            row = conn.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
            if row is None:
                return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
            run_id = int(row["pipeline_run_id"])
            run = db_module.get_pipeline_run(conn, run_id)
            captions = {}
            if run and run.get("captions_json"):
                try:
                    captions = json.loads(run["captions_json"])
                except (TypeError, ValueError):
                    captions = {}
            ig = captions.get("instagram") or {}
            ig["caption"] = caption
            captions["instagram"] = ig
            db_module.set_captions(conn, run_id, captions)
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("edit_caption failed: %s", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return JSONResponse(
        {"ok": True, "id": approval_id, "action": "edit_caption"}
    )
