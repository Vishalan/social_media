"""Unit 8 SHELL — dashboard routes."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import db as db_module  # noqa: E402
from sidecar import auth as auth_module  # noqa: E402
from sidecar.app import app  # noqa: E402
from sidecar.config import settings_manager, Settings, SettingsManager  # noqa: E402


REQUIRED_ENV = {
    "ANTHROPIC_API_KEY": "test-anthropic",
    "SIDECAR_ADMIN_PASSWORD": "test-admin-pw",
}


def _write_env(path: Path, data: dict) -> None:
    path.write_text("\n".join(f"{k}={v}" for k, v in data.items()) + "\n")


@pytest.fixture
def env_setup(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    db_path = tmp_path / "sidecar.sqlite3"
    _write_env(env_path, {**REQUIRED_ENV, "SIDECAR_DB_PATH": str(db_path)})
    mgr = SettingsManager(env_path=str(env_path))
    mgr.load()
    monkeypatch.setattr(settings_manager, "_settings", mgr.settings)
    monkeypatch.setattr(settings_manager, "env_path", str(env_path))
    db_module.init_db(str(db_path))
    auth_module.reset_signer_for_tests()
    yield {"env_path": env_path, "db_path": db_path, "tmp_path": tmp_path}


@pytest.fixture
def client(env_setup):
    return TestClient(app)


@pytest.fixture
def authed_client(env_setup):
    c = TestClient(app)
    token = auth_module.make_session_token()
    c.cookies.set(auth_module.COOKIE_NAME, token)
    return c


def test_summary_page_renders_without_auth_redirect_when_logged_in(authed_client):
    r = authed_client.get("/")
    assert r.status_code == 200
    assert "Summary" in r.text


def test_summary_page_redirects_to_login_when_unauthenticated(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_runs_page_renders_empty_state_when_no_runs(authed_client):
    r = authed_client.get("/runs")
    assert r.status_code == 200
    assert "No runs yet" in r.text


def test_runs_page_renders_rows_when_runs_exist(authed_client, env_setup):
    conn = db_module.connect(str(env_setup["db_path"]))
    try:
        db_module.insert_pipeline_run(
            conn,
            topic_title="A test topic",
            topic_url="https://example.com",
            topic_score=0.9,
            selection_rationale="reasons",
            source_newsletter_date="2026-04-06",
        )
    finally:
        conn.close()
    r = authed_client.get("/runs")
    assert r.status_code == 200
    assert "A test topic" in r.text


def test_runs_page_returns_partial_when_htmx_request(authed_client, env_setup):
    conn = db_module.connect(str(env_setup["db_path"]))
    try:
        db_module.insert_pipeline_run(
            conn, "Topic X", "https://x", 0.5, "rationale", "2026-04-06"
        )
    finally:
        conn.close()
    r = authed_client.get("/runs", headers={"HX-Request": "true"})
    assert r.status_code == 200
    # Partial: must NOT contain the base layout sidebar
    assert "<aside class=\"sidebar\">" not in r.text
    assert "Topic X" in r.text


def test_run_detail_page_renders(authed_client, env_setup):
    conn = db_module.connect(str(env_setup["db_path"]))
    try:
        rid = db_module.insert_pipeline_run(
            conn, "Detail topic", "https://d", 0.7, "why", "2026-04-06"
        )
        db_module.set_captions(conn, rid, {"twitter": "hello"})
    finally:
        conn.close()
    r = authed_client.get(f"/runs/{rid}")
    assert r.status_code == 200
    assert "Detail topic" in r.text
    assert "twitter" in r.text


def test_run_detail_page_404_when_missing(authed_client):
    r = authed_client.get("/runs/99999")
    assert r.status_code == 404


def test_approvals_page_renders_pending_approvals(authed_client, env_setup):
    conn = db_module.connect(str(env_setup["db_path"]))
    try:
        rid = db_module.insert_pipeline_run(
            conn, "Approval topic", "https://a", 0.6, "why", "2026-04-06"
        )
        db_module.create_approval(conn, rid, telegram_message_id=42)
    finally:
        conn.close()
    r = authed_client.get("/approvals")
    assert r.status_code == 200
    assert "Approval topic" in r.text
    assert "Approve" in r.text


def test_settings_page_masks_secrets(authed_client):
    r = authed_client.get("/settings")
    assert r.status_code == 200
    # The admin password we set was "test-admin-pw" — it must NOT appear.
    assert "test-admin-pw" not in r.text
    assert "***" in r.text


def test_login_page_renders_without_auth(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "Sign in" in r.text or "password" in r.text.lower()
