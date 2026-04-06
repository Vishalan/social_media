"""
Daily 05:00 newsletter trigger.

Fetches the most recent TLDR AI newsletter, extracts stories, scores them,
and persists the top 2 as `pending_generation` rows in `pipeline_runs`.

Failure isolation: this function NEVER raises out. ANY exception is caught
at the outermost level, logged with context, and a failure-marker dict is
returned. APScheduler's job-error layer is a safety net, not our primary
defense.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .. import db as db_module
from ..config import settings_manager
from ..gmail_client import GmailClient
from ..topic_selector import extract_items, score_topics

logger = logging.getLogger(__name__)


def _load_oauth_token_json(oauth_path: str) -> str:
    """Read the Gmail OAuth token JSON file as a raw string."""
    return Path(oauth_path).read_text()


def run_daily_trigger() -> dict:
    """Run the daily newsletter → topic-selection → DB-insert job.

    Returns a summary dict. On any failure, returns a dict with
    ``{"ok": False, "error": "..."}`` instead of raising.
    """
    try:
        settings = settings_manager.settings
        if settings is None:
            # Attempt a lazy load so this can be invoked outside the FastAPI
            # lifespan (e.g. from tests that patch settings_manager).
            try:
                settings = settings_manager.load()
            except Exception as exc:
                logger.error("daily_trigger: settings not loaded: %s", exc)
                return {"ok": False, "error": f"settings not loaded: {exc}"}

        # --- Gmail fetch --------------------------------------------------
        try:
            oauth_json = _load_oauth_token_json(settings.GMAIL_OAUTH_PATH)
            gmail = GmailClient(oauth_json)
            newsletter = gmail.fetch_latest_newsletter()
        except Exception as exc:
            logger.error("daily_trigger: gmail fetch failed: %s", exc, exc_info=True)
            return {"ok": False, "error": f"gmail fetch failed: {exc}"}

        if newsletter is None:
            logger.info("daily_trigger: no newsletter within 24h, skipping")
            return {
                "ok": True,
                "skipped": True,
                "reason": "no newsletter within 24h",
                "pipeline_run_ids": [],
            }

        body_text = newsletter.get("body_text", "") or ""
        newsletter_date = newsletter.get("received_at", "") or ""

        # --- Extraction ---------------------------------------------------
        try:
            items = extract_items(body_text)
        except Exception as exc:
            logger.error(
                "daily_trigger: extract_items failed: %s", exc, exc_info=True
            )
            return {
                "ok": False,
                "error": f"extract_items failed: {exc}",
                "newsletter_date": newsletter_date,
            }

        if not items:
            logger.warning("daily_trigger: no items extracted from newsletter")
            return {
                "ok": True,
                "skipped": True,
                "reason": "no items extracted",
                "newsletter_date": newsletter_date,
                "pipeline_run_ids": [],
            }

        # --- Scoring ------------------------------------------------------
        try:
            top = score_topics(items, top_n=2)
        except Exception as exc:
            logger.error(
                "daily_trigger: score_topics failed: %s", exc, exc_info=True
            )
            return {
                "ok": False,
                "error": f"score_topics failed: {exc}",
                "newsletter_date": newsletter_date,
                "items_extracted": len(items),
            }

        if not top:
            logger.warning("daily_trigger: scoring returned no topics")
            return {
                "ok": True,
                "skipped": True,
                "reason": "scoring returned no topics",
                "newsletter_date": newsletter_date,
                "pipeline_run_ids": [],
            }

        # --- Persist ------------------------------------------------------
        inserted_ids: list[int] = []
        try:
            conn = db_module.connect(settings.SIDECAR_DB_PATH)
            try:
                for t in top:
                    run_id = db_module.insert_pipeline_run(
                        conn,
                        topic_title=str(t.get("title", "")),
                        topic_url=str(t.get("url", "")),
                        topic_score=float(t.get("score", 0) or 0),
                        selection_rationale=str(t.get("rationale", "")),
                        source_newsletter_date=newsletter_date,
                    )
                    inserted_ids.append(run_id)
            finally:
                conn.close()
        except Exception as exc:
            logger.error(
                "daily_trigger: db insert failed: %s", exc, exc_info=True
            )
            return {
                "ok": False,
                "error": f"db insert failed: {exc}",
                "newsletter_date": newsletter_date,
                "items_extracted": len(items),
                "pipeline_run_ids": inserted_ids,
            }

        summary = {
            "ok": True,
            "newsletter_date": newsletter_date,
            "items_extracted": len(items),
            "topics_selected": len(inserted_ids),
            "pipeline_run_ids": inserted_ids,
        }
        logger.info("daily_trigger: success %s", json.dumps(summary))
        return summary

    except Exception as exc:  # outermost catch-all — never raise out
        logger.error(
            "daily_trigger: unexpected failure: %s", exc, exc_info=True
        )
        return {"ok": False, "error": f"unexpected: {exc}"}
