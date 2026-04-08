"""
Daily topic trigger.

Loads every enabled topic source (Gmail, Hacker News, etc. — see
``sidecar/topic_sources/``), merges their candidate items, scores the
combined set with Claude, and persists the top N as ``pending_generation``
rows in ``pipeline_runs``. The process_pending_runs job picks them up from
there within 30 seconds.

Failure isolation:
- This function NEVER raises out. All exceptions are caught at the
  outermost level and returned as ``{"ok": False, "error": "..."}``.
- Individual source failures are isolated: one broken source does not
  take down the run. As long as at least one source returns items, the
  rest of the pipeline proceeds.
"""
from __future__ import annotations

import json
import logging

from .. import db as db_module
from ..config import settings_manager
from ..topic_selector import score_topics
from ..topic_sources import load_enabled_sources

logger = logging.getLogger(__name__)


def run_daily_trigger() -> dict:
    """Run the daily topic-collection → scoring → DB-insert job.

    Returns a summary dict. On any failure, returns
    ``{"ok": False, "error": "..."}`` instead of raising.
    """
    try:
        settings = settings_manager.settings
        if settings is None:
            # Lazy load so the job can be invoked from tests / one-shot
            # exec contexts outside the FastAPI lifespan.
            try:
                settings = settings_manager.load()
            except Exception as exc:
                logger.error("daily_trigger: settings not loaded: %s", exc)
                return {"ok": False, "error": f"settings not loaded: {exc}"}

        # --- Collect from every enabled source ---------------------------
        sources = load_enabled_sources(settings)
        if not sources:
            logger.warning(
                "daily_trigger: no topic sources enabled or configured "
                "(PIPELINE_TOPIC_SOURCES)"
            )
            return {
                "ok": True,
                "skipped": True,
                "reason": "no sources enabled/configured",
                "pipeline_run_ids": [],
            }

        all_items: list[dict] = []
        source_labels: list[str] = []
        per_source_counts: dict[str, int] = {}
        for source in sources:
            try:
                items, label = source.fetch_items(settings)
            except Exception as exc:
                logger.warning(
                    "daily_trigger: source %s raised: %s",
                    getattr(source, "name", "?"),
                    exc,
                    exc_info=True,
                )
                per_source_counts[source.name] = 0
                continue
            per_source_counts[source.name] = len(items)
            if label:
                source_labels.append(f"{source.name}:{label}")
            all_items.extend(items)
            logger.info(
                "daily_trigger: source %s returned %d items",
                source.name,
                len(items),
            )

        if not all_items:
            logger.warning("daily_trigger: every enabled source returned 0 items")
            return {
                "ok": True,
                "skipped": True,
                "reason": "no items from any source",
                "per_source_counts": per_source_counts,
                "pipeline_run_ids": [],
            }

        combined_label = " | ".join(source_labels) or "daily_trigger"

        # --- Score the merged candidate set ------------------------------
        try:
            top = score_topics(all_items, top_n=2)
        except Exception as exc:
            logger.error(
                "daily_trigger: score_topics failed: %s", exc, exc_info=True
            )
            return {
                "ok": False,
                "error": f"score_topics failed: {exc}",
                "per_source_counts": per_source_counts,
                "items_collected": len(all_items),
            }

        if not top:
            logger.warning("daily_trigger: scoring returned no topics")
            return {
                "ok": True,
                "skipped": True,
                "reason": "scoring returned no topics",
                "per_source_counts": per_source_counts,
                "pipeline_run_ids": [],
            }

        # --- Persist -----------------------------------------------------
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
                        source_newsletter_date=combined_label,
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
                "per_source_counts": per_source_counts,
                "items_collected": len(all_items),
                "pipeline_run_ids": inserted_ids,
            }

        summary = {
            "ok": True,
            "per_source_counts": per_source_counts,
            "items_collected": len(all_items),
            "topics_selected": len(inserted_ids),
            "pipeline_run_ids": inserted_ids,
            "source_labels": source_labels,
        }
        logger.info("daily_trigger: success %s", json.dumps(summary))
        return summary

    except Exception as exc:  # outermost catch-all — never raise out
        logger.error(
            "daily_trigger: unexpected failure: %s", exc, exc_info=True
        )
        return {"ok": False, "error": f"unexpected: {exc}"}
