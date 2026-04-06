"""Tests for sidecar.jobs.daily_trigger."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import db as db_module  # noqa: E402
from sidecar.jobs import daily_trigger as dt_module  # noqa: E402


SAMPLE_ITEMS = [
    {"title": "Story A", "url": "https://a", "description": "d", "category": "c"},
    {"title": "Story B", "url": "https://b", "description": "d", "category": "c"},
    {"title": "Story C", "url": "https://c", "description": "d", "category": "c"},
]

TOP_TWO = [
    {"title": "Story A", "url": "https://a", "description": "d", "score": 38, "rationale": "big"},
    {"title": "Story B", "url": "https://b", "description": "d", "score": 30, "rationale": "good"},
]


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "sidecar.sqlite3")
    db_module.init_db(db_path)
    return db_path


@pytest.fixture
def fake_settings(tmp_db, tmp_path):
    oauth = tmp_path / "oauth.json"
    oauth.write_text('{"refresh_token":"x","client_id":"c","client_secret":"s"}')
    return SimpleNamespace(
        SIDECAR_DB_PATH=tmp_db,
        GMAIL_OAUTH_PATH=str(oauth),
    )


@pytest.fixture
def patch_settings(fake_settings):
    with patch.object(dt_module.settings_manager, "_settings", fake_settings), \
         patch.object(
             dt_module.settings_manager.__class__,
             "settings",
             property(lambda self: fake_settings),
         ):
        yield fake_settings


def _make_gmail(newsletter):
    inst = MagicMock()
    inst.fetch_latest_newsletter.return_value = newsletter
    return inst


def test_happy_path_creates_two_runs(patch_settings, tmp_db):
    newsletter = {
        "message_id": "m1",
        "received_at": "2026-04-05T05:00:00+00:00",
        "subject": "TLDR AI",
        "body_text": "stories...",
    }
    with patch.object(dt_module, "GmailClient", return_value=_make_gmail(newsletter)), \
         patch.object(dt_module, "extract_items", return_value=SAMPLE_ITEMS), \
         patch.object(dt_module, "score_topics", return_value=TOP_TWO):
        result = dt_module.run_daily_trigger()

    assert result["ok"] is True
    assert result["topics_selected"] == 2
    assert len(result["pipeline_run_ids"]) == 2
    # Verify rows landed in the DB
    conn = db_module.connect(tmp_db)
    try:
        rows = conn.execute(
            "SELECT topic_title, topic_url, topic_score, selection_rationale,"
            " source_newsletter_date, status FROM pipeline_runs ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 2
    assert rows[0]["topic_title"] == "Story A"
    assert rows[0]["topic_score"] == 38
    assert rows[0]["source_newsletter_date"] == "2026-04-05T05:00:00+00:00"
    assert rows[0]["status"] == "pending_generation"
    assert rows[1]["topic_title"] == "Story B"


def test_no_newsletter_skips_day(patch_settings, tmp_db):
    with patch.object(dt_module, "GmailClient", return_value=_make_gmail(None)), \
         patch.object(dt_module, "extract_items") as ext, \
         patch.object(dt_module, "score_topics") as sc:
        result = dt_module.run_daily_trigger()

    assert result["ok"] is True
    assert result.get("skipped") is True
    assert result["pipeline_run_ids"] == []
    ext.assert_not_called()
    sc.assert_not_called()

    conn = db_module.connect(tmp_db)
    try:
        count = conn.execute("SELECT COUNT(*) AS n FROM pipeline_runs").fetchone()["n"]
    finally:
        conn.close()
    assert count == 0


def test_extraction_failure_skips_day(patch_settings, tmp_db):
    newsletter = {
        "message_id": "m1",
        "received_at": "2026-04-05T05:00:00+00:00",
        "subject": "TLDR AI",
        "body_text": "stories",
    }
    with patch.object(dt_module, "GmailClient", return_value=_make_gmail(newsletter)), \
         patch.object(dt_module, "extract_items", side_effect=ValueError("bad json")), \
         patch.object(dt_module, "score_topics") as sc:
        result = dt_module.run_daily_trigger()

    assert result["ok"] is False
    assert "extract_items failed" in result["error"]
    sc.assert_not_called()

    conn = db_module.connect(tmp_db)
    try:
        count = conn.execute("SELECT COUNT(*) AS n FROM pipeline_runs").fetchone()["n"]
    finally:
        conn.close()
    assert count == 0


def test_scoring_failure_skips_day(patch_settings, tmp_db):
    newsletter = {
        "message_id": "m1",
        "received_at": "2026-04-05T05:00:00+00:00",
        "subject": "TLDR AI",
        "body_text": "stories",
    }
    with patch.object(dt_module, "GmailClient", return_value=_make_gmail(newsletter)), \
         patch.object(dt_module, "extract_items", return_value=SAMPLE_ITEMS), \
         patch.object(dt_module, "score_topics", side_effect=ValueError("score drift")):
        result = dt_module.run_daily_trigger()

    assert result["ok"] is False
    assert "score_topics failed" in result["error"]

    conn = db_module.connect(tmp_db)
    try:
        count = conn.execute("SELECT COUNT(*) AS n FROM pipeline_runs").fetchone()["n"]
    finally:
        conn.close()
    assert count == 0
