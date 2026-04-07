"""
Duplicate guard (Unit 9).

Prevents re-posting the same topic within a lookback window. Two checks:
  1. Exact topic_url match
  2. Jaccard similarity on the title word set (default threshold 0.85)

Only considers runs in terminal/successful statuses
('generated', 'approved', 'auto_approved', 'published') — in-flight runs
(pending_generation, failed, etc.) do NOT block new work on the same URL.

Never raises. On any DB error returns
``{"is_duplicate": False, "match_run_id": None, "match_reason": "db error: ..."}``.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)


TERMINAL_STATUSES = ("generated", "approved", "auto_approved", "published")
DEFAULT_JACCARD_THRESHOLD = 0.8
_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set:
    if not text:
        return set()
    return set(_WORD_RE.findall(text.lower()))


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def check(
    conn: sqlite3.Connection,
    topic_url: str,
    topic_title: str,
    lookback_days: int = 30,
    jaccard_threshold: float = DEFAULT_JACCARD_THRESHOLD,
    exclude_run_id: int | None = None,
) -> dict:
    """Return a dict describing whether this topic is a duplicate.

    ``{"is_duplicate": bool, "match_run_id": int | None, "match_reason": str}``

    ``exclude_run_id`` skips a specific pipeline_runs.id from the candidate
    set — required when called from publish_action because the run being
    published is already in a terminal status (`generated`) and would
    otherwise self-match as a duplicate.
    """
    try:
        placeholders = ",".join("?" for _ in TERMINAL_STATUSES)
        sql = (
            f"SELECT id, topic_url, topic_title, created_at, status "
            f"FROM pipeline_runs "
            f"WHERE status IN ({placeholders}) "
            f"  AND created_at >= datetime('now', ?) "
        )
        params: list = list(TERMINAL_STATUSES) + [f"-{int(lookback_days)} days"]
        if exclude_run_id is not None:
            sql += "  AND id != ? "
            params.append(int(exclude_run_id))
        sql += "ORDER BY created_at DESC, id DESC"
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("duplicate_guard: db error: %s", exc)
        return {
            "is_duplicate": False,
            "match_run_id": None,
            "match_reason": f"db error: {exc}",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("duplicate_guard: unexpected error: %s", exc)
        return {
            "is_duplicate": False,
            "match_run_id": None,
            "match_reason": f"db error: {exc}",
        }

    url_norm = (topic_url or "").strip()
    title_tokens = _tokenize(topic_title or "")

    # Prefer exact URL match
    if url_norm:
        for r in rows:
            row_url = (r["topic_url"] if "topic_url" in r.keys() else None) or ""
            if row_url.strip() == url_norm:
                return {
                    "is_duplicate": True,
                    "match_run_id": int(r["id"]),
                    "match_reason": f"exact url match: {url_norm}",
                }

    # Then title similarity
    if title_tokens:
        for r in rows:
            row_title = (r["topic_title"] if "topic_title" in r.keys() else None) or ""
            score = _jaccard(title_tokens, _tokenize(row_title))
            if score >= jaccard_threshold:
                return {
                    "is_duplicate": True,
                    "match_run_id": int(r["id"]),
                    "match_reason": (
                        f"title similarity {score:.2f} >= {jaccard_threshold}: "
                        f"{row_title!r}"
                    ),
                }

    return {
        "is_duplicate": False,
        "match_run_id": None,
        "match_reason": "no match",
    }
