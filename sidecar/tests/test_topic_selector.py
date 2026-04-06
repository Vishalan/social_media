"""Tests for sidecar.topic_selector."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar.topic_selector import extract_items, score_topics  # noqa: E402


def _make_client(*texts):
    client = MagicMock()
    responses = []
    for t in texts:
        r = MagicMock()
        r.content = [MagicMock(text=t)]
        responses.append(r)
    client.messages.create.side_effect = responses
    return client


SAMPLE_ITEMS = [
    {
        "title": "OpenAI launches GPT-6",
        "url": "https://example.com/gpt6",
        "description": "10M context",
        "category": "Big Tech",
    },
    {
        "title": "Google Gemini 3",
        "url": "https://example.com/gemini3",
        "description": "Enterprise",
        "category": "Big Tech",
    },
]


def test_extract_items_happy_path():
    payload = json.dumps(SAMPLE_ITEMS)
    client = _make_client(payload)
    out = extract_items("body goes here with stories", client=client)
    assert len(out) == 2
    assert out[0]["title"] == "OpenAI launches GPT-6"
    assert client.messages.create.call_count == 1


def test_extract_items_retries_on_invalid_json():
    good = json.dumps(SAMPLE_ITEMS)
    client = _make_client("this is not json at all", good)
    out = extract_items("body", client=client)
    assert len(out) == 2
    assert client.messages.create.call_count == 2


def test_extract_items_raises_after_two_failures():
    client = _make_client("garbage one", "garbage two")
    with pytest.raises(ValueError, match="extract_items failed"):
        extract_items("body", client=client)
    assert client.messages.create.call_count == 2


def test_extract_items_empty_body_returns_empty_list():
    client = _make_client("SHOULD NOT BE CALLED")
    assert extract_items("", client=client) == []
    assert extract_items("   ", client=client) == []
    assert client.messages.create.call_count == 0


def test_score_topics_picks_top_n_by_score():
    scored = [
        {"title": "A", "url": "u1", "description": "d", "score": 10, "rationale": "r"},
        {"title": "B", "url": "u2", "description": "d", "score": 35, "rationale": "r"},
        {"title": "C", "url": "u3", "description": "d", "score": 22, "rationale": "r"},
        {"title": "D", "url": "u4", "description": "d", "score": 40, "rationale": "r"},
        {"title": "E", "url": "u5", "description": "d", "score": 5, "rationale": "r"},
    ]
    client = _make_client(json.dumps(scored))
    items = [{"title": x["title"], "url": x["url"], "description": "d", "category": "c"} for x in scored]
    top = score_topics(items, client=client, top_n=2)
    assert len(top) == 2
    assert top[0]["title"] == "D"
    assert top[1]["title"] == "B"


def test_score_topics_retries_on_invalid_json():
    good = json.dumps(
        [
            {"title": "A", "url": "u", "description": "d", "score": 30, "rationale": "r"},
            {"title": "B", "url": "u", "description": "d", "score": 20, "rationale": "r"},
        ]
    )
    client = _make_client("not json", good)
    top = score_topics(SAMPLE_ITEMS, client=client, top_n=2)
    assert len(top) == 2
    assert top[0]["title"] == "A"
    assert client.messages.create.call_count == 2
