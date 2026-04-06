"""Unit 7 — wired approvals API tests via TestClient."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import db as db_module  # noqa: E402
from sidecar import auth as auth_module  # noqa: E402
from sidecar.app import app  # noqa: E402
from sidecar.config import settings_manager, SettingsManager  # noqa: E402


REQ = {"ANTHROPIC_API_KEY": "x", "SIDECAR_ADMIN_PASSWORD": "pw"}


@pytest.fixture
def env_setup(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    db = tmp_path / "sidecar.sqlite3"
    env.write_text(
        "\n".join(f"{k}={v}" for k, v in {**REQ, "SIDECAR_DB_PATH": str(db)}.items())
        + "\n"
    )
    mgr = SettingsManager(env_path=str(env))
    mgr.load()
    monkeypatch.setattr(settings_manager, "_settings", mgr.settings)
    monkeypatch.setattr(settings_manager, "env_path", str(env))
    db_module.init_db(str(db))
    auth_module.reset_signer_for_tests()
    return {"db": str(db)}


@pytest.fixture
def client(env_setup):
    c = TestClient(app)
    c.cookies.set(auth_module.COOKIE_NAME, auth_module.make_session_token())
    return c


def _seed(db_path):
    conn = db_module.connect(db_path)
    try:
        run_id = db_module.insert_pipeline_run(
            conn, "T", "https://x", 0.5, "r", "2026-04-06"
        )
        db_module.set_captions(conn, run_id, {"instagram": {"caption": "old"}})
        approval_id = db_module.create_approval(conn, run_id, telegram_message_id=1)
    finally:
        conn.close()
    return run_id, approval_id


def test_approve_writes_db_and_calls_schedule_publish(env_setup, client):
    run_id, approval_id = _seed(env_setup["db"])
    with patch(
        "sidecar.jobs.publish.schedule_publish",
        new=AsyncMock(return_value={"job_id": "j1"}),
    ) as mock_sched:
        r = client.post(f"/approvals/{approval_id}/approve")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["run_id"] == run_id

    conn = db_module.connect(env_setup["db"])
    try:
        row = db_module.get_approval_by_run_id(conn, run_id)
    finally:
        conn.close()
    assert row["status"] == "approved"
    mock_sched.assert_awaited_once_with(run_id)


def test_reject_writes_db(env_setup, client):
    run_id, approval_id = _seed(env_setup["db"])
    r = client.post(f"/approvals/{approval_id}/reject")
    assert r.status_code == 200
    conn = db_module.connect(env_setup["db"])
    try:
        row = db_module.get_approval_by_run_id(conn, run_id)
    finally:
        conn.close()
    assert row["status"] == "rejected"


def test_reschedule_writes_proposed_time(env_setup, client):
    run_id, approval_id = _seed(env_setup["db"])
    r = client.post(
        f"/approvals/{approval_id}/reschedule",
        data={"proposed_time": "2026-04-08T19:00:00"},
    )
    assert r.status_code == 200
    conn = db_module.connect(env_setup["db"])
    try:
        row = db_module.get_approval_by_run_id(conn, run_id)
    finally:
        conn.close()
    assert row["status"] == "rescheduled"
    assert row["proposed_time"] == "2026-04-08T19:00:00"


def test_edit_caption_updates_captions_json(env_setup, client):
    run_id, approval_id = _seed(env_setup["db"])
    r = client.post(
        f"/approvals/{approval_id}/edit_caption",
        data={"caption": "Brand new"},
    )
    assert r.status_code == 200
    conn = db_module.connect(env_setup["db"])
    try:
        run = db_module.get_pipeline_run(conn, run_id)
    finally:
        conn.close()
    captions = json.loads(run["captions_json"])
    assert captions["instagram"]["caption"] == "Brand new"


def test_approve_404_when_missing(env_setup, client):
    r = client.post("/approvals/9999/approve")
    assert r.status_code == 404
