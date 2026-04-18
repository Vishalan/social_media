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
import re
from datetime import datetime
from typing import Any
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
# humor + relevance scoring — uses Claude Haiku to rate candidates (Unit 1)
# ---------------------------------------------------------------------------


def _score_candidates_batch(
    candidates: list[dict], settings: Any
) -> dict[str, dict]:
    """Rate candidates for humor AND niche relevance using Anthropic Haiku.

    Hardcoded to Anthropic Haiku (not routed through a pluggable llm_client):
    local models produce binary 10/5 scores that defeat quality filtering.
    Haiku gives nuanced gradients (3,5,7,8,9) for ~$0.001/batch, which is
    the quality-critical signal the >= 7 threshold depends on.

    Returns a dict mapping source_url -> {"humor": float, "relevance": float}.
    Candidates that can't be scored get neutral 5.0 to avoid biasing the
    ranker either way. Never raises — returns {} on any error.
    """
    if not candidates:
        return {}

    items_text = []
    for i, c in enumerate(candidates):
        eng = c.get("engagement") or {}
        sub = eng.get("subreddit", "?")
        items_text.append(
            f"{i+1}. [{c.get('media_type','?')}] r/{sub}: {c.get('title','')[:120]}"
        )

    prompt = (
        "You are scoring meme candidates for @commoncreed, an Instagram page "
        "about AI, tech, software engineering, and developer culture.\n\n"
        "For each candidate below, provide TWO scores (0-10):\n"
        "1. HUMOR — Is it genuinely funny? Would it get laughs? Score 0 for "
        "wholesome, inspirational, sad, political, or not-funny content.\n"
        "2. RELEVANCE — Is it related to: programming, software engineering, "
        "AI/ML, tech industry, developer life, CS memes, gadgets, startups, "
        "tech culture? Score 10 for directly about coding/tech. Score 5 for "
        "tangentially related (science, gaming tech, clever engineering). "
        "Score 0-2 for completely unrelated (animals, sports, cooking, nature, "
        "random viral clips).\n\n"
        + "\n".join(items_text)
        + "\n\nRespond with ONLY a JSON array of [humor, relevance] pairs, "
        "e.g. [[7, 9], [3, 1], [9, 8], ...]. No explanation."
    )

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
    if not api_key:
        logger.warning("score_candidates: no ANTHROPIC_API_KEY, skipping")
        return {}

    try:
        import httpx

        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30.0,
        )
        if resp.status_code != 200:
            logger.warning("score_candidates: API %d", resp.status_code)
            return {}

        text = resp.json()["content"][0]["text"].strip()

        # Parse nested JSON array [[h,r], [h,r], ...]
        m = re.search(r"\[[\s\S]*\]", text)
        if not m:
            logger.warning("score_candidates: no array in response: %s", text[:200])
            return {}

        pairs = json.loads(m.group())
        result: dict[str, dict] = {}
        for i, c in enumerate(candidates):
            if i < len(pairs) and isinstance(pairs[i], list) and len(pairs[i]) >= 2:
                result[c["source_url"]] = {
                    "humor": float(pairs[i][0]),
                    "relevance": float(pairs[i][1]),
                }
            else:
                result[c["source_url"]] = {"humor": 5.0, "relevance": 5.0}
        logger.info(
            "score_candidates: haiku scored %d (avg humor=%.1f, avg relevance=%.1f)",
            len(result),
            sum(v["humor"] for v in result.values()) / max(len(result), 1),
            sum(v["relevance"] for v in result.values()) / max(len(result), 1),
        )
        return result
    except Exception as exc:
        logger.warning("score_candidates: failed: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# cross-run dedup — 48h title Jaccard lookback (Unit 3)
# ---------------------------------------------------------------------------


_WORD_RE = re.compile(r"[a-z0-9]+")


def _jaccard_title(a: str, b: str) -> float:
    """Jaccard similarity on the tokenized title word set.

    Follows the same tokenizer pattern as ``sidecar/duplicate_guard.py``:
    lowercase alphanumeric word tokens, empty sets return 0.0.
    """
    if not a or not b:
        return 0.0
    ta = set(_WORD_RE.findall(a.lower()))
    tb = set(_WORD_RE.findall(b.lower()))
    if not ta or not tb:
        return 0.0
    union = len(ta | tb)
    if union == 0:
        return 0.0
    return len(ta & tb) / union


def _fetch_recent_surfaced_titles(conn) -> list[str]:
    """Return titles of candidates surfaced to Telegram in the last 48h.

    Used by the cross-run dedup check before surfacing a new candidate.
    Safe-fails to an empty list on any DB error so the trigger still runs.
    """
    try:
        rows = conn.execute(
            """
            SELECT title FROM meme_candidates
             WHERE telegram_message_id IS NOT NULL
               AND created_at >= datetime('now', '-2 days')
            """
        ).fetchall()
        return [r["title"] for r in rows if r["title"]]
    except Exception as exc:
        logger.warning("fetch_recent_surfaced_titles: %s", exc)
        return []


def _is_cross_run_duplicate(
    title: str, recent_titles: list[str], threshold: float = 0.7
) -> bool:
    """True if ``title`` is >= ``threshold`` Jaccard-similar to any recent title.

    Used to prevent surfacing the same meme twice across runs within the 48h
    lookback window.
    """
    if not title or not recent_titles:
        return False
    for rt in recent_titles:
        if _jaccard_title(title, rt) >= threshold:
            return True
    return False


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

    # --- Unit 1: Humor + relevance scoring via Claude Haiku ---
    # Score all candidates for humor AND niche relevance before ranking so
    # we surface genuinely funny tech/AI content and hard-filter out
    # off-brand viral content. Attach scores to each candidate dict so the
    # ranker + logs can see them.
    candidate_scores = await asyncio.to_thread(
        _score_candidates_batch, all_candidates, settings
    )
    for c in all_candidates:
        scores = candidate_scores.get(c["source_url"], {})
        c["humor_score"] = scores.get("humor", 5.0)
        c["relevance_score"] = scores.get("relevance", 5.0)

    # --- Unit 1: Hard filter — only humor >= 7 AND relevance >= 7 survive ---
    min_humor = int(getattr(settings, "MEME_MIN_HUMOR_SCORE", 7) or 7)
    min_relevance = int(getattr(settings, "MEME_MIN_RELEVANCE_SCORE", 7) or 7)
    before_filter = len(all_candidates)
    all_candidates = [
        c for c in all_candidates
        if c.get("humor_score", 0) >= min_humor
        and c.get("relevance_score", 0) >= min_relevance
    ]
    logger.info(
        "meme_trigger: quality filter kept %d/%d (humor>=%d, relevance>=%d)",
        len(all_candidates),
        before_filter,
        min_humor,
        min_relevance,
    )

    # --- Unit 2: Per-media-type surface limits ---
    image_surface_limit = int(
        getattr(settings, "MEME_DAILY_SURFACE_LIMIT", 2) or 2
    )
    video_surface_limit = int(
        getattr(settings, "MEME_VIDEO_DAILY_SURFACE_LIMIT", 2) or 2
    )

    # Sort by Reddit score descending for deterministic top-N picking
    def _score(c: dict) -> int:
        return int((c.get("engagement") or {}).get("score") or 0)

    def _is_video(c: dict) -> bool:
        return (c.get("media_type") or "").lower() in ("video", "gif")

    all_candidates.sort(key=_score, reverse=True)

    inserted_ids: list[int] = []
    surfaced_ids: list[int] = []
    try:
        conn = db_module.connect(settings.SIDECAR_DB_PATH)
    except Exception as exc:
        logger.error("meme_trigger: db connect failed: %s", exc)
        return {"ok": False, "error": f"db: {exc}", "per_source": per_source}

    # --- Unit 3: Pre-load recently surfaced titles for cross-run dedup ---
    recent_surfaced_titles = _fetch_recent_surfaced_titles(conn)

    image_surfaced = 0
    video_surfaced = 0
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

            # Unit 3 — cross-run dedup: skip surfacing if a similar-title
            # candidate was surfaced in the last 48h. The row stays in
            # pending_review so autopilot can still pick it up later.
            if _is_cross_run_duplicate(
                cand.get("title", ""), recent_surfaced_titles, threshold=0.7
            ):
                logger.info(
                    "meme_trigger: cross-run dup skipped (48h, J>=0.7): %s",
                    cand.get("title", "")[:80],
                )
                continue

            # Unit 2 — surface up to per-type quotas; skip the rest (they
            # stay pending_review and remain eligible for autopilot).
            if _is_video(cand):
                if video_surfaced < video_surface_limit:
                    surfaced_ids.append(row_id)
                    video_surfaced += 1
            else:
                if image_surfaced < image_surface_limit:
                    surfaced_ids.append(row_id)
                    image_surfaced += 1
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

    # Schedule the autopilot fallback so that if the owner doesn't tap any
    # of the previews, the highest-scored ones still publish at the next
    # peak slot. Idempotent — replaces any existing scheduled job.
    auto_job_id = None
    if surfaced_ids:
        auto_job_id = schedule_meme_auto_approve_after_trigger(settings)

    return {
        "ok": True,
        "per_source": per_source,
        "total_fetched": len(all_candidates),
        "inserted": len(inserted_ids),
        "surfaced": len(surfaced_ids),
        "surfaced_images": image_surfaced,
        "surfaced_videos": video_surfaced,
        "telegram_sent": len(sent),
        "inserted_ids": inserted_ids,
        "surfaced_ids": surfaced_ids,
        "auto_approve_job_id": auto_job_id,
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


async def meme_auto_approve_action() -> dict:
    """Fired by APScheduler at next-peak-slot - MEME_AUTO_APPROVE_OFFSET_MIN.

    Picks the top-scoring meme candidates that are still in
    ``pending_review`` and auto-publishes ``MEME_DAILY_AUTO_APPROVE_COUNT``
    of them. The rest are marked ``auto_skipped`` so they don't pile up
    across days.

    Never raises. Safe-fail closed: if Postiz/sidecar/network is down at
    fire time, the candidates stay in pending_review and the next
    scheduled tick (or the next manual trigger) gets another chance.
    """
    settings = settings_manager.settings
    if settings is None:
        try:
            settings = settings_manager.load()
        except Exception as exc:
            logger.error("meme_auto_approve_action: settings: %s", exc)
            return {"ok": False, "error": f"settings: {exc}"}

    if not bool(getattr(settings, "MEME_AUTO_APPROVE_ENABLED", True)):
        logger.info("meme_auto_approve_action: disabled, skipping")
        return {"ok": True, "skipped": True, "reason": "disabled"}

    take = int(getattr(settings, "MEME_DAILY_AUTO_APPROVE_COUNT", 1) or 1)

    # Find the top N pending_review meme candidates by Reddit score.
    try:
        conn = db_module.connect(settings.SIDECAR_DB_PATH)
    except Exception as exc:
        logger.error("meme_auto_approve_action: db connect: %s", exc)
        return {"ok": False, "error": f"db: {exc}"}

    try:
        rows = conn.execute(
            """
            SELECT id, engagement_json
              FROM meme_candidates
             WHERE status = 'pending_review'
             ORDER BY id DESC
            """
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        logger.info("meme_auto_approve_action: no pending candidates")
        return {"ok": True, "picked": 0, "reason": "no pending"}

    def _score(row) -> int:
        try:
            return int((json.loads(row["engagement_json"] or "{}")).get("score") or 0)
        except Exception:
            return 0

    sorted_rows = sorted(rows, key=_score, reverse=True)
    chosen_ids = [int(r["id"]) for r in sorted_rows[:take]]
    skipped_ids = [int(r["id"]) for r in sorted_rows[take:]]

    logger.info(
        "meme_auto_approve_action: picked %d (top score=%d), skipping %d",
        len(chosen_ids),
        _score(sorted_rows[0]) if sorted_rows else 0,
        len(skipped_ids),
    )

    # Skip the rest first so subsequent ticks see a clean slate
    if skipped_ids:
        try:
            conn = db_module.connect(settings.SIDECAR_DB_PATH)
            try:
                with conn:
                    for sid in skipped_ids:
                        conn.execute(
                            "UPDATE meme_candidates SET status='auto_skipped' WHERE id=?",
                            (sid,),
                        )
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("meme_auto_approve_action: skip-mark failed: %s", exc)

    # Publish the chosen candidates serially (nas_heavy_work_lock would
    # serialize them anyway, but explicit is better than implicit)
    results: list[dict] = []
    for cid in chosen_ids:
        try:
            r = await publish_meme_candidate(cid)
            results.append({"id": cid, "ok": r.get("ok"), "error": r.get("error")})
        except Exception as exc:
            logger.exception(
                "meme_auto_approve_action: publish_meme_candidate(%s) raised: %s",
                cid,
                exc,
            )
            results.append({"id": cid, "ok": False, "error": str(exc)})

    return {
        "ok": True,
        "picked": chosen_ids,
        "skipped": skipped_ids,
        "results": results,
    }


def schedule_meme_auto_approve_after_trigger(
    settings: Any,
) -> str | None:
    """Schedule one meme_auto_approve_action job at next-peak-slot - offset.

    Idempotent on the day: replaces any existing job with the same id.
    Returns the job_id, or None if no scheduler is registered.
    """
    from .. import runtime as _rt
    from .publish import compute_next_slot
    from datetime import timedelta as _td

    sched = getattr(_rt, "scheduler", None)
    if sched is None:
        logger.info(
            "schedule_meme_auto_approve_after_trigger: no scheduler registered"
        )
        return None

    offset_min = int(
        getattr(settings, "MEME_AUTO_APPROVE_OFFSET_MIN", 30) or 30
    )
    slot = compute_next_slot()
    fire_at = slot - _td(minutes=offset_min)
    if fire_at < datetime.now():
        fire_at = datetime.now() + _td(seconds=10)

    job_id = "meme_auto_approve_next_slot"
    try:
        sched.add_job(
            meme_auto_approve_action,
            trigger="date",
            run_date=fire_at,
            id=job_id,
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info(
            "scheduled meme_auto_approve at %s (slot=%s, offset=%dmin)",
            fire_at.isoformat(),
            slot.isoformat(),
            offset_min,
        )
    except Exception as exc:
        logger.warning(
            "schedule_meme_auto_approve_after_trigger add_job failed: %s", exc
        )
        return None
    return job_id


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
