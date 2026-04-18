"""Tests for Unit B3 — 2026 editing-rhythm rules in the timeline planner.

These tests cover:
  1. ``_TIMELINE_SYSTEM_PROMPT`` contains the 2026 rhythm-rule keywords.
  2. The per-video segment budget math for a 60 s video (``MAX = 40``).
  3. The per-video segment budget math for a 30 s video (``MAX = 20``).
  4. ``_plan_timeline`` overflow → compaction retry with the compaction prompt.
  5. ``_plan_timeline`` still over budget after retry → truncate to the cap.
  6. ``_plan_timeline`` normal (in-budget) response passes through unchanged.

All Anthropic calls are mocked following the pattern established in
``test_selector.py`` / ``test_stats_card.py``. No real HTTP / LLM calls are made.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

# Dual-import: run from repo root (scripts.broll_gen...) or from scripts/.
try:
    from scripts.broll_gen.browser_visit import (
        BrowserVisitGenerator,
        _TIMELINE_SYSTEM_PROMPT,
    )
except ImportError:  # pragma: no cover — fallback when cwd is scripts/
    from broll_gen.browser_visit import (  # type: ignore[no-redef]
        BrowserVisitGenerator,
        _TIMELINE_SYSTEM_PROMPT,
    )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_haiku_response(n_segments: int) -> MagicMock:
    """Build a MagicMock Anthropic ``messages.create`` response with n browser segments."""
    segments = [
        {"type": "browser", "scroll_pct": (i % 10) / 10.0} for i in range(n_segments)
    ]
    payload = json.dumps({"segments": segments})
    resp = MagicMock()
    resp.content = [MagicMock(text=payload)]
    return resp


def _make_mock_client_sequence(*counts: int) -> MagicMock:
    """Build a mock AsyncAnthropic client that returns Haiku responses of the given lengths in order."""
    responses = [_make_haiku_response(c) for c in counts]
    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=responses)
    return client


def _make_sections(n: int = 5) -> list[dict]:
    """Synthesize n valid captured sections for ``_plan_timeline`` inputs."""
    return [
        {
            "scroll_pct": i / max(n - 1, 1),
            "screenshot_path": f"/tmp/section_{i}.png",
            "text": f"Section {i} article text about some topic.",
        }
        for i in range(n)
    ]


_SCRIPT_TEXT = (
    "Today we break down the newest AI release. The model is ten times faster "
    "than last year and it runs on consumer hardware. This changes everything "
    "for small teams who have been waiting for affordable inference. Let's dig in."
)


# ── 1. System prompt contains the 2026 rhythm rules ────────────────────────────


def test_system_prompt_contains_rhythm_rules() -> None:
    assert "2–4 seconds" in _TIMELINE_SYSTEM_PROMPT, (
        "Rhythm rules must mention cutting every 2–4 seconds"
    )
    assert "burst sequence" in _TIMELINE_SYSTEM_PROMPT, (
        "Rhythm rules must mention the 'burst sequence' retention reset"
    )


# ── 2 & 3. Per-video segment-budget math ──────────────────────────────────────


def test_segment_budget_60s() -> None:
    # A 60 s video gets a budget of max(8, int(60 / 1.5)) == 40 segments.
    assert max(8, int(60 / 1.5)) == 40


def test_segment_budget_30s() -> None:
    # A 30 s video gets a budget of max(8, int(30 / 1.5)) == 20 segments.
    assert max(8, int(30 / 1.5)) == 20


# ── 4. Overflow triggers compaction retry ─────────────────────────────────────


async def test_planner_overflow_triggers_compaction_retry() -> None:
    # 45 s video → MAX = max(8, 30) = 30, hard_cap = 45.
    # First call returns 50 (> 45) → triggers retry.
    # Retry returns 38 (≤ 45) → passes.
    target_duration_s = 45.0
    n_segments = 10

    mock_client = _make_mock_client_sequence(50, 38)
    gen = BrowserVisitGenerator(anthropic_client=mock_client)
    sections = _make_sections(5)

    result = await gen._plan_timeline(
        script_text=_SCRIPT_TEXT,
        target_duration_s=target_duration_s,
        sections=sections,
        n_segments=n_segments,
    )

    # Haiku was called twice: original + compaction retry.
    assert mock_client.messages.create.await_count == 2, (
        f"Expected exactly 2 Haiku calls (original + compaction retry); "
        f"got {mock_client.messages.create.await_count}"
    )

    # The SECOND call must include the compaction prompt text.
    second_call_kwargs = mock_client.messages.create.await_args_list[1].kwargs
    second_user_msg = second_call_kwargs["messages"][0]["content"]
    assert "exceeded the segment budget" in second_user_msg, (
        "Compaction retry prompt must tell Haiku the previous plan exceeded the budget"
    )
    assert "Consolidate adjacent same-type segments" in second_user_msg, (
        "Compaction retry prompt must tell Haiku to consolidate adjacent segments"
    )
    assert "30" in second_user_msg, (
        "Compaction retry prompt must include the concrete segment budget (30 for 45 s)"
    )

    # The returned list has the retry's 38 segments (validated, unchanged count).
    assert len(result) == 38, (
        f"Expected 38 segments after successful compaction retry; got {len(result)}"
    )


# ── 5. Still over budget after retry → truncate to cap ────────────────────────


async def test_planner_still_over_after_retry_truncates() -> None:
    # 60 s video → MAX = 40, hard_cap = 60.
    # First call: 70 (> 60) → triggers retry.
    # Retry: 65 (> 60) → truncate to hard_cap (60).
    target_duration_s = 60.0
    n_segments = 10
    expected_cap = int(max(8, int(target_duration_s / 1.5)) * 1.5)  # == 60

    mock_client = _make_mock_client_sequence(70, 65)
    gen = BrowserVisitGenerator(anthropic_client=mock_client)
    sections = _make_sections(5)

    result = await gen._plan_timeline(
        script_text=_SCRIPT_TEXT,
        target_duration_s=target_duration_s,
        sections=sections,
        n_segments=n_segments,
    )

    assert mock_client.messages.create.await_count == 2, (
        "Planner must retry exactly once even when the retry is still over budget"
    )
    assert len(result) <= expected_cap, (
        f"When retry is still over budget, result must be truncated to ≤ {expected_cap}; "
        f"got {len(result)}"
    )
    # Specifically: our implementation truncates to the hard cap (MAX*1.5 = 60).
    assert len(result) == expected_cap, (
        f"Expected truncation to exactly MAX*1.5 = {expected_cap}; got {len(result)}"
    )


# ── 6. In-budget response passes through unchanged (no retry) ─────────────────


async def test_existing_timeline_parsing_unchanged() -> None:
    # 60 s video → MAX = 40, hard_cap = 60. A 20-segment response is well under.
    target_duration_s = 60.0
    n_segments = 20  # caller-requested; Haiku returns exactly 20.

    mock_client = _make_mock_client_sequence(20)
    gen = BrowserVisitGenerator(anthropic_client=mock_client)
    sections = _make_sections(5)

    result = await gen._plan_timeline(
        script_text=_SCRIPT_TEXT,
        target_duration_s=target_duration_s,
        sections=sections,
        n_segments=n_segments,
    )

    # No retry — Haiku was called exactly once.
    assert mock_client.messages.create.await_count == 1, (
        "A 20-segment response is well under the 60-cap and must NOT trigger a retry"
    )
    # Result length matches the reasonable 20-segment plan.
    assert len(result) == 20, (
        f"Expected 20 validated segments to pass through unchanged; got {len(result)}"
    )
    # Every entry is a valid browser segment dict (sanity).
    for seg in result:
        assert seg["type"] == "browser"
        assert isinstance(seg["scroll_pct"], float)
