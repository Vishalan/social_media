"""Autopilot must pick top-N images AND top-N videos independently.

Pre-split behavior was a single leaderboard that always starved videos
(images get ~3-10x more Reddit karma on the same sub). With
``MEME_VIDEO_DAILY_AUTO_APPROVE_COUNT`` and a per-media-type split,
images and videos land on each autopilot tick, not just whichever type
won the karma race that day.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import db as db_module  # noqa: E402
from sidecar.jobs import meme_flow as mf  # noqa: E402


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    db_module.init_db(str(db_path))
    return str(db_path)


def _insert_candidate(
    db_path: str,
    *,
    cand_id: int,
    media_type: str,
    score: int,
    status: str = "pending_review",
) -> None:
    conn = db_module.connect(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO meme_candidates (
                    id, source, source_url, author_handle, title,
                    media_url, media_type, engagement_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cand_id,
                    "reddit_programmerhumor",
                    f"https://reddit.com/r/ProgrammerHumor/abc{cand_id}",
                    "testuser",
                    f"title {cand_id}",
                    f"https://example.com/{cand_id}",
                    media_type,
                    json.dumps({"score": score}),
                    status,
                ),
            )
    finally:
        conn.close()


def _make_settings(db_path: str, img_count=1, vid_count=1, enabled=True):
    return SimpleNamespace(
        SIDECAR_DB_PATH=db_path,
        MEME_AUTO_APPROVE_ENABLED=enabled,
        MEME_DAILY_AUTO_APPROVE_COUNT=img_count,
        MEME_VIDEO_DAILY_AUTO_APPROVE_COUNT=vid_count,
    )


def test_autopilot_picks_top_image_and_top_video_together(temp_db, monkeypatch):
    """Top-scoring image AND top-scoring video both get picked."""
    _insert_candidate(temp_db, cand_id=10, media_type="image", score=5000)
    _insert_candidate(temp_db, cand_id=11, media_type="image", score=100)
    _insert_candidate(temp_db, cand_id=20, media_type="video", score=800)
    _insert_candidate(temp_db, cand_id=21, media_type="video", score=200)

    mf.settings_manager._settings = _make_settings(temp_db)
    publish_calls: list[int] = []

    async def fake_publish(cid):
        publish_calls.append(cid)
        return {"ok": True}

    with patch.object(mf, "publish_meme_candidate", fake_publish):
        result = asyncio.run(mf.meme_auto_approve_action())

    assert result["ok"] is True
    # One image (cand 10) + one video (cand 20) picked.
    assert set(result["picked"]) == {10, 20}
    # The low-score image (11) and low-score video (21) are skipped.
    assert set(result["skipped"]) == {11, 21}
    assert set(publish_calls) == {10, 20}


def test_autopilot_when_only_images_available(temp_db, monkeypatch):
    """If the pool has no videos, images still auto-publish."""
    _insert_candidate(temp_db, cand_id=30, media_type="image", score=1000)
    _insert_candidate(temp_db, cand_id=31, media_type="image", score=500)

    mf.settings_manager._settings = _make_settings(temp_db)

    async def fake_publish(cid):
        return {"ok": True}

    with patch.object(mf, "publish_meme_candidate", fake_publish):
        result = asyncio.run(mf.meme_auto_approve_action())

    assert result["picked"] == [30]
    assert result["skipped"] == [31]


def test_autopilot_when_only_videos_available(temp_db, monkeypatch):
    """If the pool has no images, videos still auto-publish."""
    _insert_candidate(temp_db, cand_id=40, media_type="video", score=900)
    _insert_candidate(temp_db, cand_id=41, media_type="gif", score=400)

    mf.settings_manager._settings = _make_settings(temp_db, img_count=1, vid_count=1)

    async def fake_publish(cid):
        return {"ok": True}

    with patch.object(mf, "publish_meme_candidate", fake_publish):
        result = asyncio.run(mf.meme_auto_approve_action())

    # Only 1 video picked (either cand 40 or 41 depending on tiebreak;
    # score 900 > 400 so cand 40 wins). GIF counts as video (per _is_video_row).
    assert result["picked"] == [40]
    assert result["skipped"] == [41]


def test_autopilot_respects_zero_video_count(temp_db, monkeypatch):
    """Setting MEME_VIDEO_DAILY_AUTO_APPROVE_COUNT=0 disables video autopilot."""
    _insert_candidate(temp_db, cand_id=50, media_type="image", score=100)
    _insert_candidate(temp_db, cand_id=51, media_type="video", score=1_000_000)

    mf.settings_manager._settings = _make_settings(temp_db, img_count=1, vid_count=0)

    async def fake_publish(cid):
        return {"ok": True}

    with patch.object(mf, "publish_meme_candidate", fake_publish):
        result = asyncio.run(mf.meme_auto_approve_action())

    # Even though cand 51 has the highest score overall, video count=0 skips it.
    assert result["picked"] == [50]
    assert result["skipped"] == [51]


def test_autopilot_no_pending_returns_clean(temp_db, monkeypatch):
    mf.settings_manager._settings = _make_settings(temp_db)
    result = asyncio.run(mf.meme_auto_approve_action())
    assert result["ok"] is True
    assert result.get("picked") == 0
    assert "no pending" in result["reason"]
