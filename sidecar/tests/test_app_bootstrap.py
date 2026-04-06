"""Unit 2 bootstrap tests — pure-Python, no external services."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ensure project root is importable so `sidecar.*` resolves when tests run
# from the project root.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import db as db_module  # noqa: E402
from sidecar.app import app  # noqa: E402
from sidecar.config import SettingsManager, load_settings  # noqa: E402
from sidecar.routes import health as health_routes  # noqa: E402


REQUIRED_ENV = {
    "ANTHROPIC_API_KEY": "changeme-test-anthropic",
    "SIDECAR_ADMIN_PASSWORD": "changeme-test-admin",
}


def _write_env(path: Path, data: dict) -> None:
    path.write_text("\n".join(f"{k}={v}" for k, v in data.items()) + "\n")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def all_good(monkeypatch):
    monkeypatch.setitem(health_routes.checks, "pipeline_code_visible", lambda: True)
    monkeypatch.setitem(health_routes.checks, "env_readable", lambda: True)
    monkeypatch.setitem(health_routes.checks, "db_writable", lambda: True)
    monkeypatch.setitem(health_routes.checks, "docker_socket_accessible", lambda: True)


# --- /health endpoint ------------------------------------------------------

def test_health_endpoint_returns_200_when_all_good(client, all_good):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["version"] == "0.1.0"
    for k in ("pipeline_code_visible", "env_readable", "db_writable", "docker_socket_accessible"):
        assert body[k] is True


def test_health_endpoint_returns_503_when_pipeline_code_missing(client, all_good, monkeypatch):
    monkeypatch.setitem(health_routes.checks, "pipeline_code_visible", lambda: False)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["ok"] is False
    assert r.json()["pipeline_code_visible"] is False


def test_health_endpoint_returns_503_when_env_not_readable(client, all_good, monkeypatch):
    monkeypatch.setitem(health_routes.checks, "env_readable", lambda: False)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["env_readable"] is False


def test_health_endpoint_returns_503_when_db_not_writable(client, all_good, monkeypatch):
    monkeypatch.setitem(health_routes.checks, "db_writable", lambda: False)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["db_writable"] is False


def test_health_endpoint_returns_503_when_docker_socket_inaccessible(client, all_good, monkeypatch):
    monkeypatch.setitem(health_routes.checks, "docker_socket_accessible", lambda: False)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["docker_socket_accessible"] is False


# --- db bootstrap ----------------------------------------------------------

def test_db_schema_bootstraps_three_tables_idempotent(tmp_path):
    db_path = str(tmp_path / "sidecar.sqlite3")
    db_module.init_db(db_path)
    db_module.init_db(db_path)  # second call must not raise
    tables = set(db_module.list_tables(db_path))
    assert {"pipeline_runs", "approvals", "settings"}.issubset(tables)


# --- config loader ---------------------------------------------------------

def test_config_loads_from_env_file(tmp_path):
    env_path = tmp_path / ".env"
    _write_env(env_path, {
        **REQUIRED_ENV,
        "POSTIZ_API_KEY": "changeme-postiz-123",
        "PIPELINE_RETENTION_DAYS": "21",
    })
    s = load_settings(str(env_path))
    assert s.ANTHROPIC_API_KEY == "changeme-test-anthropic"
    assert s.SIDECAR_ADMIN_PASSWORD == "changeme-test-admin"
    assert s.POSTIZ_API_KEY == "changeme-postiz-123"
    assert s.PIPELINE_RETENTION_DAYS == 21  # typed int coercion


def test_config_raises_on_missing_required_fields(tmp_path):
    env_path = tmp_path / ".env"
    _write_env(env_path, {"POSTIZ_API_KEY": "changeme-only"})
    with pytest.raises(ValueError) as ei:
        load_settings(str(env_path))
    msg = str(ei.value)
    assert "ANTHROPIC_API_KEY" in msg or "SIDECAR_ADMIN_PASSWORD" in msg


def test_config_reload_picks_up_changes(tmp_path):
    env_path = tmp_path / ".env"
    _write_env(env_path, {**REQUIRED_ENV, "PIPELINE_RETENTION_DAYS": "7"})
    mgr = SettingsManager(env_path=str(env_path))
    mgr.load()
    assert mgr.settings.PIPELINE_RETENTION_DAYS == 7
    _write_env(env_path, {**REQUIRED_ENV, "PIPELINE_RETENTION_DAYS": "30"})
    mgr.reload()
    assert mgr.settings.PIPELINE_RETENTION_DAYS == 30


def test_config_raises_on_missing_file(tmp_path):
    missing = tmp_path / "nope.env"
    with pytest.raises(FileNotFoundError):
        load_settings(str(missing))
