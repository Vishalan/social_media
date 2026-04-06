"""Unit 9 — duplicate_guard tests."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import db as db_module  # noqa: E402
from sidecar.duplicate_guard import check  # noqa: E402


@pytest.fixture
def conn(tmp_path):
    p = str(tmp_path / "dup.sqlite3")
    db_module.init_db(p)
    c = db_module.connect(p)
    yield c
    c.close()


def _insert(conn, title, url, status="published", created_at=None):
    run_id = db_module.insert_pipeline_run(
        conn,
        topic_title=title,
        topic_url=url,
        topic_score=1.0,
        selection_rationale="r",
        source_newsletter_date="2026-04-06",
        status=status,
    )
    if created_at is not None:
        conn.execute(
            "UPDATE pipeline_runs SET created_at = ? WHERE id = ?",
            (created_at, run_id),
        )
        conn.commit()
    return run_id


def test_exact_url_match_detected(conn):
    _insert(conn, "Some Title", "https://example.com/x", "published")
    out = check(conn, "https://example.com/x", "Different Title")
    assert out["is_duplicate"] is True
    assert "url" in out["match_reason"]


def test_different_url_not_duplicate(conn):
    _insert(conn, "Totally Unrelated Story", "https://example.com/a", "published")
    out = check(conn, "https://example.com/b", "Another Title")
    assert out["is_duplicate"] is False


def test_old_run_outside_lookback_not_duplicate(conn):
    old = (datetime.utcnow() - timedelta(days=60)).isoformat(timespec="seconds")
    _insert(
        conn,
        "OpenAI launches GPT-5",
        "https://example.com/old",
        "published",
        created_at=old,
    )
    out = check(conn, "https://example.com/old", "OpenAI launches GPT-5", lookback_days=30)
    assert out["is_duplicate"] is False


def test_jaccard_similarity_above_threshold(conn):
    _insert(conn, "OpenAI launches GPT-5", "https://a.com/1", "published")
    out = check(conn, "https://b.com/2", "OpenAI launches GPT-5 model")
    assert out["is_duplicate"] is True
    assert "similarity" in out["match_reason"]


def test_jaccard_similarity_below_threshold(conn):
    _insert(conn, "OpenAI launches GPT-5", "https://a.com/1", "published")
    out = check(conn, "https://b.com/2", "Google Cloud releases new database product")
    assert out["is_duplicate"] is False


def test_db_error_returns_not_duplicate_safely():
    class BadConn:
        def execute(self, *a, **kw):
            import sqlite3

            raise sqlite3.Error("boom")

    out = check(BadConn(), "https://x", "t")
    assert out["is_duplicate"] is False
    assert "db error" in out["match_reason"]


def test_only_matches_terminal_statuses(conn):
    _insert(conn, "Blocked topic", "https://a.com/p", status="pending_generation")
    _insert(conn, "Failed topic", "https://a.com/f", status="failed")
    out1 = check(conn, "https://a.com/p", "Blocked topic")
    out2 = check(conn, "https://a.com/f", "Failed topic")
    assert out1["is_duplicate"] is False
    assert out2["is_duplicate"] is False

    _insert(conn, "Good topic", "https://a.com/g", status="published")
    out3 = check(conn, "https://a.com/g", "Good topic")
    assert out3["is_duplicate"] is True
