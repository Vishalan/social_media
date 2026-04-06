"""Unit 9 — weekly cost report tests."""
from __future__ import annotations

import asyncio
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import db as db_module  # noqa: E402
from sidecar.jobs import cost_report as cr  # noqa: E402


@pytest.fixture
def db_path(tmp_path):
    p = str(tmp_path / "sidecar.sqlite3")
    db_module.init_db(p)
    return p


@pytest.fixture
def patched(db_path, monkeypatch):
    fake = types.SimpleNamespace(
        SIDECAR_DB_PATH=db_path, TELEGRAM_CHAT_ID="123"
    )
    monkeypatch.setattr(
        type(cr.settings_manager),
        "settings",
        property(lambda self: fake),
    )
    return fake


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _seed(db_path, costs, days_ago):
    conn = db_module.connect(db_path)
    try:
        rid = db_module.insert_pipeline_run(
            conn, "t", "u", 1.0, "r", "2026-04-06", status="published"
        )
        db_module.update_pipeline_run_generation_result(
            conn, rid, "published", None, None, None,
            costs.get("sonnet", 0),
            costs.get("haiku", 0),
            costs.get("elevenlabs", 0),
            costs.get("veed", 0),
            None, None, None,
        )
        if days_ago is not None:
            ca = (datetime.utcnow() - timedelta(days=days_ago)).isoformat(timespec="seconds")
            conn.execute("UPDATE pipeline_runs SET created_at = ? WHERE id = ?", (ca, rid))
            conn.commit()
    finally:
        conn.close()


def test_sums_last_7_days_costs_correctly(patched, monkeypatch):
    _seed(patched.SIDECAR_DB_PATH, {"sonnet": 0.1, "elevenlabs": 1.0}, days_ago=1)
    _seed(patched.SIDECAR_DB_PATH, {"sonnet": 0.2, "veed": 2.0}, days_ago=3)
    monkeypatch.setattr(cr, "_send_telegram", AsyncMock())
    out = _run(cr.send_weekly_cost_report())
    assert out["ok"] is True
    s = out["summary"]
    assert abs(s["sonnet"] - 0.3) < 1e-6
    assert abs(s["elevenlabs"] - 1.0) < 1e-6
    assert abs(s["veed"] - 2.0) < 1e-6
    assert abs(s["total"] - 3.3) < 1e-6


def test_projected_monthly_formula(patched, monkeypatch):
    _seed(patched.SIDECAR_DB_PATH, {"veed": 7.0}, days_ago=1)
    monkeypatch.setattr(cr, "_send_telegram", AsyncMock())
    out = _run(cr.send_weekly_cost_report())
    assert abs(out["summary"]["projected_monthly"] - 30.0) < 1e-6


def test_empty_week_produces_valid_report(patched, monkeypatch):
    monkeypatch.setattr(cr, "_send_telegram", AsyncMock())
    out = _run(cr.send_weekly_cost_report())
    assert out["ok"] is True
    assert out["summary"]["total"] == 0
    assert out["summary"]["projected_monthly"] == 0
    assert out["summary"]["videos"] == 0


def test_sends_telegram_message(patched, monkeypatch):
    _seed(patched.SIDECAR_DB_PATH, {"sonnet": 0.5}, days_ago=2)
    tg = AsyncMock()
    monkeypatch.setattr(cr, "_send_telegram", tg)
    out = _run(cr.send_weekly_cost_report())
    tg.assert_awaited_once()
    msg = tg.call_args.args[0]
    assert "Weekly cost report" in msg
    assert "Sonnet" in msg
