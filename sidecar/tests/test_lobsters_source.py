"""Tests for LobstersTopicSource."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sidecar.topic_sources.lobsters_source import LobstersTopicSource


def _entry(**overrides):
    base = {
        "short_id": "abc123",
        "short_id_url": "https://lobste.rs/s/abc123",
        "created_at": "2026-04-07T00:00:00Z",
        "title": "A story",
        "url": "https://example.com/article",
        "score": 25,
        "comment_count": 7,
        "tags": ["programming"],
        "submitter_user": {"username": "alice"},
    }
    base.update(overrides)
    return base


FIXTURE = [
    _entry(short_id="a1", title="Rust news", url="https://ex.com/1", score=50, tags=["rust", "programming"]),
    _entry(short_id="a2", title="AI thing", url="https://ex.com/2", score=30, tags=["ai", "ml"]),
    _entry(short_id="a3", title="Discussion only", url="", short_id_url="https://lobste.rs/s/a3", score=15),
    _entry(short_id="a4", title="Too low", score=2),
    _entry(short_id="a5", title="Devtools post", url="https://ex.com/5", score=12, tags=["devtools"]),
    _entry(short_id="a6", title="Sixth", url="https://ex.com/6", score=11, tags=["unix"]),
]


class _Resp:
    def __init__(self, status_code=200, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("bad json")
        return self._payload


class _Client:
    def __init__(self, resp):
        self._resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        return self._resp


def _patch_httpx(resp):
    fake = SimpleNamespace(Client=lambda *a, **kw: _Client(resp))
    return patch.dict("sys.modules", {"httpx": fake})


def test_is_configured_true():
    assert LobstersTopicSource().is_configured(None) is True


def test_valid_fixture_returns_items():
    with _patch_httpx(_Resp(200, FIXTURE)):
        items, label = LobstersTopicSource().fetch_items(SimpleNamespace())
    titles = [i["title"] for i in items]
    assert "Rust news" in titles
    assert "AI thing" in titles
    assert "Too low" not in titles  # min_score filter
    assert label.startswith("lobsters@")
    assert all(i["source"] == "lobsters" for i in items)


def test_external_url_preferred():
    with _patch_httpx(_Resp(200, [_entry(url="https://ex.com/x", short_id_url="https://lobste.rs/s/x")])):
        items, _ = LobstersTopicSource().fetch_items(SimpleNamespace())
    assert items[0]["url"] == "https://ex.com/x"


def test_discussion_only_fallback():
    with _patch_httpx(_Resp(200, [_entry(url="", short_id_url="https://lobste.rs/s/zz", score=20)])):
        items, _ = LobstersTopicSource().fetch_items(SimpleNamespace())
    assert items[0]["url"] == "https://lobste.rs/s/zz"
    assert "Discussion-only" in items[0]["summary"]


def test_min_score_filter():
    with _patch_httpx(_Resp(200, [_entry(score=3)])):
        items, _ = LobstersTopicSource().fetch_items(SimpleNamespace())
    assert items == []


def test_empty_response():
    with _patch_httpx(_Resp(200, [])):
        items, label = LobstersTopicSource().fetch_items(SimpleNamespace())
    assert items == []
    assert label.startswith("lobsters@")


def test_http_5xx():
    with _patch_httpx(_Resp(503, None)):
        items, label = LobstersTopicSource().fetch_items(SimpleNamespace())
    assert items == []
    assert label.startswith("lobsters@")


def test_malformed_json():
    with _patch_httpx(_Resp(200, None, raise_json=True)):
        items, _ = LobstersTopicSource().fetch_items(SimpleNamespace())
    assert items == []


def test_max_items_limit():
    settings = SimpleNamespace(LOBSTERS_MAX_ITEMS=2, LOBSTERS_MIN_SCORE=1)
    with _patch_httpx(_Resp(200, FIXTURE)):
        items, _ = LobstersTopicSource().fetch_items(settings)
    assert len(items) == 2


def test_source_field_stamped():
    with _patch_httpx(_Resp(200, [_entry()])):
        items, _ = LobstersTopicSource().fetch_items(SimpleNamespace())
    assert items[0]["source"] == "lobsters"
