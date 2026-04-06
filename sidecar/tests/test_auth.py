"""Unit 8 SHELL — auth (signed cookie sessions)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import auth as auth_module  # noqa: E402
from sidecar import db as db_module  # noqa: E402
from sidecar.app import app  # noqa: E402
from sidecar.config import settings_manager, SettingsManager  # noqa: E402


REQUIRED_ENV = {
    "ANTHROPIC_API_KEY": "test-anthropic",
    "SIDECAR_ADMIN_PASSWORD": "correct-horse",
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
def client(env_setup):
    return TestClient(app)


def test_login_with_correct_password_sets_cookie(client):
    r = client.post(
        "/login",
        data={"username": "admin", "password": "correct-horse"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert auth_module.COOKIE_NAME in r.cookies


def test_login_with_wrong_password_returns_401(client):
    r = client.post(
        "/login",
        data={"username": "admin", "password": "wrong"},
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_logout_clears_cookie(client):
    # First login
    client.post(
        "/login", data={"username": "admin", "password": "correct-horse"},
        follow_redirects=False,
    )
    r = client.post("/logout", follow_redirects=False)
    assert r.status_code == 303
    # The Set-Cookie should be expiring the cookie
    set_cookie = r.headers.get("set-cookie", "")
    assert auth_module.COOKIE_NAME in set_cookie


def test_protected_route_without_cookie_redirects_to_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_protected_route_with_expired_cookie_redirects_to_login(client, monkeypatch):
    # Build a token then verify with a 0-second max-age, simulating expiry.
    token = auth_module.make_session_token()
    monkeypatch.setattr(auth_module, "COOKIE_MAX_AGE", 0)
    time.sleep(1.1)
    client.cookies.set(auth_module.COOKIE_NAME, token)
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_cookie_is_signed_not_plain(client):
    token = auth_module.make_session_token()
    # Plain "admin" must NOT verify; only the signed form does.
    assert not auth_module.verify_session_token("admin")
    assert auth_module.verify_session_token(token)
    # And it must contain a signature separator
    assert "." in token
