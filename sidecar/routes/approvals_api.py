"""
Approval action stubs.

These endpoints exist so the dashboard buttons have somewhere to POST. They
log the request and return 200 with a small JSON body. The REAL DB updates
for approval actions are owned by Unit 6 (Telegram bot integration); the
publish trigger lives in Unit 7. We deliberately do not write to the
approvals table here to avoid colliding with Unit 6.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse

from ..auth import require_auth


logger = logging.getLogger("sidecar.approvals_api")
router = APIRouter()


# TODO: Unit 6 wires the real DB updates for approval actions; Unit 7 wires
# the publish trigger. Until then these endpoints just log + return 200.


@router.post("/approvals/{approval_id}/approve")
async def approve(
    approval_id: int, request: Request, _: bool = Depends(require_auth)
):
    logger.info("approval stub: approve id=%s", approval_id)
    return JSONResponse({"ok": True, "id": approval_id, "action": "approve", "stub": True})


@router.post("/approvals/{approval_id}/reject")
async def reject(
    approval_id: int, request: Request, _: bool = Depends(require_auth)
):
    logger.info("approval stub: reject id=%s", approval_id)
    return JSONResponse({"ok": True, "id": approval_id, "action": "reject", "stub": True})


@router.post("/approvals/{approval_id}/reschedule")
async def reschedule(
    approval_id: int,
    proposed_time: str = Form(default=""),
    _: bool = Depends(require_auth),
):
    logger.info(
        "approval stub: reschedule id=%s proposed_time=%s",
        approval_id, proposed_time,
    )
    return JSONResponse({
        "ok": True, "id": approval_id, "action": "reschedule",
        "proposed_time": proposed_time, "stub": True,
    })


@router.post("/approvals/{approval_id}/edit_caption")
async def edit_caption(
    approval_id: int,
    caption: str = Form(default=""),
    _: bool = Depends(require_auth),
):
    logger.info(
        "approval stub: edit_caption id=%s len=%d",
        approval_id, len(caption or ""),
    )
    return JSONResponse({
        "ok": True, "id": approval_id, "action": "edit_caption", "stub": True,
    })
