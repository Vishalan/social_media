"""Unit 9 — retention job tests."""
from __future__ import annotations

import asyncio
import os
import sys
import time
import types
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import db as db_module  # noqa: E402
from sidecar.jobs import retention as ret  # noqa: E402


@pytest.fixture
def db_path(tmp_path):
    p = str(tmp_path / "sidecar.sqlite3")
    db_module.init_db(p)
    return p


@pytest.fixture
def patched_settings(db_path, monkeypatch):
    fake = types.SimpleNamespace(SIDECAR_DB_PATH=db_path)
    monkeypatch.setattr(
        type(ret.settings_manager),
        "settings",
        property(lambda self: fake),
    )
    return fake


def _seed_run(db_path, video, thumb, audio, created_at=None):
    conn = db_module.connect(db_path)
    try:
        rid = db_module.insert_pipeline_run(
            conn, "t", "u", 1.0, "r", "2026-04-06", status="published"
        )
        db_module.update_pipeline_run_generation_result(
            conn, rid, "published", video, thumb, audio,
            0, 0, 0, 0, None, None, None,
        )
        if created_at is not None:
            conn.execute(
                "UPDATE pipeline_runs SET created_at = ? WHERE id = ?",
                (created_at, rid),
            )
            conn.commit()
    finally:
        conn.close()
    return rid


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _old_iso():
    return (datetime.utcnow() - timedelta(days=30)).isoformat(timespec="seconds")


def _recent_iso():
    return (datetime.utcnow() - timedelta(days=1)).isoformat(timespec="seconds")


def test_prunes_files_older_than_N_days(tmp_path, db_path, patched_settings):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x" * 100)
    t = tmp_path / "t.jpg"
    t.write_bytes(b"y" * 50)
    _seed_run(db_path, str(v), str(t), None, created_at=_old_iso())

    out = _run(ret.run_retention_job(retention_days=14))
    assert str(v) in out["pruned"]
    assert str(t) in out["pruned"]
    assert not v.exists()
    assert not t.exists()


def test_keeps_recent_files(tmp_path, db_path, patched_settings):
    v = tmp_path / "keep.mp4"
    v.write_bytes(b"x")
    _seed_run(db_path, str(v), None, None, created_at=_recent_iso())

    out = _run(ret.run_retention_job(retention_days=14))
    assert v.exists()
    assert str(v) not in out["pruned"]


def test_nulls_db_row_paths_after_prune(tmp_path, db_path, patched_settings):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    rid = _seed_run(db_path, str(v), None, None, created_at=_old_iso())

    _run(ret.run_retention_job(retention_days=14))
    conn = db_module.connect(db_path)
    try:
        row = db_module.get_pipeline_run(conn, rid)
    finally:
        conn.close()
    assert row["video_path"] is None


def test_sets_retention_pruned_at_timestamp(tmp_path, db_path, patched_settings):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    rid = _seed_run(db_path, str(v), None, None, created_at=_old_iso())

    _run(ret.run_retention_job(retention_days=14))
    conn = db_module.connect(db_path)
    try:
        row = db_module.get_pipeline_run(conn, rid)
    finally:
        conn.close()
    assert row["retention_pruned_at"]


def test_missing_file_ok(tmp_path, db_path, patched_settings):
    ghost = str(tmp_path / "ghost.mp4")
    rid = _seed_run(db_path, ghost, None, None, created_at=_old_iso())
    out = _run(ret.run_retention_job(retention_days=14))
    # Does not crash; row still updated
    assert out.get("rows_updated", 0) >= 1
    conn = db_module.connect(db_path)
    try:
        row = db_module.get_pipeline_run(conn, rid)
    finally:
        conn.close()
    assert row["video_path"] is None


def test_bytes_freed_total_correct(tmp_path, db_path, patched_settings):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x" * 200)
    t = tmp_path / "t.jpg"
    t.write_bytes(b"y" * 50)
    _seed_run(db_path, str(v), str(t), None, created_at=_old_iso())

    out = _run(ret.run_retention_job(retention_days=14))
    assert out["bytes_freed"] == 250


def test_never_raises_on_permission_error(tmp_path, db_path, patched_settings, monkeypatch):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    _seed_run(db_path, str(v), None, None, created_at=_old_iso())

    def bad_remove(_path):
        raise PermissionError("nope")

    monkeypatch.setattr(ret.os, "remove", bad_remove)
    # Should not raise
    out = _run(ret.run_retention_job(retention_days=14))
    assert isinstance(out, dict)
