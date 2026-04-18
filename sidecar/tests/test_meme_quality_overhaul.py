"""Tests for the meme-quality-overhaul plan (4 units).

Unit 1 — Haiku scoring + >= 7 humor/relevance thresholds
Unit 2 — Reduced surface limits (2 img + 2 vid per run)
Unit 3 — Cross-run dedup (48h lookback, 0.7 Jaccard on titles)
Unit 4 — Additional Reddit sources (cscareerquestions, webdev,
         DataIsBeautiful, homelab, MechanicalKeyboards)

All tests use an in-memory-style temp sqlite file (no network, no real
Anthropic API). Scoring is exercised via monkeypatching
``_score_candidates_batch`` to return deterministic pairs.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar import db as db_module  # noqa: E402
from sidecar.config import Settings  # noqa: E402
from sidecar.jobs import meme_flow  # noqa: E402
from sidecar.meme_sources import _REGISTRY  # noqa: E402
from sidecar.meme_sources.reddit_memes import _DEFAULT_SUBREDDITS  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_conn(tmp_path):
    p = str(tmp_path / "meme.sqlite3")
    db_module.init_db(p)
    c = db_module.connect(p)
    yield c
    c.close()


@pytest.fixture
def db_path(tmp_path):
    p = str(tmp_path / "meme.sqlite3")
    db_module.init_db(p)
    return p


def _make_settings(db_path: str, **overrides):
    """Build a Settings-like namespace with sensible defaults for the trigger."""
    base = {
        "ANTHROPIC_API_KEY": "test-key",
        "TELEGRAM_CHAT_ID": "",  # disable actual Telegram send
        "SIDECAR_DB_PATH": db_path,
        "MEME_MIN_HUMOR_SCORE": 7,
        "MEME_MIN_RELEVANCE_SCORE": 7,
        "MEME_DAILY_SURFACE_LIMIT": 2,
        "MEME_VIDEO_DAILY_SURFACE_LIMIT": 2,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _candidate(
    i: int,
    *,
    media_type: str = "image",
    score: int = 1000,
    title: str | None = None,
):
    return {
        "source": "reddit_programmerhumor",
        "source_url": f"https://reddit.com/r/ProgrammerHumor/comments/{i}",
        "author_handle": f"u/user{i}",
        "title": title if title is not None else f"Candidate {i} title",
        "media_url": f"https://i.redd.it/{i}.jpg",
        "media_type": media_type,
        "engagement": {"score": score, "comments": 10, "subreddit": "ProgrammerHumor"},
        "published_at": "2026-04-16T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# Unit 1 — thresholds default to 7 and filter is strict
# ---------------------------------------------------------------------------


def test_unit1_config_default_thresholds_are_seven():
    s = Settings(ANTHROPIC_API_KEY="x", SIDECAR_ADMIN_PASSWORD="x")
    assert s.MEME_MIN_HUMOR_SCORE == 7
    assert s.MEME_MIN_RELEVANCE_SCORE == 7


def test_unit1_haiku_hardcoded_model_and_provider(monkeypatch):
    """_score_candidates_batch posts to Anthropic with claude-haiku-4-5."""
    captured = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"content": [{"text": "[[8, 9]]"}]}

    def fake_post(url, headers, json, timeout):  # noqa: A002
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeResp()

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)

    cands = [_candidate(1)]
    settings = _make_settings("/tmp/ignored.sqlite3")
    out = meme_flow._score_candidates_batch(cands, settings)

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["json"]["model"] == "claude-haiku-4-5-20251001"
    assert captured["headers"]["x-api-key"] == "test-key"
    assert out[cands[0]["source_url"]] == {"humor": 8.0, "relevance": 9.0}


def test_unit1_filter_rejects_below_seven(db_path, monkeypatch):
    """Candidates scoring below 7 on either axis must not surface."""
    cands = [
        _candidate(1, title="Funny but off-niche"),
        _candidate(2, title="On-niche but not funny"),
        _candidate(3, title="Good on both"),
    ]

    # Force deterministic scores without touching the network.
    def fake_scorer(all_cands, settings):
        return {
            cands[0]["source_url"]: {"humor": 9.0, "relevance": 4.0},  # relevance fail
            cands[1]["source_url"]: {"humor": 5.0, "relevance": 9.0},  # humor fail
            cands[2]["source_url"]: {"humor": 8.0, "relevance": 8.0},  # passes
        }

    monkeypatch.setattr(meme_flow, "_score_candidates_batch", fake_scorer)

    # Stub the source layer to return our hand-crafted candidates.
    class _FakeSource:
        name = "reddit_programmerhumor"

        def fetch_candidates(self, settings):
            return list(cands)

    monkeypatch.setattr(
        meme_flow, "load_enabled_meme_sources", lambda s: [_FakeSource()]
    )

    # No Telegram — empty chat_id short-circuits _send_meme_preview
    settings = _make_settings(db_path)
    # settings_manager exposes .settings as a @property backed by ._settings,
    # so we patch the backing attribute directly.
    monkeypatch.setattr(meme_flow.settings_manager, "_settings", settings, raising=False)

    # Neutralize autopilot scheduler
    monkeypatch.setattr(
        meme_flow,
        "schedule_meme_auto_approve_after_trigger",
        lambda s: None,
    )
    # Neutralize Telegram send
    async def _no_send(cid):
        return None

    monkeypatch.setattr(meme_flow, "_send_meme_preview", _no_send)

    result = asyncio.run(meme_flow.run_meme_trigger())
    assert result["ok"]
    # Only candidate #3 passed the filter and got inserted
    assert result["inserted"] == 1
    assert result["surfaced"] == 1


# ---------------------------------------------------------------------------
# Unit 2 — surface limits are 2 + 2 per run
# ---------------------------------------------------------------------------


def test_unit2_config_surface_limits():
    s = Settings(ANTHROPIC_API_KEY="x", SIDECAR_ADMIN_PASSWORD="x")
    assert s.MEME_DAILY_SURFACE_LIMIT == 2
    assert s.MEME_VIDEO_DAILY_SURFACE_LIMIT == 2


def test_unit2_per_type_surface_caps_respected(db_path, monkeypatch):
    """Images and videos each get their own cap (2 each)."""
    # 5 images + 5 videos — all pass the humor/relevance filter
    cands = [
        _candidate(i, media_type=("video" if i >= 10 else "image"), score=1000 - i)
        for i in range(1, 6)
    ] + [
        _candidate(i, media_type="video", score=2000 - i)
        for i in range(10, 15)
    ]

    def fake_scorer(all_cands, settings):
        return {c["source_url"]: {"humor": 9.0, "relevance": 9.0} for c in all_cands}

    monkeypatch.setattr(meme_flow, "_score_candidates_batch", fake_scorer)

    class _FakeSource:
        name = "reddit_programmerhumor"

        def fetch_candidates(self, settings):
            return list(cands)

    monkeypatch.setattr(
        meme_flow, "load_enabled_meme_sources", lambda s: [_FakeSource()]
    )

    settings = _make_settings(db_path)
    monkeypatch.setattr(meme_flow.settings_manager, "_settings", settings, raising=False)
    monkeypatch.setattr(
        meme_flow, "schedule_meme_auto_approve_after_trigger", lambda s: None
    )

    async def _no_send(cid):
        return None

    monkeypatch.setattr(meme_flow, "_send_meme_preview", _no_send)

    result = asyncio.run(meme_flow.run_meme_trigger())
    assert result["surfaced_images"] == 2
    assert result["surfaced_videos"] == 2
    # 4 total surfaced (2 img + 2 vid), 10 total inserted
    assert result["surfaced"] == 4
    assert result["inserted"] == 10


# ---------------------------------------------------------------------------
# Unit 3 — cross-run dedup (48h lookback, 0.7 Jaccard)
# ---------------------------------------------------------------------------


def test_unit3_jaccard_above_threshold_flagged():
    assert meme_flow._jaccard_title("Debugging at 3am", "Debugging at 3am again") >= 0.7
    assert meme_flow._is_cross_run_duplicate(
        "Debugging at 3am again",
        ["Debugging at 3am"],
        threshold=0.7,
    )


def test_unit3_jaccard_below_threshold_not_flagged():
    assert meme_flow._jaccard_title(
        "Debugging at 3am", "My cat climbed the fridge"
    ) < 0.7
    assert not meme_flow._is_cross_run_duplicate(
        "My cat climbed the fridge",
        ["Debugging at 3am"],
        threshold=0.7,
    )


def test_unit3_empty_inputs_safe():
    assert meme_flow._jaccard_title("", "anything") == 0.0
    assert meme_flow._jaccard_title("something", "") == 0.0
    assert not meme_flow._is_cross_run_duplicate("anything", [])
    assert not meme_flow._is_cross_run_duplicate("", ["x y z"])


def test_unit3_fetch_recent_surfaced_titles_filters_correctly(db_conn):
    # Insert one row with telegram_message_id + recent created_at — should appear
    db_conn.execute(
        """
        INSERT INTO meme_candidates
            (source, source_url, author_handle, title, media_url, media_type,
             engagement_json, status, telegram_message_id, created_at)
        VALUES
            ('reddit_programmerhumor', 'u1', 'u/a', 'Surfaced recently', 'm1',
             'image', '{}', 'pending_review', 42,
             datetime('now', '-1 hours'))
        """
    )
    # Insert one row that was NOT surfaced (null telegram_message_id)
    db_conn.execute(
        """
        INSERT INTO meme_candidates
            (source, source_url, author_handle, title, media_url, media_type,
             engagement_json, status, telegram_message_id, created_at)
        VALUES
            ('reddit_programmerhumor', 'u2', 'u/b', 'Never surfaced', 'm2',
             'image', '{}', 'pending_review', NULL,
             datetime('now', '-1 hours'))
        """
    )
    # Insert one row surfaced >48h ago — should be filtered out by the lookback
    db_conn.execute(
        """
        INSERT INTO meme_candidates
            (source, source_url, author_handle, title, media_url, media_type,
             engagement_json, status, telegram_message_id, created_at)
        VALUES
            ('reddit_programmerhumor', 'u3', 'u/c', 'Too old', 'm3',
             'image', '{}', 'pending_review', 43,
             datetime('now', '-3 days'))
        """
    )
    db_conn.commit()

    titles = meme_flow._fetch_recent_surfaced_titles(db_conn)
    assert titles == ["Surfaced recently"]


def test_unit3_cross_run_dedup_skips_similar_in_trigger(db_path, monkeypatch):
    """Full run_meme_trigger: a newly fetched candidate whose title is
    >=0.7 similar to one surfaced in the last 48h should not re-surface."""
    # Seed the DB with a "previously surfaced" candidate from 1 hour ago
    conn = db_module.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO meme_candidates
                (source, source_url, author_handle, title, media_url, media_type,
                 engagement_json, status, telegram_message_id, created_at)
            VALUES
                ('reddit_programmerhumor',
                 'https://reddit.com/seed',
                 'u/seed', 'when the code works on the first try',
                 'https://img/seed.jpg', 'image', '{}',
                 'pending_review', 99, datetime('now', '-1 hours'))
            """
        )
        conn.commit()
    finally:
        conn.close()

    # New candidates: one near-duplicate of the seed, one totally different
    near_dup = _candidate(
        1, title="When the code works on the first try lol"
    )
    novel = _candidate(2, title="My Arduino finally blinked the LED")

    def fake_scorer(all_cands, settings):
        return {c["source_url"]: {"humor": 9.0, "relevance": 9.0} for c in all_cands}

    monkeypatch.setattr(meme_flow, "_score_candidates_batch", fake_scorer)

    class _FakeSource:
        name = "reddit_programmerhumor"

        def fetch_candidates(self, settings):
            return [near_dup, novel]

    monkeypatch.setattr(
        meme_flow, "load_enabled_meme_sources", lambda s: [_FakeSource()]
    )

    settings = _make_settings(db_path)
    monkeypatch.setattr(meme_flow.settings_manager, "_settings", settings, raising=False)
    monkeypatch.setattr(
        meme_flow, "schedule_meme_auto_approve_after_trigger", lambda s: None
    )

    async def _no_send(cid):
        return None

    monkeypatch.setattr(meme_flow, "_send_meme_preview", _no_send)

    result = asyncio.run(meme_flow.run_meme_trigger())
    # Both got inserted (new rows), but only the novel one surfaced
    assert result["inserted"] == 2
    assert result["surfaced"] == 1


# ---------------------------------------------------------------------------
# Unit 4 — additional Reddit sources registered + mapped
# ---------------------------------------------------------------------------


def test_unit4_new_sources_in_registry():
    for name in [
        "reddit_cscareerquestions",
        "reddit_webdev",
        "reddit_dataisbeautiful",
        "reddit_homelab",
        "reddit_mechanicalkeyboards",
    ]:
        assert name in _REGISTRY, f"missing source {name!r} in registry"


def test_unit4_new_sources_have_subreddit_mapping():
    expected = {
        "reddit_cscareerquestions": "cscareerquestions",
        "reddit_webdev": "webdev",
        "reddit_dataisbeautiful": "DataIsBeautiful",
        "reddit_homelab": "homelab",
        "reddit_mechanicalkeyboards": "MechanicalKeyboards",
    }
    for name, sub in expected.items():
        assert _DEFAULT_SUBREDDITS.get(name) == sub


def test_unit4_settings_defaults_include_all_new_sources():
    s = Settings(ANTHROPIC_API_KEY="x", SIDECAR_ADMIN_PASSWORD="x")
    sources = s.MEME_SOURCES
    for name in [
        "reddit_cscareerquestions",
        "reddit_webdev",
        "reddit_dataisbeautiful",
        "reddit_homelab",
        "reddit_mechanicalkeyboards",
    ]:
        assert name in sources, f"{name} missing from default MEME_SOURCES"
