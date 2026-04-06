"""Unit 9 — health ping tests."""
from __future__ import annotations

import asyncio
import os
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
from sidecar.jobs import health_ping as hp  # noqa: E402


@pytest.fixture
def db_path(tmp_path):
    p = str(tmp_path / "sidecar.sqlite3")
    db_module.init_db(p)
    return p


@pytest.fixture
def patched(db_path, monkeypatch):
    fake = types.SimpleNamespace(
        SIDECAR_DB_PATH=db_path,
        POSTIZ_BASE_URL="http://postiz",
        POSTIZ_API_KEY="k",
        TELEGRAM_CHAT_ID="123",
        GMAIL_OAUTH_PATH="/nope",
        ANTHROPIC_API_KEY="a",
    )
    monkeypatch.setattr(
        type(hp.settings_manager),
        "settings",
        property(lambda self: fake),
    )
    # reset rate-limit dict
    hp._LAST_ALERT_AT.clear()
    monkeypatch.delenv("HEALTH_PING_ANTHROPIC", raising=False)
    return fake


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _patch_all_healthy(monkeypatch):
    monkeypatch.setattr(hp, "_ping_postiz", AsyncMock(return_value=True))
    monkeypatch.setattr(hp, "_ping_telegram", AsyncMock(return_value=True))
    monkeypatch.setattr(hp, "_ping_gmail", AsyncMock(return_value=True))
    monkeypatch.setattr(hp, "_ping_anthropic", AsyncMock(return_value=True))


def test_all_services_healthy(patched, monkeypatch):
    _patch_all_healthy(monkeypatch)
    alert = AsyncMock()
    monkeypatch.setattr(hp, "_alert", alert)
    out = _run(hp.run_health_pings())
    assert out["postiz"] is True
    assert out["telegram"] is True
    assert out["gmail"] is True
    alert.assert_not_called()


def test_postiz_down_sends_alert(patched, monkeypatch):
    monkeypatch.setattr(hp, "_ping_postiz", AsyncMock(return_value=False))
    monkeypatch.setattr(hp, "_ping_telegram", AsyncMock(return_value=True))
    monkeypatch.setattr(hp, "_ping_gmail", AsyncMock(return_value=True))
    alert = AsyncMock()
    monkeypatch.setattr(hp, "_alert", alert)
    _run(hp.run_health_pings())
    # First positional arg is service name
    services_alerted = [c.args[0] for c in alert.call_args_list]
    assert "postiz" in services_alerted
    # Verify to_telegram=True for postiz
    for c in alert.call_args_list:
        if c.args[0] == "postiz":
            assert c.kwargs.get("to_telegram", True) is True


def test_telegram_down_alert_goes_to_logs_not_telegram(patched, monkeypatch):
    monkeypatch.setattr(hp, "_ping_postiz", AsyncMock(return_value=True))
    monkeypatch.setattr(hp, "_ping_telegram", AsyncMock(return_value=False))
    monkeypatch.setattr(hp, "_ping_gmail", AsyncMock(return_value=True))
    alert = AsyncMock()
    monkeypatch.setattr(hp, "_alert", alert)
    _run(hp.run_health_pings())
    for c in alert.call_args_list:
        if c.args[0] == "telegram":
            assert c.kwargs.get("to_telegram") is False
            return
    pytest.fail("telegram alert not fired")


def test_rate_limit_suppresses_second_alert_within_hour(patched, monkeypatch):
    """Call _alert twice in quick succession; second should not send."""
    sent = []

    async def fake_send(chat_id, text):
        sent.append(text)

    bot = MagicMock()
    bot.bot = MagicMock()
    bot.bot.send_message = AsyncMock(side_effect=fake_send)

    fake_app = types.SimpleNamespace(state=types.SimpleNamespace(telegram_bot=bot))
    monkeypatch.setitem(sys.modules, "sidecar.app", types.SimpleNamespace(app=fake_app))

    _run(hp._alert("postiz", "down", to_telegram=True))
    _run(hp._alert("postiz", "still down", to_telegram=True))
    assert len(sent) == 1


def test_rate_limit_resets_after_hour(patched, monkeypatch):
    sent = []

    async def fake_send(chat_id, text):
        sent.append(text)

    bot = MagicMock()
    bot.bot = MagicMock()
    bot.bot.send_message = AsyncMock(side_effect=fake_send)
    fake_app = types.SimpleNamespace(state=types.SimpleNamespace(telegram_bot=bot))
    monkeypatch.setitem(sys.modules, "sidecar.app", types.SimpleNamespace(app=fake_app))

    _run(hp._alert("postiz", "down", to_telegram=True))
    # Backdate
    hp._LAST_ALERT_AT["postiz"] = datetime.utcnow() - timedelta(hours=2)
    _run(hp._alert("postiz", "still down", to_telegram=True))
    assert len(sent) == 2


def test_anthropic_ping_skipped_by_default(patched, monkeypatch):
    called = AsyncMock(return_value=True)
    monkeypatch.setattr(hp, "_ping_postiz", AsyncMock(return_value=True))
    monkeypatch.setattr(hp, "_ping_telegram", AsyncMock(return_value=True))
    monkeypatch.setattr(hp, "_ping_gmail", AsyncMock(return_value=True))
    monkeypatch.setattr(hp, "_ping_anthropic", called)
    out = _run(hp.run_health_pings())
    assert out.get("anthropic") == "skipped"
    called.assert_not_called()


def test_records_last_success_timestamps_in_settings_table(patched, monkeypatch):
    _patch_all_healthy(monkeypatch)
    monkeypatch.setattr(hp, "_alert", AsyncMock())
    _run(hp.run_health_pings())

    conn = db_module.connect(patched.SIDECAR_DB_PATH)
    try:
        v = db_module.get_settings_value(conn, "health_ping_last_success_postiz", "")
    finally:
        conn.close()
    assert v
    # ISO-format-ish
    assert "T" in v
