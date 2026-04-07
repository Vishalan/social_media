"""
Publish job (Unit 7).

APScheduler-triggered actions for the approve / auto-approve flow:

  - ``schedule_publish(run_id)``      → one-shot job that fires the publish
                                        action at the approved slot
                                        (default: now if slot is in past)
  - ``schedule_auto_approve(run_id)`` → one-shot job at slot - 30 min that
                                        flips a still-pending approval to
                                        ``auto_approved`` and triggers
                                        ``schedule_publish``
  - ``publish_action(run_id)``        → the actual Postiz publish + IG
                                        Collab verify + repair work

Failure isolation: ``publish_action`` NEVER raises out. Any catastrophic
failure marks the row ``publish_failed`` with the stack trace and sends a
Telegram alert.
"""
from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, time as _time, timedelta
from typing import Any, Optional

from .. import db as db_module
from ..config import settings_manager

logger = logging.getLogger(__name__)


EXPECTED_COLLAB_USERNAME = "vishalan.ai"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_conn():
    s = settings_manager.settings
    if s is None:
        raise RuntimeError("settings not loaded")
    return db_module.connect(s.SIDECAR_DB_PATH)


def _get_scheduler():
    """Best-effort lookup of the running APScheduler instance.

    Prefers the process-wide registry (sidecar.runtime) because job handlers
    running under the scheduler's own context cannot reliably import
    sidecar.app without pulling in the whole FastAPI graph.
    """
    try:
        from sidecar import runtime as _rt  # type: ignore

        if _rt.scheduler is not None:
            return _rt.scheduler
    except Exception:
        pass
    try:
        from sidecar.app import app as fastapi_app  # type: ignore

        return getattr(fastapi_app.state, "scheduler", None)
    except Exception:
        return None


def _now() -> datetime:
    return datetime.now()


def compute_next_slot(now: Optional[datetime] = None) -> datetime:
    """Return the next 09:00 or 19:00 posting slot.

    Timezone handling: we use ``datetime.now()`` (host local time) to match
    the rest of the sidecar (Unit 6's slot picker also uses naive local
    time). The Synology host runs in the owner's local TZ.
    """
    base = now or _now()
    today = base.date()
    candidates = [
        datetime.combine(today, _time(9, 0)),
        datetime.combine(today, _time(19, 0)),
        datetime.combine(today + timedelta(days=1), _time(9, 0)),
    ]
    for c in candidates:
        if c > base:
            return c
    return candidates[-1]


async def _send_telegram(text: str) -> None:
    """Best-effort Telegram alert; never raises."""
    try:
        from sidecar.app import app as fastapi_app  # type: ignore

        bot_app = getattr(fastapi_app.state, "telegram_bot", None)
        if bot_app is None:
            logger.info("telegram alert (bot not running): %s", text)
            return
        s = settings_manager.settings
        chat_id = getattr(s, "TELEGRAM_CHAT_ID", "") if s else ""
        if not chat_id:
            return
        await bot_app.bot.send_message(chat_id=chat_id, text=text)
    except Exception as exc:
        logger.warning("telegram alert failed: %s", exc)


# ---------------------------------------------------------------------------
# schedule_publish
# ---------------------------------------------------------------------------

async def schedule_publish(pipeline_run_id: int) -> dict:
    """Create a one-shot APScheduler job to publish ``pipeline_run_id``.

    Reads the approval row to find a proposed_time; if absent or in the
    past, the publish runs immediately.
    """
    try:
        conn = _open_conn()
        try:
            approval = db_module.get_approval_by_run_id(conn, pipeline_run_id)
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("schedule_publish: cannot read approval: %s", exc)
        approval = None

    run_at = _now()
    if approval and approval.get("proposed_time"):
        try:
            run_at = datetime.fromisoformat(approval["proposed_time"])
        except Exception:
            run_at = _now()
    if run_at < _now():
        run_at = _now()

    sched = _get_scheduler()
    job_id = f"publish_run_{pipeline_run_id}"
    if sched is None:
        logger.info(
            "schedule_publish: no scheduler available; skipping (job_id=%s)",
            job_id,
        )
        return {
            "job_id": job_id,
            "scheduled_for": run_at.isoformat(),
            "skipped": True,
        }

    try:
        sched.add_job(
            publish_action,
            trigger="date",
            run_date=run_at,
            args=[pipeline_run_id],
            id=job_id,
            replace_existing=True,
            # APScheduler's default misfire_grace_time is 1s — too tight when
            # the publish target is "now" and the scheduler tick + jobstore
            # round-trip takes longer than that. Allow up to 5 minutes so a
            # busy event loop can't silently drop the job.
            misfire_grace_time=300,
        )
    except Exception as exc:
        logger.warning("schedule_publish add_job failed: %s", exc)
    return {"job_id": job_id, "scheduled_for": run_at.isoformat()}


# ---------------------------------------------------------------------------
# schedule_auto_approve
# ---------------------------------------------------------------------------

async def schedule_auto_approve(
    pipeline_run_id: int, scheduled_slot: datetime
) -> str:
    """Schedule a one-shot auto-approve job at slot - 30min."""
    s = settings_manager.settings
    offset_min = int(getattr(s, "PIPELINE_AUTO_APPROVE_OFFSET_MIN", 30) or 30) if s else 30
    fire_at = scheduled_slot - timedelta(minutes=offset_min)
    if fire_at < _now():
        fire_at = _now()

    sched = _get_scheduler()
    job_id = f"auto_approve_run_{pipeline_run_id}"
    if sched is None:
        logger.info(
            "schedule_auto_approve: no scheduler available; skipping (job_id=%s)",
            job_id,
        )
        return job_id

    try:
        sched.add_job(
            auto_approve_action,
            trigger="date",
            run_date=fire_at,
            args=[pipeline_run_id],
            id=job_id,
            replace_existing=True,
        )
    except Exception as exc:
        logger.warning("schedule_auto_approve add_job failed: %s", exc)
    return job_id


# ---------------------------------------------------------------------------
# auto_approve_action
# ---------------------------------------------------------------------------

async def auto_approve_action(pipeline_run_id: int) -> dict:
    """Fired by APScheduler at slot - 30min.

    If the approval is still pending, flip to ``auto_approved`` and trigger
    publish. Otherwise no-op.
    """
    try:
        conn = _open_conn()
        try:
            approval = db_module.get_approval_by_run_id(conn, pipeline_run_id)
            if approval is None:
                logger.info("auto_approve: no approval row for run %d", pipeline_run_id)
                return {"ok": False, "reason": "no approval"}
            status = approval.get("status") or ""
            if status != "pending":
                logger.info(
                    "auto_approve: run %d already %s, no-op",
                    pipeline_run_id,
                    status,
                )
                return {"ok": True, "noop": True, "status": status}
            db_module.update_approval_status(
                conn,
                approval["id"],
                "auto_approved",
                datetime.utcnow().isoformat(timespec="seconds"),
            )
        finally:
            conn.close()
    except Exception as exc:
        logger.exception("auto_approve_action failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    try:
        await schedule_publish(pipeline_run_id)
    except Exception as exc:
        logger.exception("auto_approve schedule_publish failed: %s", exc)
        return {"ok": False, "error": f"schedule_publish: {exc}"}

    return {"ok": True, "auto_approved": True}


# ---------------------------------------------------------------------------
# publish_action
# ---------------------------------------------------------------------------

async def publish_action(pipeline_run_id: int) -> dict:
    """The actual publish work — Postiz + IG Collab verify/repair.

    NEVER raises out. On any catastrophic failure, marks the run
    ``publish_failed`` and sends a Telegram alert.
    """
    logger.info("publish_action: starting for run %s", pipeline_run_id)
    try:
        # 1) read the run + captions
        try:
            conn = _open_conn()
            try:
                run = db_module.get_pipeline_run_with_captions(conn, pipeline_run_id)
                approval = db_module.get_approval_by_run_id(conn, pipeline_run_id)
            finally:
                conn.close()
        except Exception as exc:
            logger.exception("publish_action: db read failed: %s", exc)
            await _mark_failed(
                pipeline_run_id, "publish_failed", f"db read: {exc}"
            )
            return {"ok": False, "error": str(exc)}

        if run is None:
            await _mark_failed(
                pipeline_run_id, "publish_failed", "pipeline_run not found"
            )
            return {"ok": False, "error": "run not found"}

        if approval is None or approval.get("status") not in (
            "approved",
            "auto_approved",
        ):
            await _mark_failed(
                pipeline_run_id,
                "publish_failed",
                f"approval not approved (status={approval.get('status') if approval else None})",
            )
            return {"ok": False, "error": "not approved"}

        # 2) duplicate guard (Unit 9 — hard import, enforced)
        from sidecar.duplicate_guard import check as duplicate_check

        try:
            topic_url = run.get("topic_url") or ""
            topic_title = run.get("topic_title") or ""
            dup_conn = _open_conn()
            try:
                dup_result = duplicate_check(
                    dup_conn,
                    topic_url,
                    topic_title,
                    exclude_run_id=pipeline_run_id,
                )
            finally:
                dup_conn.close()
        except Exception as exc:
            logger.warning("duplicate_guard.check raised: %s", exc)
            dup_result = {"is_duplicate": False, "match_run_id": None, "match_reason": f"check error: {exc}"}

        if dup_result.get("is_duplicate"):
            await _mark_failed(
                pipeline_run_id,
                "publish_failed_duplicate",
                f"duplicate detected: {dup_result.get('match_reason', '')}",
            )
            await _send_telegram(
                f"⚠ Duplicate detected — run {pipeline_run_id} not published "
                f"({dup_result.get('match_reason', '')})"
            )
            return {"ok": False, "duplicate": True, "match": dup_result}

        # 3) build the Postiz call
        captions = run.get("captions") or {}
        ig = captions.get("instagram") or {}
        yt = captions.get("youtube") or {}

        ig_caption = ig.get("caption") or run.get("topic_title") or ""
        hashtags = ig.get("hashtags") or []
        if hashtags:
            ig_caption = f"{ig_caption}\n\n{' '.join(hashtags)}"
        yt_title = yt.get("title") or run.get("topic_title") or ""
        yt_description = yt.get("description") or ""

        # Resolve the scheduled slot. Priority:
        #   1. The user's explicit reschedule (approval.proposed_time)
        #   2. The next peak posting slot (09:00 / 19:00 local) from
        #      compute_next_slot — so even an "Approve immediately" tap
        #      lands on a peak hour rather than firing right away.
        #   3. Fallback to "now" only if slot computation breaks.
        scheduled_slot = compute_next_slot()
        if approval.get("proposed_time"):
            try:
                scheduled_slot = datetime.fromisoformat(approval["proposed_time"])
            except Exception:
                pass

        # 4) Postiz publish
        try:
            from sidecar.postiz_client import make_client_from_settings

            postiz = make_client_from_settings(settings_manager.settings)
            postiz_resp = postiz.publish_post(
                video_path=run.get("video_path") or "",
                thumbnail_path=run.get("thumbnail_path") or "",
                ig_caption=ig_caption,
                yt_title=yt_title,
                yt_description=yt_description,
                ig_collab_usernames=[EXPECTED_COLLAB_USERNAME],
                scheduled_slot=scheduled_slot,
            )
        except Exception as exc:
            logger.exception("publish_action: postiz failed: %s", exc)
            await _mark_failed(
                pipeline_run_id, "publish_failed", f"postiz: {exc}"
            )
            await _send_telegram(
                f"⚠ Publish failed for run {pipeline_run_id}: {exc}"
            )
            return {"ok": False, "error": str(exc)}

        post_ids = _extract_post_ids(postiz_resp)

        # 5) IG Collab verify-then-fallback
        ig_media_id = post_ids.get("instagram") or ""
        collab_ok = False
        if ig_media_id:
            try:
                from sidecar.ig_direct import IGDirectClient

                tokens = postiz.get_account_tokens()
                ig_tokens = (tokens or {}).get("instagram", {})
                first = next(iter(ig_tokens.values()), {}) if ig_tokens else {}
                access_token = first.get("access_token", "")
                ig_user_id = first.get("user_id", "")
                ig_client = IGDirectClient(access_token=access_token)
                collab_ok = ig_client.verify_collab(
                    ig_media_id, EXPECTED_COLLAB_USERNAME
                )
                if not collab_ok:
                    logger.info(
                        "IG Collab missing on %s, attempting edit", ig_media_id
                    )
                    edit_result = ig_client.add_collab_by_edit(
                        ig_media_id, EXPECTED_COLLAB_USERNAME
                    )
                    if edit_result is not None:
                        collab_ok = ig_client.verify_collab(
                            ig_media_id, EXPECTED_COLLAB_USERNAME
                        )
                if not collab_ok and ig_user_id:
                    logger.info(
                        "IG Collab still missing, attempting recreate"
                    )
                    recreate_result = ig_client.add_collab_by_recreate(
                        ig_user_id=ig_user_id,
                        video_url=run.get("video_path") or "",
                        caption=ig_caption,
                        collaborator_ig_user_ids=[EXPECTED_COLLAB_USERNAME],
                    )
                    if recreate_result.get("ok"):
                        collab_ok = True
                        new_id = (
                            recreate_result.get("media", {}).get("id")
                            or recreate_result.get("container_id")
                        )
                        if new_id:
                            post_ids["instagram"] = new_id
            except Exception as exc:
                logger.warning("IG Collab verify/repair failed: %s", exc)

        # 6) persist results
        try:
            conn = _open_conn()
            try:
                db_module.update_pipeline_run_publish_result(
                    conn,
                    pipeline_run_id,
                    status="published",
                    post_ids=post_ids,
                    error=None if collab_ok else "ig_collab_unverified",
                )
            finally:
                conn.close()
        except Exception as exc:
            logger.exception("publish_action: db write failed: %s", exc)

        await _send_telegram(
            f"✓ Published run {pipeline_run_id} (collab_ok={collab_ok})"
        )
        return {"ok": True, "post_ids": post_ids, "collab_ok": collab_ok}

    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("publish_action catastrophic failure: %s\n%s", exc, tb)
        try:
            await _mark_failed(pipeline_run_id, "publish_failed", tb)
        except Exception:
            pass
        try:
            await _send_telegram(
                f"⚠ Publish CRASH for run {pipeline_run_id}: {exc}"
            )
        except Exception:
            pass
        return {"ok": False, "error": str(exc)}


def _extract_post_ids(postiz_resp: Any) -> dict:
    """Pull per-platform media ids out of a Postiz response (best effort)."""
    out: dict = {}
    if not isinstance(postiz_resp, dict):
        return out
    posts = postiz_resp.get("posts") or postiz_resp.get("results") or []
    if isinstance(posts, list):
        for p in posts:
            if not isinstance(p, dict):
                continue
            platform = (p.get("platform") or p.get("provider") or "").lower()
            mid = p.get("id") or p.get("postId") or p.get("mediaId")
            if platform and mid:
                out[platform] = mid
    # Top-level shorthand for tests
    for key in ("instagram", "youtube"):
        if key in postiz_resp and key not in out:
            v = postiz_resp[key]
            if isinstance(v, dict) and "id" in v:
                out[key] = v["id"]
            elif isinstance(v, str):
                out[key] = v
    return out


async def _mark_failed(run_id: int, status: str, error: str) -> None:
    try:
        conn = _open_conn()
        try:
            db_module.update_pipeline_run_publish_result(
                conn, run_id, status=status, post_ids=None, error=error
            )
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("_mark_failed db write error: %s", exc)
