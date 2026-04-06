"""
APScheduler job: process pending pipeline_runs rows sequentially.

Unit 4. Runs every 30 seconds, picks up any rows with status
``pending_generation``, and drives them through ``pipeline_runner.run_pipeline_for_run``
one at a time. A module-level asyncio.Lock enforces the invariant that ONLY
ONE subprocess may run at a time across the entire sidecar — pipeline peaks
are ~2 GB RSS and the DS1520+ cannot afford parallel video gens.

Failure isolation: this function NEVER raises out. The loop catches per-row
exceptions (defense in depth, since ``run_pipeline_for_run`` already promises
not to raise) so that one bad video does not block the other one in the same
batch (R15).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .. import db as db_module
from .. import pipeline_runner
from ..config import settings_manager

logger = logging.getLogger(__name__)

# Module-level lock enforcing single-subprocess invariant.
_pipeline_lock = asyncio.Lock()


async def process_pending_runs() -> dict:
    """Scan pipeline_runs for pending_generation rows and process them in order.

    Returns a dict summary. Never raises.
    """
    try:
        if _pipeline_lock.locked():
            logger.info(
                "process_pending_runs: lock already held, skipping this tick"
            )
            return {"skipped": True, "reason": "another run in progress"}

        async with _pipeline_lock:
            settings = settings_manager.settings
            if settings is None:
                try:
                    settings = settings_manager.load()
                except Exception as exc:
                    logger.error(
                        "process_pending_runs: settings not loaded: %s", exc
                    )
                    return {
                        "ok": False,
                        "error": f"settings not loaded: {exc}",
                        "processed": 0,
                        "succeeded": 0,
                    }

            # --- Fetch pending rows --------------------------------------
            try:
                conn = db_module.connect(settings.SIDECAR_DB_PATH)
                try:
                    rows = db_module.get_pending_pipeline_runs(conn)
                finally:
                    conn.close()
            except Exception as exc:
                logger.exception(
                    "process_pending_runs: failed to query pending rows: %s",
                    exc,
                )
                return {
                    "ok": False,
                    "error": f"query: {exc}",
                    "processed": 0,
                    "succeeded": 0,
                }

            if not rows:
                return {"ok": True, "processed": 0, "succeeded": 0}

            # --- Sequential execution ------------------------------------
            processed = 0
            succeeded = 0
            results: list[Any] = []
            for row in rows:
                run_id = int(row["id"])
                try:
                    result = await pipeline_runner.run_pipeline_for_run(run_id)
                except Exception as exc:
                    # pipeline_runner promises not to raise, but defense in
                    # depth: log and continue to the next row so one failure
                    # never blocks the other (R15).
                    logger.exception(
                        "process_pending_runs: run_pipeline_for_run raised "
                        "for run %s: %s",
                        run_id,
                        exc,
                    )
                    result = {
                        "ok": False,
                        "id": run_id,
                        "error": f"collaborator raised: {exc}",
                    }
                processed += 1
                if isinstance(result, dict) and result.get("ok"):
                    succeeded += 1
                results.append(result)

            return {
                "ok": True,
                "processed": processed,
                "succeeded": succeeded,
                "results": results,
            }

    except Exception as exc:  # outermost catch-all — never raise
        logger.exception(
            "process_pending_runs: unexpected failure: %s", exc
        )
        return {"ok": False, "error": f"unexpected: {exc}"}
