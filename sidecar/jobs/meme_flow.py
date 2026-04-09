"""
Meme flow: trigger + publish for the Reddit meme reposter (v0).

Two public entry points:

    run_meme_trigger() -> dict
        Fetches candidates from every enabled meme source, filters out
        denylisted creators + already-seen source_urls, inserts the top
        N into the meme_candidates table as ``pending_review``, and
        fires one Telegram preview per candidate. Never raises.

    publish_meme_candidate(candidate_id: int) -> dict
        Invoked from the Telegram Approve callback. Downloads media
        via safe_fetch, normalizes, overlays credit, uploads to Postiz,
        and schedules for the next peak slot. Never raises.

Intentionally NOT split into separate files yet — v0 deliverable is
"end-to-end working flow, minimum surface area". Refactor when a
second source or a second approval path forces it.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from .. import db as db_module
from ..config import settings_manager
from ..meme_pipeline import (
    MemePipelineError,
    apply_credit_overlay,
    normalize_media,
    safe_fetch,
)
from ..meme_sources import load_enabled_meme_sources

logger = logging.getLogger(__name__)


_MEDIA_WORK_DIR = Path("/app/output/memes")


# ---------------------------------------------------------------------------
# run_meme_trigger — fetch + filter + surface to Telegram
# ---------------------------------------------------------------------------


async def run_meme_trigger() -> dict:
    """Fetch memes from enabled sources + send new candidates to Telegram.

    Async so it can be fired from the APScheduler loop (which is already
    running an event loop) or from a one-shot ``asyncio.run(...)`` call.
    """
    try:
        settings = settings_manager.settings
        if settings is None:
            settings = settings_manager.load()
    except Exception as exc:
        logger.error("run_meme_trigger: settings load failed: %s", exc)
        return {"ok": False, "error": f"settings: {exc}"}

    sources = load_enabled_meme_sources(settings)
    if not sources:
        return {"ok": True, "skipped": True, "reason": "no meme sources enabled"}

    per_source: dict[str, int] = {}
    all_candidates: list[dict] = []
    for src in sources:
        try:
            items = src.fetch_candidates(settings)
        except Exception as exc:
            logger.warning(
                "meme_trigger: source %s raised: %s", src.name, exc, exc_info=True
            )
            items = []
        per_source[src.name] = len(items)
        all_candidates.extend(items)

    if not all_candidates:
        return {
            "ok": True,
            "skipped": True,
            "reason": "no items from any source",
            "per_source": per_source,
        }

    # Limit how many we surface per run so Telegram doesn't get flooded.
    surface_limit = int(
        getattr(settings, "MEME_DAILY_SURFACE_LIMIT", 5) or 5
    )

    # Sort by score descending for deterministic top-N picking
    def _score(c: dict) -> int:
        return int((c.get("engagement") or {}).get("score") or 0)

    all_candidates.sort(key=_score, reverse=True)

    inserted_ids: list[int] = []
    surfaced_ids: list[int] = []
    try:
        conn = db_module.connect(settings.SIDECAR_DB_PATH)
    except Exception as exc:
        logger.error("meme_trigger: db connect failed: %s", exc)
        return {"ok": False, "error": f"db: {exc}", "per_source": per_source}

    try:
        for cand in all_candidates:
            # Creator denylist short-circuit
            if db_module.is_meme_creator_denied(
                conn, cand["author_handle"], cand["source"]
            ):
                logger.info(
                    "meme_trigger: skipping denylisted %s on %s",
                    cand["author_handle"],
                    cand["source"],
                )
                continue

            try:
                row_id = db_module.insert_meme_candidate(conn, cand)
            except Exception as exc:
                logger.warning("meme_trigger: insert failed: %s", exc)
                continue

            # Was this NEW or a re-surface of an existing row?
            existing = db_module.get_meme_candidate(conn, row_id) or {}
            if existing.get("status") != "pending_review":
                # already processed in a previous run
                continue

            inserted_ids.append(row_id)
            if len(surfaced_ids) < surface_limit:
                surfaced_ids.append(row_id)
    finally:
        conn.close()

    # Fire Telegram previews for the surfaced IDs
    sent: list[int] = []
    for cid in surfaced_ids:
        try:
            msg_id = await _send_meme_preview(cid)
            if msg_id is not None:
                sent.append(msg_id)
        except Exception as exc:
            logger.warning(
                "meme_trigger: send_meme_preview(%s) failed: %s", cid, exc
            )

    return {
        "ok": True,
        "per_source": per_source,
        "total_fetched": len(all_candidates),
        "inserted": len(inserted_ids),
        "surfaced": len(surfaced_ids),
        "telegram_sent": len(sent),
        "inserted_ids": inserted_ids,
        "surfaced_ids": surfaced_ids,
    }


async def _send_meme_preview(candidate_id: int) -> int | None:
    """Send a single meme candidate to Telegram with Approve/Reject buttons.

    Prefers the long-lived runtime.telegram_app (set by app.py at startup).
    Falls back to a fresh one-shot Application when fired from a manual
    exec context where the lifespan hasn't populated the singleton.
    """
    from .. import runtime as _rt

    tg_app = _rt.telegram_app
    one_shot_app = None
    if tg_app is None:
        try:
            from ..telegram_bot import build_application as _build_tg
            settings_manager.load()
            one_shot_app = _build_tg(settings_manager.settings)
            await one_shot_app.initialize()
            tg_app = one_shot_app
        except Exception as exc:
            logger.warning("send_meme_preview: build one-shot app failed: %s", exc)
            return None

    settings = settings_manager.settings
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "") if settings else ""
    if not chat_id:
        logger.warning("send_meme_preview: no TELEGRAM_CHAT_ID configured")
        return None

    conn = db_module.connect(settings.SIDECAR_DB_PATH)
    try:
        cand = db_module.get_meme_candidate(conn, candidate_id)
    finally:
        conn.close()
    if cand is None:
        logger.warning("send_meme_preview: candidate %s not found", candidate_id)
        return None

    engagement = json.loads(cand.get("engagement_json") or "{}")
    score = engagement.get("score", 0)
    comments = engagement.get("comments", 0)
    subreddit = engagement.get("subreddit", "?")

    caption = (
        f"🎯 Meme candidate — {cand['media_type']}\n"
        f"@{cand['author_handle']} · r/{subreddit}\n"
        f"👍 {score:,} score · 💬 {comments:,} comments\n\n"
        f"Title: {cand['title'][:180]}\n"
        f"Source: {cand['source_url']}"
    )

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Approve", callback_data=f"meme:approve:{candidate_id}"
                ),
                InlineKeyboardButton(
                    "❌ Reject", callback_data=f"meme:reject:{candidate_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🚫 Deny creator", callback_data=f"meme:deny:{candidate_id}"
                ),
            ],
        ]
    )

    try:
        if cand["media_type"] == "image":
            msg = await tg_app.bot.send_photo(
                chat_id=chat_id,
                photo=cand["media_url"],
                caption=caption,
                reply_markup=keyboard,
            )
        else:
            msg = await tg_app.bot.send_video(
                chat_id=chat_id,
                video=cand["media_url"],
                caption=caption,
                reply_markup=keyboard,
            )
    except Exception as exc:
        logger.warning(
            "send_meme_preview(%s): send failed: %s — falling back to text",
            candidate_id,
            exc,
        )
        msg = await tg_app.bot.send_message(
            chat_id=chat_id,
            text=caption + "\n\n⚠ media preview failed to attach",
            reply_markup=keyboard,
        )

    try:
        conn = db_module.connect(settings.SIDECAR_DB_PATH)
        try:
            db_module.update_meme_candidate(
                conn, candidate_id, telegram_message_id=msg.message_id
            )
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("send_meme_preview(%s): db update failed: %s", candidate_id, exc)

    if one_shot_app is not None:
        try:
            await one_shot_app.shutdown()
        except Exception:
            pass

    return msg.message_id


# ---------------------------------------------------------------------------
# publish_meme_candidate — on approve: download, overlay, upload to Postiz
# ---------------------------------------------------------------------------


async def publish_meme_candidate(candidate_id: int) -> dict:
    """Download media, normalize, overlay credit, push to Postiz.

    Called from the Telegram Approve callback. Returns a dict summary.
    Never raises.
    """
    settings = settings_manager.settings
    if settings is None:
        try:
            settings = settings_manager.load()
        except Exception as exc:
            return {"ok": False, "error": f"settings: {exc}"}

    conn = db_module.connect(settings.SIDECAR_DB_PATH)
    try:
        cand = db_module.get_meme_candidate(conn, candidate_id)
    finally:
        conn.close()
    if cand is None:
        return {"ok": False, "error": "candidate not found"}
    if cand["status"] not in ("pending_review", "approved"):
        return {"ok": False, "error": f"candidate in status {cand['status']}"}

    # --- Acquire NAS heavy work lock so we don't compete with a generative run ---
    from .. import runtime as _rt
    lock = getattr(_rt, "nas_heavy_work_lock", None)
    if lock is None:
        # Fallback: create a local per-call lock (no mutex vs generative track).
        # Acceptable for v0 since generative uses its own _pipeline_lock still.
        lock = asyncio.Lock()

    run_dir = _MEDIA_WORK_DIR / f"cand_{candidate_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Infer file extension from media_url (Reddit images are .jpg/.png/.webp,
    # videos are .mp4 via reddit_video fallback)
    ext = ".bin"
    low = cand["media_url"].lower().split("?")[0]
    for suffix in (".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".gif", ".webp"):
        if low.endswith(suffix):
            ext = suffix
            break
    raw_path = run_dir / f"raw{ext}"

    try:
        async with lock:
            # Run blocking work in a thread so we don't stall the event loop
            await asyncio.to_thread(_publish_blocking, cand, candidate_id, run_dir, raw_path, settings)
    except MemePipelineError as exc:
        logger.exception("publish_meme_candidate(%s) failed: %s", candidate_id, exc)
        _mark_failed(settings, candidate_id, f"pipeline: {exc}")
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        logger.exception(
            "publish_meme_candidate(%s) unexpected: %s", candidate_id, exc
        )
        _mark_failed(settings, candidate_id, f"unexpected: {exc}")
        return {"ok": False, "error": str(exc)}

    return {"ok": True, "id": candidate_id}


def _publish_blocking(
    cand: dict, candidate_id: int, run_dir: Path, raw_path: Path, settings
) -> None:
    """Blocking publish chain: fetch, normalize, overlay, upload to Postiz."""
    # 1) safe-fetch
    safe_fetch(cand["media_url"], raw_path)

    # 2) normalize
    if cand["media_type"] == "image":
        normalized_path = run_dir / "normalized.jpg"
    else:
        normalized_path = run_dir / "normalized.mp4"
    normalize_media(raw_path, normalized_path, cand["media_type"])

    # 3) credit overlay
    if cand["media_type"] == "image":
        credited_path = run_dir / "credited.jpg"
    else:
        credited_path = run_dir / "credited.mp4"
    apply_credit_overlay(
        normalized_path,
        credited_path,
        cand["author_handle"],
        cand["source"],
        cand["media_type"],
    )

    # Persist paths
    conn = db_module.connect(settings.SIDECAR_DB_PATH)
    try:
        db_module.update_meme_candidate(
            conn,
            candidate_id,
            normalized_path=str(normalized_path),
            credited_path=str(credited_path),
            status="publishing",
            reviewed_at=datetime.utcnow().isoformat() + "Z",
        )
    finally:
        conn.close()

    # 4) Upload to Postiz — reuse existing publish_post with curated caption
    from ..postiz_client import make_client_from_settings
    from ..jobs.publish import compute_next_slot

    client = make_client_from_settings(settings)

    # Build caption: our intro + explicit credit + hashtags
    eng = json.loads(cand.get("engagement_json") or "{}")
    subreddit = eng.get("subreddit", "ProgrammerHumor")
    caption_ig = (
        f"Spotted on r/{subreddit} today 👀\n\n"
        f"🎥 via {cand['author_handle']} on Reddit\n"
        f"🔗 {cand['source_url']}\n\n"
        f"#commoncreed #techhumor #programmermemes #coding #devlife"
    )
    yt_title = f"[{subreddit}] {cand['title'][:60]}"[:100]
    yt_description = (
        f"Shared from r/{subreddit}. Full credit to {cand['author_handle']}.\n"
        f"Original post: {cand['source_url']}\n\n"
        f"Posted via CommonCreed."
    )

    scheduled_slot = compute_next_slot()
    # The publish_post helper expects a "video_path" and "thumbnail_path".
    # For image posts we pass the image as BOTH slots so Postiz's upload
    # step has something to send; the publish shape on Postiz's side still
    # needs refinement for image-only posts in a later iteration.
    video_path = str(credited_path) if cand["media_type"] == "video" else ""
    thumbnail_path = (
        str(credited_path) if cand["media_type"] == "image" else str(credited_path)
    )

    if cand["media_type"] == "video":
        postiz_resp = client.publish_post(
            video_path=video_path,
            thumbnail_path=thumbnail_path,
            ig_caption=caption_ig,
            yt_title=yt_title,
            yt_description=yt_description,
            ig_collab_usernames=[],  # Reddit handles aren't IG handles
            scheduled_slot=scheduled_slot,
            media_kind="video",
        )
    else:
        # Image-only meme — IG post only, YouTube is skipped at the
        # client level. The image is uploaded once via /api/public/v1/upload
        # and queued as an IG feed post for the next peak slot.
        postiz_resp = client.publish_post(
            video_path=str(credited_path),
            thumbnail_path=str(credited_path),
            ig_caption=caption_ig,
            yt_title=yt_title,
            yt_description=yt_description,
            ig_collab_usernames=[],
            scheduled_slot=scheduled_slot,
            media_kind="image",
        )

    conn = db_module.connect(settings.SIDECAR_DB_PATH)
    try:
        db_module.update_meme_candidate(
            conn,
            candidate_id,
            status="published",
            postiz_response_json=json.dumps(postiz_resp, default=str)[:4000],
            published_at_local=datetime.utcnow().isoformat() + "Z",
        )
    finally:
        conn.close()


def _mark_failed(settings, candidate_id: int, error: str) -> None:
    try:
        conn = db_module.connect(settings.SIDECAR_DB_PATH)
        try:
            db_module.update_meme_candidate(
                conn,
                candidate_id,
                status="publish_failed",
                publish_error=error[:2000],
            )
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("meme_flow._mark_failed(%s) db failed: %s", candidate_id, exc)


# ---------------------------------------------------------------------------
# reject / deny helpers called from the Telegram callback handler
# ---------------------------------------------------------------------------


def reject_meme_candidate(candidate_id: int) -> dict:
    settings = settings_manager.settings
    if settings is None:
        settings = settings_manager.load()
    conn = db_module.connect(settings.SIDECAR_DB_PATH)
    try:
        db_module.update_meme_candidate(
            conn,
            candidate_id,
            status="rejected",
            reviewed_at=datetime.utcnow().isoformat() + "Z",
        )
    finally:
        conn.close()
    return {"ok": True, "id": candidate_id}


def deny_meme_creator(candidate_id: int) -> dict:
    settings = settings_manager.settings
    if settings is None:
        settings = settings_manager.load()
    conn = db_module.connect(settings.SIDECAR_DB_PATH)
    try:
        cand = db_module.get_meme_candidate(conn, candidate_id)
        if cand is None:
            return {"ok": False, "error": "candidate not found"}
        db_module.add_meme_creator_to_denylist(
            conn,
            cand["author_handle"],
            cand["source"],
            reason="denied from Telegram preview",
        )
        db_module.update_meme_candidate(
            conn,
            candidate_id,
            status="rejected_creator_denied",
            reviewed_at=datetime.utcnow().isoformat() + "Z",
        )
    finally:
        conn.close()
    return {"ok": True, "id": candidate_id}
