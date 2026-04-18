"""Tests for Unit A3 — ``scripts.content_gen.keyword_extractor``.

These tests are hermetic:
  * Haiku is mocked via ``AsyncAnthropic``-shaped stubs (no network).
  * No real ffmpeg / subprocess involvement.
  * Caption segments are synthesised inline, matching Whisper's
    ``{word, start, end}`` shape from Unit A2.

Test-first posture (origin plan Unit A3): the drift-guard test was authored
BEFORE the extractor implementation — it encodes the Tier 0 invariant that
zoom-punches can only land on real Whisper-emitted words.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Dual-import (consistent with scripts/pytest.ini pythonpath=.): bare primary,
# ``scripts.`` fallback when only the repo root is on sys.path.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

try:
    from content_gen.keyword_extractor import (  # type: ignore[import-not-found]
        KeywordPunch,
        extract_keyword_punches,
    )
except ImportError:  # pragma: no cover — only when scripts/ is not on sys.path
    from scripts.content_gen.keyword_extractor import (  # type: ignore[no-redef]
        KeywordPunch,
        extract_keyword_punches,
    )


# ─── Fixtures ────────────────────────────────────────────────────────────────


def _segments(words: list[str], start: float = 1.0, per_word: float = 0.25) -> list[dict]:
    """Build synthetic caption_segments with deterministic timestamps."""
    out: list[dict] = []
    t = start
    for w in words:
        out.append({"word": w, "start": t, "end": t + per_word})
        t += per_word
    return out


def _mock_haiku(response_json_text: str) -> MagicMock:
    """Build an ``AsyncAnthropic``-shaped mock that returns ``response_json_text``."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=response_json_text)]
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    return mock_client


# ─── 1. Happy path ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_happy_path_mocked():
    """Haiku returns 2 valid tokens, both present in captions → 2 KeywordPunch."""
    caption_segments = _segments(
        ["Today", "GPT-5", "launched", "with", "40%", "higher", "scores"],
        start=1.0,
        per_word=0.3,
    )
    client = _mock_haiku(
        '['
        ' {"word": "GPT-5", "intensity": "heavy"},'
        ' {"word": "40%", "intensity": "medium"}'
        ']'
    )

    punches = await extract_keyword_punches(
        script_text="Today GPT-5 launched with 40% higher scores.",
        caption_segments=caption_segments,
        anthropic_client=client,
    )

    assert len(punches) == 2
    # GPT-5 is segment index 1 → start=1.3
    gpt5 = next(p for p in punches if p.word.lower() == "gpt-5")
    assert pytest.approx(gpt5.t_start, abs=1e-6) == 1.3
    assert pytest.approx(gpt5.t_end, abs=1e-6) == 1.3 + 0.3
    assert gpt5.intensity == "heavy"
    # 40% is segment index 4 → start=1.0 + 4*0.3 = 2.2
    forty = next(p for p in punches if "40" in p.word)
    assert pytest.approx(forty.t_start, abs=1e-6) == 2.2
    assert forty.intensity == "medium"


# ─── 2. Drift guard — hallucinated word dropped + WARN logged ────────────────


@pytest.mark.asyncio
async def test_drift_guard_drops_hallucinated_word(caplog):
    """Haiku emits a word NOT in caption_segments → dropped, WARN logged."""
    caption_segments = _segments(["Hello", "world"], start=0.5, per_word=0.4)
    # "Martians" is a pure hallucination — never appears in captions.
    client = _mock_haiku(
        '[{"word": "Martians", "intensity": "heavy"}]'
    )

    with caplog.at_level(logging.WARNING, logger="content_gen.keyword_extractor"):
        punches = await extract_keyword_punches(
            script_text="Hello world.",
            caption_segments=caption_segments,
            anthropic_client=client,
        )

    assert punches == []
    # One WARN message per drop.
    drift_logs = [r for r in caplog.records if "drift" in r.message.lower() or "drop" in r.message.lower()]
    assert len(drift_logs) == 1


# ─── 3. Drift guard — case-insensitive matching ──────────────────────────────


@pytest.mark.asyncio
async def test_drift_guard_case_insensitive_match():
    """Haiku says 'openai', caption has 'OpenAI' — should match."""
    caption_segments = _segments(["Today", "OpenAI", "shipped"], start=1.0, per_word=0.25)
    client = _mock_haiku(
        '[{"word": "openai", "intensity": "medium"}]'
    )

    punches = await extract_keyword_punches(
        script_text="Today OpenAI shipped something.",
        caption_segments=caption_segments,
        anthropic_client=client,
    )

    assert len(punches) == 1
    assert punches[0].word.lower() == "openai"
    # OpenAI is index 1 → start = 1.0 + 0.25 = 1.25
    assert pytest.approx(punches[0].t_start, abs=1e-6) == 1.25


# ─── 4. Empty script ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_script_returns_empty():
    """Empty / whitespace script → no API call, empty result."""
    # Client should never be invoked — use a failing mock to prove it.
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=AssertionError("should not be called"))

    punches = await extract_keyword_punches(
        script_text="",
        caption_segments=[],
        anthropic_client=client,
    )

    assert punches == []
    client.messages.create.assert_not_called()


# ─── 5. Intensity normalisation ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_intensity_normalization():
    """Haiku emits a bad intensity → defaults to 'medium'."""
    caption_segments = _segments(["Claude", "shipped"], start=0.5, per_word=0.3)
    client = _mock_haiku(
        '[{"word": "Claude", "intensity": "nuclear"}]'  # invalid → default
    )

    punches = await extract_keyword_punches(
        script_text="Claude shipped.",
        caption_segments=caption_segments,
        anthropic_client=client,
    )

    assert len(punches) == 1
    assert punches[0].intensity == "medium"


# ─── 6. Trimmed-audio clock preserved (Tier 0 invariant) ─────────────────────


@pytest.mark.asyncio
async def test_trimmed_audio_clock_preserved():
    """KeywordPunch t_start must exactly equal caption_segments[i]['start'].

    The caption_segments passed in are already on the trimmed-audio clock
    (see smoke_e2e + Unit A2 docstring). The extractor MUST NOT re-resolve
    timestamps via any other clock — a matched word's ``t_start`` is the
    caption's ``start`` field verbatim.
    """
    # Pick unusual float values to make accidental recomputation obvious.
    caption_segments = [
        {"word": "The", "start": 3.14159, "end": 3.41421},
        {"word": "Gemini", "start": 3.41421, "end": 3.73205},
        {"word": "model", "start": 3.73205, "end": 4.12310},
    ]
    client = _mock_haiku(
        '[{"word": "Gemini", "intensity": "heavy"}]'
    )

    punches = await extract_keyword_punches(
        script_text="The Gemini model.",
        caption_segments=caption_segments,
        anthropic_client=client,
    )

    assert len(punches) == 1
    # Exact equality — no re-resolution.
    assert punches[0].t_start == 3.41421
    assert punches[0].t_end == 3.73205


# ─── 7. Haiku failure isolation ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_haiku_failure_returns_empty_not_raises(caplog):
    """If Haiku raises, the extractor returns [] — never propagates."""
    caption_segments = _segments(["Hello"], start=1.0)
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=RuntimeError("network boom"))

    with caplog.at_level(logging.WARNING, logger="content_gen.keyword_extractor"):
        punches = await extract_keyword_punches(
            script_text="Hello world.",
            caption_segments=caption_segments,
            anthropic_client=client,
        )

    assert punches == []
    # A WARN should describe the failure so operators can investigate.
    assert any("haiku" in r.message.lower() or "claude" in r.message.lower() or "keyword" in r.message.lower()
               for r in caplog.records)


# ─── 8. Trailing punctuation on caption word still matches ───────────────────


@pytest.mark.asyncio
async def test_match_strips_trailing_punctuation():
    """Whisper often emits 'GPT-5,' or 'GPT-5.' — the guard should still match."""
    caption_segments = [
        {"word": "Today", "start": 1.0, "end": 1.3},
        {"word": "GPT-5,", "start": 1.3, "end": 1.6},
        {"word": "launched", "start": 1.6, "end": 2.0},
    ]
    client = _mock_haiku(
        '[{"word": "GPT-5", "intensity": "heavy"}]'
    )

    punches = await extract_keyword_punches(
        script_text="Today GPT-5 launched.",
        caption_segments=caption_segments,
        anthropic_client=client,
    )

    assert len(punches) == 1
    assert punches[0].t_start == 1.3
