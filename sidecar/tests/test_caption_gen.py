"""Tests for sidecar.caption_gen."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure project root is importable so `sidecar.*` resolves.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar.caption_gen import (  # noqa: E402
    BRAND_TAG,
    IG_CAPTION_MAX,
    YT_CREDIT_LINE,
    YT_DESCRIPTION_MAX,
    YT_TITLE_MAX,
    generate_captions,
)


def _resp(text: str) -> MagicMock:
    r = MagicMock()
    r.content = [MagicMock(text=text)]
    return r


def _client(*texts: str) -> MagicMock:
    c = MagicMock()
    c.messages.create.side_effect = [_resp(t) for t in texts]
    return c


def _valid_payload(
    ig_caption: str = "Big AI news drop from the lab today. #commoncreed",
    ig_tags=None,
    yt_title: str = "Huge AI News You Missed",
    yt_desc: str = "Today we break down the biggest AI headline of the week.",
    yt_tags=None,
) -> dict:
    if ig_tags is None:
        ig_tags = ["#commoncreed", "#ai", "#tech", "#news", "#reels"]
    if yt_tags is None:
        yt_tags = ["#commoncreed", "#ai", "#shorts", "#tech", "#news"]
    return {
        "instagram": {"caption": ig_caption, "hashtags": ig_tags},
        "youtube": {"title": yt_title, "description": yt_desc, "hashtags": yt_tags},
    }


def _j(payload: dict) -> str:
    return json.dumps(payload)


SCRIPT = "A short script about the latest AI model release from a major lab."
HEADLINE = "AI NEWS DROP"


def test_happy_path_returns_valid_shape():
    client = _client(_j(_valid_payload()))
    result = generate_captions(SCRIPT, HEADLINE, client=client)
    assert "instagram" in result and "youtube" in result
    assert isinstance(result["instagram"]["caption"], str)
    assert isinstance(result["instagram"]["hashtags"], list)
    assert isinstance(result["youtube"]["title"], str)
    assert isinstance(result["youtube"]["description"], str)
    assert isinstance(result["youtube"]["hashtags"], list)
    assert client.messages.create.call_count == 1


def test_ig_caption_length_enforced():
    # First attempt too long, second attempt valid.
    bad = _valid_payload(ig_caption="x" * (IG_CAPTION_MAX + 20))
    good = _valid_payload()
    client = _client(_j(bad), _j(good))
    result = generate_captions(SCRIPT, HEADLINE, client=client)
    assert client.messages.create.call_count == 2
    assert len(result["instagram"]["caption"]) <= IG_CAPTION_MAX


def test_ig_caption_length_fallback_after_retry():
    bad = _valid_payload(ig_caption="x" * (IG_CAPTION_MAX + 20))
    client = _client(_j(bad), _j(bad))
    result = generate_captions(SCRIPT, HEADLINE, client=client)
    assert client.messages.create.call_count == 2
    # Fallback uses the headline as caption.
    assert result["instagram"]["caption"] == HEADLINE
    assert BRAND_TAG in result["instagram"]["hashtags"]
    assert BRAND_TAG in result["youtube"]["hashtags"]


def test_yt_title_length_enforced():
    bad = _valid_payload(yt_title="T" * (YT_TITLE_MAX + 5))
    good = _valid_payload()
    client = _client(_j(bad), _j(good))
    result = generate_captions(SCRIPT, HEADLINE, client=client)
    assert client.messages.create.call_count == 2
    assert len(result["youtube"]["title"]) <= YT_TITLE_MAX


def test_yt_description_length_enforced():
    bad = _valid_payload(yt_desc="d" * (YT_DESCRIPTION_MAX + 50))
    good = _valid_payload()
    client = _client(_j(bad), _j(good))
    result = generate_captions(SCRIPT, HEADLINE, client=client)
    assert client.messages.create.call_count == 2
    # Post-append description = llm desc + credit line.
    assert result["youtube"]["description"].endswith(YT_CREDIT_LINE)


def test_hashtag_count_enforced_min():
    bad = _valid_payload(ig_tags=["#commoncreed", "#ai", "#tech"])  # 3 < 5
    good = _valid_payload()
    client = _client(_j(bad), _j(good))
    generate_captions(SCRIPT, HEADLINE, client=client)
    assert client.messages.create.call_count == 2


def test_hashtag_count_enforced_max():
    bad = _valid_payload(
        ig_tags=["#commoncreed"] + [f"#tag{i}" for i in range(11)]  # 12 > 10
    )
    good = _valid_payload()
    client = _client(_j(bad), _j(good))
    generate_captions(SCRIPT, HEADLINE, client=client)
    assert client.messages.create.call_count == 2


def test_hashtag_format_enforced():
    # hashtag missing '#'
    bad = _valid_payload(ig_tags=["commoncreed", "#ai", "#tech", "#news", "#reels"])
    good = _valid_payload()
    client = _client(_j(bad), _j(good))
    generate_captions(SCRIPT, HEADLINE, client=client)
    assert client.messages.create.call_count == 2


def test_hashtag_format_enforced_spaces():
    bad = _valid_payload(
        ig_tags=["#commoncreed", "#ai news", "#tech", "#news", "#reels"]
    )
    good = _valid_payload()
    client = _client(_j(bad), _j(good))
    generate_captions(SCRIPT, HEADLINE, client=client)
    assert client.messages.create.call_count == 2


def test_commoncreed_tag_always_present_ig():
    result = generate_captions(SCRIPT, HEADLINE, client=_client(_j(_valid_payload())))
    assert BRAND_TAG in [t.lower() for t in result["instagram"]["hashtags"]]


def test_commoncreed_tag_always_present_yt():
    result = generate_captions(SCRIPT, HEADLINE, client=_client(_j(_valid_payload())))
    assert BRAND_TAG in [t.lower() for t in result["youtube"]["hashtags"]]


def test_commoncreed_missing_triggers_retry():
    bad = _valid_payload(
        ig_tags=["#ai", "#tech", "#news", "#reels", "#shorts"]  # no #commoncreed
    )
    good = _valid_payload()
    client = _client(_j(bad), _j(good))
    generate_captions(SCRIPT, HEADLINE, client=client)
    assert client.messages.create.call_count == 2


def test_yt_credit_line_appended():
    # Use a description that's near but under the limit so we can verify the
    # credit line is appended AFTER validation (final length > internal budget
    # is acceptable).
    long_desc = "x" * (YT_DESCRIPTION_MAX - 10)
    payload = _valid_payload(yt_desc=long_desc)
    client = _client(_j(payload))
    result = generate_captions(SCRIPT, HEADLINE, client=client)
    assert "@vishalangharat" in result["youtube"]["description"]
    assert result["youtube"]["description"].endswith(YT_CREDIT_LINE)
    # Together they exceed 500 — that's fine, append-after-validation is intentional.
    assert len(result["youtube"]["description"]) == len(long_desc) + len(YT_CREDIT_LINE)


def test_fallback_when_json_parse_fails_twice():
    client = _client("not json at all", "still {not json")
    result = generate_captions(SCRIPT, HEADLINE, client=client)
    assert "instagram" in result and "youtube" in result
    assert result["instagram"]["caption"] == HEADLINE
    assert BRAND_TAG in result["instagram"]["hashtags"]
    assert result["youtube"]["description"].endswith(YT_CREDIT_LINE)
    assert client.messages.create.call_count == 2


def test_never_raises_on_catastrophic_llm_failure():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    # Should NOT raise.
    result = generate_captions(SCRIPT, HEADLINE, client=client)
    assert "instagram" in result and "youtube" in result
    assert BRAND_TAG in result["instagram"]["hashtags"]
    assert BRAND_TAG in result["youtube"]["hashtags"]
    assert result["youtube"]["description"].endswith(YT_CREDIT_LINE)
    # Both attempts made.
    assert client.messages.create.call_count == 2


def test_set_captions_persists_to_db(tmp_path):
    from sidecar.db import connect, init_db, set_captions

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    # Migration must be idempotent.
    init_db(db_path)

    conn = connect(db_path)
    cur = conn.execute(
        "INSERT INTO pipeline_runs (status) VALUES ('pending')"
    )
    run_id = cur.lastrowid
    conn.commit()

    captions = _valid_payload()
    set_captions(conn, run_id, captions)

    row = conn.execute(
        "SELECT captions_json FROM pipeline_runs WHERE id = ?", (run_id,)
    ).fetchone()
    assert row is not None
    assert json.loads(row["captions_json"]) == captions
    conn.close()
