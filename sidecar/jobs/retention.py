"""
Retention job (Unit 9).

Daily prune of video/audio/thumbnail files older than N days. The
pipeline_runs row is KEPT (for analytics) but the file-path columns are
NULLed and ``retention_pruned_at`` is stamped.

Failure isolation: outermost try/except — never raises.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from .. import db as db_module
from ..config import settings_manager

logger = logging.getLogger(__name__)


PATH_COLUMNS = ("video_path", "audio_path", "thumbnail_path")


def _open_conn():
    s = settings_manager.settings
    if s is None:
        raise RuntimeError("settings not loaded")
    return db_module.connect(s.SIDECAR_DB_PATH)


async def run_retention_job(retention_days: int = 14) -> dict:
    """Prune old generation artifacts. Never raises."""
    result: dict = {"pruned": [], "rows_updated": 0, "bytes_freed": 0}
    try:
        try:
            conn = _open_conn()
        except Exception as exc:
            logger.warning("retention: cannot open db: %s", exc)
            return {**result, "error": str(exc)}

        try:
            cutoff = (
                datetime.utcnow() - timedelta(days=int(retention_days))
            ).isoformat(timespec="seconds")
            try:
                rows = conn.execute(
                    "SELECT id, video_path, audio_path, thumbnail_path, "
                    "created_at, retention_pruned_at "
                    "FROM pipeline_runs "
                    "WHERE created_at < ? "
                    "  AND (retention_pruned_at IS NULL OR retention_pruned_at = '')",
                    (cutoff,),
                ).fetchall()
            except Exception as exc:
                logger.warning("retention: select failed: %s", exc)
                return {**result, "error": str(exc)}

            for r in rows:
                row_id = int(r["id"])
                any_pruned = False
                for col in PATH_COLUMNS:
                    try:
                        path = r[col]
                    except Exception:
                        path = None
                    if not path:
                        continue
                    try:
                        if os.path.exists(path):
                            try:
                                size = os.path.getsize(path)
                            except Exception:
                                size = 0
                            try:
                                os.remove(path)
                                result["pruned"].append(path)
                                result["bytes_freed"] += int(size)
                                any_pruned = True
                            except Exception as exc:
                                logger.warning(
                                    "retention: remove %s failed: %s",
                                    path,
                                    exc,
                                )
                        else:
                            # Missing files are fine — still null the row.
                            any_pruned = True
                    except Exception as exc:
                        logger.warning(
                            "retention: path check %s failed: %s", path, exc
                        )

                try:
                    db_module.mark_retention_pruned(conn, row_id)
                    result["rows_updated"] += 1
                except Exception as exc:
                    logger.warning(
                        "retention: mark_retention_pruned(%d) failed: %s",
                        row_id,
                        exc,
                    )
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return result
    except Exception as exc:  # outermost catch-all — never raise out
        logger.error("retention: unexpected failure: %s", exc, exc_info=True)
        return {**result, "error": f"unexpected: {exc}"}
