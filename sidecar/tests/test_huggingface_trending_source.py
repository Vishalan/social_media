"""Tests for HuggingFaceTrendingTopicSource."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from sidecar.topic_sources.huggingface_trending_source import (
    HuggingFaceTrendingTopicSource,
)


MODELS_FIXTURE = [
    {"id": "meta/llama-3", "downloads": 50000, "likes": 800, "pipeline_tag": "text-generation"},
    {"id": "tiny/noise", "downloads": 10, "likes": 0, "pipeline_tag": "text-classification"},  # filtered
    {"id": "vis/diff", "downloads": 9000, "likes": 200},  # missing pipeline_tag
    {"id": "", "downloads": 99999, "likes": 1},  # empty id, skipped
]

SPACES_FIXTURE = [
    {"id": "demo/cool-app", "likes": 120, "sdk": "gradio"},
    {"id": "low/likes", "likes": 1, "sdk": "streamlit"},  # filtered
    {"id": "no/sdk", "likes": 50},  # missing sdk
]


def _resp(status: int, json_data=None):
    req = httpx.Request("GET", "https://huggingface.co/")
    return httpx.Response(status, json=json_data if json_data is not None else [], request=req)


def _client_with(models_resp, spaces_resp):
    def handler(request):
        if "/api/models" in str(request.url):
            if isinstance(models_resp, Exception):
                raise models_resp
            return models_resp
        if "/api/spaces" in str(request.url):
            if isinstance(spaces_resp, Exception):
                raise spaces_resp
            return spaces_resp
        return _resp(404)
    # Use the real (un-patched) Client so the patch below redirects only
    # the SOURCE's httpx.Client() call, without re-entering this helper.
    return _RealClient(transport=httpx.MockTransport(handler), timeout=10.0)


_RealClient = httpx.Client  # captured once at import, before any test patches


def _run(models_resp, spaces_resp, **settings_kw):
    src = HuggingFaceTrendingTopicSource()
    settings = SimpleNamespace(**settings_kw)
    mock_client = _client_with(models_resp, spaces_resp)
    with patch("httpx.Client", lambda *a, **kw: mock_client):
        return src.fetch_items(settings)


def test_is_configured_always_true():
    assert HuggingFaceTrendingTopicSource().is_configured(None) is True
    assert HuggingFaceTrendingTopicSource().is_configured(SimpleNamespace()) is True


def test_valid_response_merges_models_and_spaces():
    items, label = _run(_resp(200, MODELS_FIXTURE), _resp(200, SPACES_FIXTURE))
    assert label.startswith("huggingface_trending@")
    titles = [i["title"] for i in items]
    assert "New trending HF model: meta/llama-3" in titles
    assert "New trending HF model: vis/diff" in titles
    assert "Trending HF Space: demo/cool-app" in titles
    assert "Trending HF Space: no/sdk" in titles
    # filters dropped these:
    assert not any("tiny/noise" in t for t in titles)
    assert not any("low/likes" in t for t in titles)
    # empty id skipped
    assert all("New trending HF model: " != t for t in titles)


def test_source_field_stamped():
    items, _ = _run(_resp(200, MODELS_FIXTURE), _resp(200, SPACES_FIXTURE))
    assert items
    assert all(i["source"] == "huggingface_trending" for i in items)


def test_missing_pipeline_tag_and_sdk_fallback():
    items, _ = _run(_resp(200, MODELS_FIXTURE), _resp(200, SPACES_FIXTURE))
    vis = next(i for i in items if "vis/diff" in i["title"])
    assert "general-purpose" in vis["summary"]
    no_sdk = next(i for i in items if "no/sdk" in i["title"])
    assert "custom" in no_sdk["summary"]


def test_empty_response_returns_empty_list():
    items, label = _run(_resp(200, []), _resp(200, []))
    assert items == []
    assert label.startswith("huggingface_trending@")


def test_one_endpoint_5xx_other_succeeds():
    items, _ = _run(_resp(500), _resp(200, SPACES_FIXTURE))
    assert items
    assert all("Space" in i["title"] for i in items)


def test_both_endpoints_5xx_returns_empty():
    items, label = _run(_resp(500), _resp(503))
    assert items == []
    assert label.startswith("huggingface_trending@")


def test_max_items_caps_output():
    big_models = [
        {"id": f"o/m{i}", "downloads": 10000, "likes": 10, "pipeline_tag": "text-generation"}
        for i in range(15)
    ]
    big_spaces = [
        {"id": f"o/s{i}", "likes": 50, "sdk": "gradio"} for i in range(15)
    ]
    items, _ = _run(_resp(200, big_models), _resp(200, big_spaces), HUGGINGFACE_MAX_ITEMS=5)
    assert len(items) == 5


def test_min_filters_respected():
    items, _ = _run(
        _resp(200, MODELS_FIXTURE),
        _resp(200, SPACES_FIXTURE),
        HUGGINGFACE_MIN_DOWNLOADS=100000,
        HUGGINGFACE_MIN_LIKES=1000,
    )
    assert items == []
