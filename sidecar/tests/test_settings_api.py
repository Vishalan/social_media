"""Unit 8 SHELL — settings write API."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import db as db_module  # noqa: E402
from sidecar import auth as auth_module  # noqa: E402
from sidecar.app import app  # noqa: E402
from sidecar.config import settings_manager, SettingsManager  # noqa: E402
from sidecar.routes import settings_api as settings_api_mod  # noqa: E402


REQUIRED_ENV = {
    "ANTHROPIC_API_KEY": "old-anthropic",
    "SIDECAR_ADMIN_PASSWORD": "old-admin-pw",
    "POSTIZ_API_KEY": "old-postiz",
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
    yield {"env_path": env_path, "db_path": db_path}


@pytest.fixture
def authed_client(env_setup):
    c = TestClient(app)
    c.cookies.set(auth_module.COOKIE_NAME, auth_module.make_session_token())
    return c


class _StubDocker:
    def __init__(self):
        self.calls: list[list[str]] = []

    def restart_containers(self, names):
        self.calls.append(list(names))
        return {"restarted": list(names), "rejected": [], "errors": []}


def test_settings_update_writes_env_atomically(authed_client, env_setup, monkeypatch):
    seen = {}
    real_replace = __import__("os").replace

    def fake_replace(src, dst):
        seen["src"] = str(src)
        seen["dst"] = str(dst)
        return real_replace(src, dst)

    monkeypatch.setattr("sidecar.routes.settings_api.os.replace", fake_replace)
    monkeypatch.setattr(settings_api_mod, "docker_manager", _StubDocker())

    r = authed_client.post("/settings/update", data={"ANTHROPIC_API_KEY": "new-key"})
    assert r.status_code == 200
    assert seen["src"].endswith(".env.new")
    assert seen["dst"].endswith(".env")
    # File now contains the new value
    body = env_setup["env_path"].read_text()
    assert "ANTHROPIC_API_KEY=new-key" in body


def test_settings_update_rejects_invalid_values(authed_client, env_setup, monkeypatch):
    monkeypatch.setattr(settings_api_mod, "docker_manager", _StubDocker())
    r = authed_client.post("/settings/update", data={"ANTHROPIC_API_KEY": "  "})
    assert r.status_code == 400


def test_settings_update_restarts_only_affected_containers(authed_client, env_setup, monkeypatch):
    stub = _StubDocker()
    monkeypatch.setattr(settings_api_mod, "docker_manager", stub)
    # Change a Postiz key (should restart) and a sidecar key (should NOT)
    r = authed_client.post(
        "/settings/update",
        data={"POSTIZ_API_KEY": "new-postiz", "ANTHROPIC_API_KEY": "new-anth"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "POSTIZ_API_KEY" in body["updated"]
    assert "ANTHROPIC_API_KEY" in body["updated"]
    assert body["restarted"] == ["postiz"]
    # Confirm the docker stub only got asked about postiz, never sidecar
    assert stub.calls == [["postiz"]]


def test_settings_update_NEVER_restarts_sidecar_itself(authed_client, env_setup, monkeypatch):
    """Critical safety test: even if a future map entry pointed at the sidecar
    container, the affected_containers helper must filter it out."""
    stub = _StubDocker()
    monkeypatch.setattr(settings_api_mod, "docker_manager", stub)
    # Inject a poisoned map entry
    poisoned = dict(settings_api_mod.KEY_TO_CONTAINERS)
    poisoned["ANTHROPIC_API_KEY"] = ("commoncreed_sidecar", "postiz")
    monkeypatch.setattr(settings_api_mod, "KEY_TO_CONTAINERS", poisoned)
    r = authed_client.post(
        "/settings/update",
        data={"ANTHROPIC_API_KEY": "new-anth"},
    )
    assert r.status_code == 200
    body = r.json()
    # postiz still gets restarted, sidecar never appears anywhere
    for call in stub.calls:
        assert "commoncreed_sidecar" not in call
    assert "commoncreed_sidecar" not in body["restarted"]


def test_settings_update_writes_audit_log_row(authed_client, env_setup, monkeypatch):
    monkeypatch.setattr(settings_api_mod, "docker_manager", _StubDocker())
    r = authed_client.post("/settings/update", data={"ANTHROPIC_API_KEY": "another-new"})
    assert r.status_code == 200
    conn = db_module.connect(str(env_setup["db_path"]))
    try:
        rows = db_module.get_settings_audit(conn)
    finally:
        conn.close()
    keys = [row["key"] for row in rows]
    assert "ANTHROPIC_API_KEY" in keys
    # Audit must NEVER store the actual secret
    for row in rows:
        assert row["value"] != "another-new"
