"""Unit 7 — publish job tests. All HTTP / external boundaries mocked."""
from __future__ import annotations

import asyncio
import json
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import db as db_module  # noqa: E402
from sidecar.jobs import publish as pub  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    p = str(tmp_path / "sidecar.sqlite3")
    db_module.init_db(p)
    return p


@pytest.fixture
def patched_settings(db_path, monkeypatch):
    fake = types.SimpleNamespace(
        SIDECAR_DB_PATH=db_path,
        TELEGRAM_BOT_TOKEN="x",
        TELEGRAM_CHAT_ID="123",
        POSTIZ_BASE_URL="http://postiz",
        POSTIZ_API_KEY="key",
        PIPELINE_AUTO_APPROVE_OFFSET_MIN=30,
    )
    monkeypatch.setattr(
        pub.settings_manager, "_settings", fake, raising=False
    )
    monkeypatch.setattr(
        type(pub.settings_manager),
        "settings",
        property(lambda self: fake),
    )
    return fake


@pytest.fixture
def seeded_run(db_path, patched_settings, tmp_path):
    conn = db_module.connect(db_path)
    try:
        run_id = db_module.insert_pipeline_run(
            conn,
            topic_title="Test",
            topic_url="https://example.com/x",
            topic_score=0.9,
            selection_rationale="why",
            source_newsletter_date="2026-04-06",
            status="awaiting_approval",
        )
        v = tmp_path / "v.mp4"
        v.write_bytes(b"v")
        t = tmp_path / "t.jpg"
        t.write_bytes(b"t")
        db_module.update_pipeline_run_generation_result(
            conn, run_id, "awaiting_approval", str(v), str(t), None,
            0, 0, 0, 0, None, None, None,
        )
        db_module.set_captions(conn, run_id, {
            "instagram": {"caption": "hi", "hashtags": ["#a"]},
            "youtube": {"title": "yt", "description": "desc"},
        })
        db_module.create_approval(conn, run_id, telegram_message_id=1)
    finally:
        conn.close()
    return run_id


def _set_approval_status(db_path, run_id, status):
    conn = db_module.connect(db_path)
    try:
        row = db_module.get_approval_by_run_id(conn, run_id)
        db_module.update_approval_status(conn, row["id"], status, "now")
    finally:
        conn.close()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# publish_action
# ---------------------------------------------------------------------------

def _patch_postiz(monkeypatch, publish_resp=None, tokens=None, raise_exc=None):
    fake_client = MagicMock()
    if raise_exc is not None:
        fake_client.publish_post.side_effect = raise_exc
    else:
        fake_client.publish_post.return_value = publish_resp or {
            "posts": [
                {"platform": "instagram", "id": "ig_123"},
                {"platform": "youtube", "id": "yt_456"},
            ]
        }
    fake_client.get_account_tokens.return_value = tokens or {
        "instagram": {"acct": {"access_token": "tk", "user_id": "iguid"}}
    }
    monkeypatch.setattr(
        "sidecar.postiz_client.make_client_from_settings",
        lambda s: fake_client,
    )
    return fake_client


def _patch_ig(monkeypatch, verify_results=None, edit_result=None, recreate_result=None):
    fake = MagicMock()
    if verify_results is None:
        verify_results = [True]
    fake.verify_collab.side_effect = list(verify_results)
    fake.add_collab_by_edit.return_value = edit_result
    fake.add_collab_by_recreate.return_value = recreate_result or {"ok": False}

    class _Stub:
        def __init__(self, access_token, **kw):
            pass

        def __new__(cls, *a, **kw):
            return fake

    monkeypatch.setattr("sidecar.ig_direct.IGDirectClient", _Stub)
    return fake


def _patch_telegram(monkeypatch):
    monkeypatch.setattr(pub, "_send_telegram", AsyncMock())


def test_publish_happy_path_collab_verified(seeded_run, db_path, patched_settings, monkeypatch):
    _set_approval_status(db_path, seeded_run, "approved")
    _patch_postiz(monkeypatch)
    _patch_ig(monkeypatch, verify_results=[True])
    _patch_telegram(monkeypatch)

    out = _run(pub.publish_action(seeded_run))
    assert out["ok"] is True
    assert out["collab_ok"] is True
    assert out["post_ids"]["instagram"] == "ig_123"

    conn = db_module.connect(db_path)
    try:
        row = db_module.get_pipeline_run(conn, seeded_run)
    finally:
        conn.close()
    assert row["status"] == "published"
    assert "ig_123" in (row["post_ids_json"] or "")


def test_publish_collab_missing_edit_succeeds(seeded_run, db_path, patched_settings, monkeypatch):
    _set_approval_status(db_path, seeded_run, "approved")
    _patch_postiz(monkeypatch)
    fake_ig = _patch_ig(
        monkeypatch,
        verify_results=[False, True],
        edit_result={"success": True},
    )
    _patch_telegram(monkeypatch)

    out = _run(pub.publish_action(seeded_run))
    assert out["ok"] is True
    assert out["collab_ok"] is True
    fake_ig.add_collab_by_edit.assert_called_once()


def test_publish_collab_missing_edit_fails_recreate_succeeds(
    seeded_run, db_path, patched_settings, monkeypatch
):
    _set_approval_status(db_path, seeded_run, "approved")
    _patch_postiz(monkeypatch)
    fake_ig = _patch_ig(
        monkeypatch,
        verify_results=[False],
        edit_result=None,
        recreate_result={"ok": True, "container_id": "c2", "media": {"id": "m2"}},
    )
    _patch_telegram(monkeypatch)

    out = _run(pub.publish_action(seeded_run))
    assert out["ok"] is True
    assert out["collab_ok"] is True
    assert out["post_ids"]["instagram"] == "m2"
    fake_ig.add_collab_by_recreate.assert_called_once()


def test_publish_postiz_fails_marks_publish_failed(seeded_run, db_path, patched_settings, monkeypatch):
    _set_approval_status(db_path, seeded_run, "approved")
    _patch_postiz(monkeypatch, raise_exc=RuntimeError("postiz down"))
    _patch_telegram(monkeypatch)

    out = _run(pub.publish_action(seeded_run))
    assert out["ok"] is False
    conn = db_module.connect(db_path)
    try:
        row = db_module.get_pipeline_run(conn, seeded_run)
    finally:
        conn.close()
    assert row["status"] == "publish_failed"
    pub._send_telegram.assert_awaited()


def test_publish_postiz_4xx_immediate_failure(seeded_run, db_path, patched_settings, monkeypatch):
    import requests as _r
    _set_approval_status(db_path, seeded_run, "approved")
    _patch_postiz(monkeypatch, raise_exc=_r.HTTPError("4xx"))
    _patch_telegram(monkeypatch)

    out = _run(pub.publish_action(seeded_run))
    assert out["ok"] is False
    conn = db_module.connect(db_path)
    try:
        row = db_module.get_pipeline_run(conn, seeded_run)
    finally:
        conn.close()
    assert row["status"] == "publish_failed"


def test_publish_duplicate_detected(seeded_run, db_path, patched_settings, monkeypatch):
    _set_approval_status(db_path, seeded_run, "approved")
    _patch_postiz(monkeypatch)
    _patch_telegram(monkeypatch)

    fake_dup = types.ModuleType("sidecar.duplicate_guard")
    fake_dup.check = lambda conn, url, title, **kw: {  # type: ignore
        "is_duplicate": True,
        "match_run_id": 1,
        "match_reason": "test",
    }
    monkeypatch.setitem(sys.modules, "sidecar.duplicate_guard", fake_dup)

    out = _run(pub.publish_action(seeded_run))
    assert out["ok"] is False
    assert out.get("duplicate") is True
    conn = db_module.connect(db_path)
    try:
        row = db_module.get_pipeline_run(conn, seeded_run)
    finally:
        conn.close()
    assert row["status"] == "publish_failed_duplicate"


def test_publish_duplicate_guard_allows_non_duplicate(seeded_run, db_path, patched_settings, monkeypatch):
    """Unit 9 — duplicate_guard is now a hard import; non-duplicate proceeds."""
    _set_approval_status(db_path, seeded_run, "approved")
    _patch_postiz(monkeypatch)
    _patch_ig(monkeypatch, verify_results=[True])
    _patch_telegram(monkeypatch)
    # Real duplicate_guard is imported; on an empty DB (other than this run)
    # the current run's own URL won't match a terminal-status row.

    out = _run(pub.publish_action(seeded_run))
    assert out["ok"] is True


def test_publish_action_catches_catastrophic_error(seeded_run, db_path, patched_settings, monkeypatch):
    _set_approval_status(db_path, seeded_run, "approved")

    def boom(*a, **kw):
        raise RuntimeError("kapow")

    monkeypatch.setattr(pub.db_module, "get_pipeline_run_with_captions", boom)
    _patch_telegram(monkeypatch)

    out = _run(pub.publish_action(seeded_run))
    assert out["ok"] is False


def test_publish_run_not_found(patched_settings, monkeypatch):
    _patch_telegram(monkeypatch)
    out = _run(pub.publish_action(99999))
    assert out["ok"] is False


def test_publish_not_approved(seeded_run, db_path, patched_settings, monkeypatch):
    # Approval is still 'pending' from fixture
    _patch_telegram(monkeypatch)
    out = _run(pub.publish_action(seeded_run))
    assert out["ok"] is False


# ---------------------------------------------------------------------------
# auto_approve_action
# ---------------------------------------------------------------------------

def test_auto_approve_pending_flips_and_triggers_publish(seeded_run, db_path, patched_settings, monkeypatch):
    monkeypatch.setattr(pub, "schedule_publish", AsyncMock(return_value={"job_id": "x"}))

    out = _run(pub.auto_approve_action(seeded_run))
    assert out["ok"] is True
    assert out.get("auto_approved") is True

    conn = db_module.connect(db_path)
    try:
        row = db_module.get_approval_by_run_id(conn, seeded_run)
    finally:
        conn.close()
    assert row["status"] == "auto_approved"
    pub.schedule_publish.assert_awaited_once_with(seeded_run)


def test_auto_approve_already_approved_noop(seeded_run, db_path, patched_settings, monkeypatch):
    _set_approval_status(db_path, seeded_run, "approved")
    monkeypatch.setattr(pub, "schedule_publish", AsyncMock())
    out = _run(pub.auto_approve_action(seeded_run))
    assert out.get("noop") is True
    pub.schedule_publish.assert_not_awaited()


def test_auto_approve_already_rejected_noop(seeded_run, db_path, patched_settings, monkeypatch):
    _set_approval_status(db_path, seeded_run, "rejected")
    monkeypatch.setattr(pub, "schedule_publish", AsyncMock())
    out = _run(pub.auto_approve_action(seeded_run))
    assert out.get("noop") is True
    pub.schedule_publish.assert_not_awaited()


# ---------------------------------------------------------------------------
# compute_next_slot
# ---------------------------------------------------------------------------

def test_compute_next_slot_morning():
    now = datetime(2026, 4, 6, 7, 0)
    slot = pub.compute_next_slot(now)
    assert slot == datetime(2026, 4, 6, 9, 0)


def test_compute_next_slot_evening():
    now = datetime(2026, 4, 6, 14, 0)
    assert pub.compute_next_slot(now) == datetime(2026, 4, 6, 19, 0)


def test_compute_next_slot_tomorrow():
    now = datetime(2026, 4, 6, 22, 0)
    assert pub.compute_next_slot(now) == datetime(2026, 4, 7, 9, 0)
