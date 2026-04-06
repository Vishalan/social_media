"""Unit 4 — jobs/run_pipeline.process_pending_runs tests."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import db as db_module  # noqa: E402
from sidecar import pipeline_runner as pr_module  # noqa: E402
from sidecar.jobs import run_pipeline as rp_module  # noqa: E402


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "sidecar.sqlite3")
    db_module.init_db(db_path)
    return db_path


@pytest.fixture
def fake_settings(tmp_db):
    return SimpleNamespace(SIDECAR_DB_PATH=tmp_db)


@pytest.fixture
def patch_settings(fake_settings):
    from sidecar.config import settings_manager as sm
    with patch.object(sm, "_settings", fake_settings), patch.object(
        sm.__class__, "settings", property(lambda self: fake_settings)
    ):
        yield fake_settings


@pytest.fixture(autouse=True)
def _fresh_lock():
    """Reset the module-level pipeline lock between tests."""
    rp_module._pipeline_lock = asyncio.Lock()
    yield


def _seed(tmp_db, title: str) -> int:
    conn = db_module.connect(tmp_db)
    try:
        return db_module.insert_pipeline_run(
            conn,
            topic_title=title,
            topic_url=f"https://x/{title}",
            topic_score=1.0,
            selection_rationale="r",
            source_newsletter_date="2026-04-05",
        )
    finally:
        conn.close()


# --- tests ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_processes_pending_rows_sequentially(patch_settings, monkeypatch):
    id_a = _seed(patch_settings.SIDECAR_DB_PATH, "A")
    id_b = _seed(patch_settings.SIDECAR_DB_PATH, "B")

    order: list[int] = []
    active = {"count": 0, "max": 0}

    async def _fake_run(run_id, timeout_seconds=900):
        active["count"] += 1
        active["max"] = max(active["max"], active["count"])
        await asyncio.sleep(0.01)
        order.append(run_id)
        active["count"] -= 1
        return {"ok": True, "id": run_id}

    monkeypatch.setattr(pr_module, "run_pipeline_for_run", _fake_run)
    monkeypatch.setattr(rp_module.pipeline_runner, "run_pipeline_for_run", _fake_run)

    result = await rp_module.process_pending_runs()
    assert result["processed"] == 2
    assert result["succeeded"] == 2
    assert order == [id_a, id_b]
    assert active["max"] == 1  # never parallel


@pytest.mark.asyncio
async def test_lock_prevents_parallel_runs(patch_settings, monkeypatch):
    _seed(patch_settings.SIDECAR_DB_PATH, "A")
    gate = asyncio.Event()

    async def _fake_run(run_id, timeout_seconds=900):
        await gate.wait()
        return {"ok": True, "id": run_id}

    monkeypatch.setattr(rp_module.pipeline_runner, "run_pipeline_for_run", _fake_run)

    t1 = asyncio.create_task(rp_module.process_pending_runs())
    # Give t1 a tick to acquire the lock.
    await asyncio.sleep(0.01)
    r2 = await rp_module.process_pending_runs()
    assert r2.get("skipped") is True

    gate.set()
    r1 = await t1
    assert r1["processed"] == 1


@pytest.mark.asyncio
async def test_no_pending_rows_returns_zero_processed(patch_settings, monkeypatch):
    async def _boom(*a, **k):  # should not be called
        raise AssertionError("should not be called")

    monkeypatch.setattr(rp_module.pipeline_runner, "run_pipeline_for_run", _boom)
    r = await rp_module.process_pending_runs()
    assert r["processed"] == 0
    assert r["succeeded"] == 0


@pytest.mark.asyncio
async def test_single_row_failure_does_not_block_others(patch_settings, monkeypatch):
    id_a = _seed(patch_settings.SIDECAR_DB_PATH, "A")
    id_b = _seed(patch_settings.SIDECAR_DB_PATH, "B")

    async def _fake_run(run_id, timeout_seconds=900):
        if run_id == id_a:
            return {"ok": False, "id": run_id, "error": "boom"}
        return {"ok": True, "id": run_id}

    monkeypatch.setattr(rp_module.pipeline_runner, "run_pipeline_for_run", _fake_run)

    r = await rp_module.process_pending_runs()
    assert r["processed"] == 2
    assert r["succeeded"] == 1


@pytest.mark.asyncio
async def test_never_raises_on_collaborator_exception(patch_settings, monkeypatch):
    _seed(patch_settings.SIDECAR_DB_PATH, "A")
    _seed(patch_settings.SIDECAR_DB_PATH, "B")

    call_count = {"n": 0}

    async def _fake_run(run_id, timeout_seconds=900):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("collaborator exploded")
        return {"ok": True, "id": run_id}

    monkeypatch.setattr(rp_module.pipeline_runner, "run_pipeline_for_run", _fake_run)

    r = await rp_module.process_pending_runs()  # must not raise
    assert r["processed"] == 2
    assert r["succeeded"] == 1
