"""Tests for Unit B1 — TweetRevealGenerator.

All external services are mocked:
  - Playwright (``_screenshot_html`` is monkey-patched to write a stub PNG).
  - Jinja (``_render_template`` is the real call in most tests — it renders
    the in-repo template against an in-process Jinja env; we assert on the
    HTML string directly for the verified/handle conditional tests).
  - FFmpeg (``_assemble_video`` is monkey-patched; we also spot-check frame
    counts by intercepting the PNG-path list the generator hands it).

No network or real browser is ever touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

# Dual-import: bare primary (matches factory.py's import path — preserves
# class identity so ``isinstance(make_broll_generator(...), TweetRevealGenerator)``
# passes), ``scripts.`` fallback when only the repo root is on sys.path.
try:
    from broll_gen import tweet_reveal as tr_module  # type: ignore[import-not-found]
    from broll_gen.base import BrollError  # type: ignore[import-not-found]
    from broll_gen.factory import make_broll_generator  # type: ignore[import-not-found]
    from broll_gen.tweet_reveal import (  # type: ignore[import-not-found]
        TweetRevealGenerator,
        _ANIMATION_FRAMES,
        _FRAME_STEP_S,
        _avatar_initial,
        _cubic_ease_out,
        _frame_values,
        _render_template,
    )
except ImportError:  # pragma: no cover — fallback when only repo-root on sys.path
    from scripts.broll_gen import tweet_reveal as tr_module  # type: ignore[no-redef]
    from scripts.broll_gen.base import BrollError  # type: ignore[no-redef]
    from scripts.broll_gen.factory import make_broll_generator  # type: ignore[no-redef]
    from scripts.broll_gen.tweet_reveal import (  # type: ignore[no-redef]
        TweetRevealGenerator,
        _ANIMATION_FRAMES,
        _FRAME_STEP_S,
        _avatar_initial,
        _cubic_ease_out,
        _frame_values,
        _render_template,
    )


# ─── Synthetic VideoJob ──────────────────────────────────────────────────────


@dataclass
class _FakeVideoJob:
    """Minimal VideoJob stand-in — only the fields TweetReveal reads."""

    topic: dict = field(default_factory=dict)
    script: dict = field(default_factory=dict)
    tweet_quote: Optional[dict] = None


def _synthetic_tweet_quote(**overrides) -> dict:
    base = {
        "author": "Sam Altman",
        "handle": "sama",
        "body": "GPT-5 is live today. Biggest leap in a year.",
        "like_count_estimate": 4200,
        "verified": True,
    }
    base.update(overrides)
    return base


# ─── 1. Happy path (mocked Playwright + FFmpeg) ─────────────────────────────


async def test_happy_path_mocked(monkeypatch, tmp_path):
    """Mock Playwright + FFmpeg; assert the generator returns the output path
    and that the FFmpeg-bound PNG list contains exactly ``_ANIMATION_FRAMES``
    frames."""

    assemble_calls: list[dict] = []

    async def fake_screenshot_html(html, output_path):
        # Write a one-byte stub so the concat-list pass has a real file path.
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\nstub")

    async def fake_assemble_video(png_paths, target_duration_s, output_path):
        assemble_calls.append(
            {
                "png_paths": list(png_paths),
                "target_duration_s": target_duration_s,
                "output_path": output_path,
            }
        )
        Path(output_path).write_bytes(b"\x00\x00\x00\x18ftypmp42fake")

    monkeypatch.setattr(tr_module, "_screenshot_html", fake_screenshot_html)
    monkeypatch.setattr(tr_module, "_assemble_video", fake_assemble_video)

    gen = TweetRevealGenerator()
    job = _FakeVideoJob(
        topic={"title": "GPT-5 Launch"},
        script={"script": "sample"},
        tweet_quote=_synthetic_tweet_quote(),
    )
    output_path = str(tmp_path / "out.mp4")

    result = await gen.generate(job, target_duration_s=4.0, output_path=output_path)

    assert result == output_path
    assert Path(output_path).exists()

    # One and only one FFmpeg assembly pass, with the expected frame count.
    assert len(assemble_calls) == 1
    assert len(assemble_calls[0]["png_paths"]) == _ANIMATION_FRAMES
    assert assemble_calls[0]["target_duration_s"] == pytest.approx(4.0)
    assert assemble_calls[0]["output_path"] == output_path


# ─── 2. Missing tweet_quote raises ──────────────────────────────────────────


async def test_missing_tweet_quote_raises(tmp_path):
    """Without ``tweet_quote``, the selector's gating failed — the generator
    must loudly raise ``BrollError`` with the exact spec message."""

    gen = TweetRevealGenerator()
    job = _FakeVideoJob(tweet_quote=None)

    with pytest.raises(
        BrollError, match="tweet_reveal requires job.tweet_quote"
    ):
        await gen.generate(
            job, target_duration_s=4.0, output_path=str(tmp_path / "o.mp4")
        )


# ─── 3. Counter frame count (animation timeline math) ───────────────────────


def test_counter_frame_count():
    """Animation pipeline produces exactly ``_ANIMATION_FRAMES`` frames over
    1.5 s, with the counter at 0 on the first frame and at the target on the
    last — cubic ease-out monotonically increasing."""

    # Structural invariant the generator + FFmpeg concat-list rely on.
    assert _ANIMATION_FRAMES == 30
    assert _FRAME_STEP_S == pytest.approx(0.05)
    assert _ANIMATION_FRAMES * _FRAME_STEP_S == pytest.approx(1.5)

    target = 4200
    values = [_frame_values(i, target) for i in range(_ANIMATION_FRAMES)]

    # First frame: counter = 0, card fully offset + invisible.
    first_count, first_ty, first_op = values[0]
    assert first_count == 0
    assert first_ty == 80  # full _SLIDE_START_OFFSET_PX
    assert first_op == pytest.approx(0.0)

    # Last frame: counter = target, card settled + fully opaque.
    last_count, last_ty, last_op = values[-1]
    assert last_count == target
    assert last_ty == 0
    assert last_op == pytest.approx(1.0)

    # Monotonic non-decreasing counter across the animation.
    counts = [v[0] for v in values]
    assert counts == sorted(counts), f"counter regressed across frames: {counts}"

    # Cubic ease-out sanity: midpoint progress > 0.5 (fast start).
    mid_eased = _cubic_ease_out(0.5)
    assert mid_eased > 0.5


# ─── 4. Factory wiring ──────────────────────────────────────────────────────


def test_factory_wiring():
    """``make_broll_generator('tweet_reveal')`` returns a TweetRevealGenerator
    instance — no more NotImplementedError (Unit B1 flips the placeholder)."""
    gen = make_broll_generator("tweet_reveal")
    assert isinstance(gen, TweetRevealGenerator), (
        f"factory returned {type(gen).__name__} for tweet_reveal; "
        "expected TweetRevealGenerator (check the bare-import / "
        "scripts.*-import dual path)"
    )


# ─── 5. Verified badge conditional ──────────────────────────────────────────


def test_verified_badge_conditional():
    """``verified=False`` → template output lacks the sky-blue checkmark SVG.

    We assert on the literal accessibility label ``aria-label="Verified"``
    which only appears when the ``{% if verified %}`` branch fires.
    """

    common_kwargs = dict(
        author="Jane Doe",
        handle="janedoe",
        body="A short body.",
        like_count=123,
        card_translate_y=0,
        card_opacity=1.0,
        avatar_initial="J",
    )

    html_verified = _render_template(verified=True, **common_kwargs)
    html_unverified = _render_template(verified=False, **common_kwargs)

    assert 'aria-label="Verified"' in html_verified, (
        "verified=True must include the checkmark SVG's aria-label"
    )
    assert "aria-label=\"Verified\"" not in html_unverified, (
        "verified=False must NOT render the checkmark SVG"
    )
    # And the sky-blue fill only needs to be present for the heart in the
    # unverified variant (heart icon always renders). We assert the author
    # name is still shown on both.
    assert "Jane Doe" in html_verified
    assert "Jane Doe" in html_unverified


# ─── 6. Handle fallback (None → author-only) ────────────────────────────────


def test_handle_fallback():
    """When ``handle=None``, the rendered HTML contains the author name and
    no ``@``-prefixed handle element."""

    html_with_handle = _render_template(
        author="Alice Example",
        handle="alicex",
        body="Some body.",
        verified=False,
        like_count=10,
        card_translate_y=0,
        card_opacity=1.0,
        avatar_initial="A",
    )
    html_no_handle = _render_template(
        author="Alice Example",
        handle=None,
        body="Some body.",
        verified=False,
        like_count=10,
        card_translate_y=0,
        card_opacity=1.0,
        avatar_initial="A",
    )

    assert "Alice Example" in html_with_handle
    assert "Alice Example" in html_no_handle
    # Handle variant renders the @-prefixed block.
    assert "@alicex" in html_with_handle
    assert 'class="handle"' in html_with_handle
    # None variant: neither the @-prefix for this handle nor the .handle
    # container element appear.
    assert "@alicex" not in html_no_handle
    assert 'class="handle"' not in html_no_handle


# ─── Avatar initial helper (no-argument sanity) ─────────────────────────────


def test_avatar_initial_uses_first_letter():
    """Tiny helper-level sanity so the template always gets a printable
    glyph even when the author starts with punctuation or is empty."""

    assert _avatar_initial("Sam Altman") == "S"
    assert _avatar_initial("  ella  ") == "E"
    # Non-alpha first character falls through to first alnum.
    assert _avatar_initial("3M") == "M"
    # Completely empty or punctuation-only author → "?".
    assert _avatar_initial("") == "?"
    assert _avatar_initial("!!!") == "?"
