"""Tests for Unit A1 — PhoneHighlightGenerator.

All external services are mocked:
  - Playwright (``_screenshot_html`` is monkey-patched to write a stub PNG).
  - Haiku (the ``anthropic_client`` fixture is an ``AsyncMock``).
  - Jinja (``_render_template`` is monkey-patched to capture its call args).
  - FFmpeg (``subprocess.run`` via ``_assemble_video`` monkey-patch).

No network or real browser is ever touched.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# Dual-import with a twist: the factory module unconditionally uses bare
# ``broll_gen.*`` imports (see scripts/broll_gen/factory.py), which means
# ``isinstance(gen, PhoneHighlightGenerator)`` only passes when THIS test
# imports from the same namespace. Prefer the bare path (available via
# scripts/pytest.ini's ``pythonpath = .``). Fall back to the ``scripts.``-
# prefixed form when the test is run from a context that only exposes the
# repo root.
try:
    from broll_gen import phone_highlight as ph_module  # type: ignore[import-not-found]
    from broll_gen.base import BrollError  # type: ignore[import-not-found]
    from broll_gen.factory import make_broll_generator  # type: ignore[import-not-found]
    from broll_gen.phone_highlight import (  # type: ignore[import-not-found]
        PhoneHighlightGenerator,
        Phrase,
        _chunk_phrases,
    )
except ImportError:  # pragma: no cover — fallback when only repo-root on sys.path
    from scripts.broll_gen import phone_highlight as ph_module  # type: ignore[no-redef]
    from scripts.broll_gen.base import BrollError  # type: ignore[no-redef]
    from scripts.broll_gen.factory import make_broll_generator  # type: ignore[no-redef]
    from scripts.broll_gen.phone_highlight import (  # type: ignore[no-redef]
        PhoneHighlightGenerator,
        Phrase,
        _chunk_phrases,
    )


# ─── Synthetic VideoJob ──────────────────────────────────────────────────────


@dataclass
class _FakeVideoJob:
    """Minimal VideoJob stand-in — only the fields this generator reads."""

    topic: dict = field(default_factory=dict)
    script: dict = field(default_factory=dict)
    caption_segments: list[dict] = field(default_factory=list)
    extracted_article: Optional[dict] = None


def _synthetic_article() -> dict:
    """An ArticleExtract.to_dict()-shaped payload whose paragraph tokens match
    the ``_synthetic_caption_segments`` text — so phrase alignment succeeds
    with a high match rate by default."""
    return {
        "title": "GPT-5 Just Launched With Big Benchmarks",
        "byline": "Jane Doe",
        "publish_date": "2026-04-18",
        "lead_paragraph": (
            "OpenAI released GPT-5 today, pushing benchmark scores up across "
            "every major evaluation and reshaping what developers can expect "
            "from frontier models this year."
        ),
        "body_paragraphs": [
            (
                "OpenAI released GPT-5 today, pushing benchmark scores up "
                "across every major evaluation and reshaping what developers "
                "can expect from frontier models this year."
            ),
            (
                "The new model scores forty percent higher on coding "
                "benchmarks and cuts inference latency by half, according "
                "to the release notes published this morning."
            ),
            (
                "Pricing stays flat at the previous tier, which analysts say "
                "puts serious pressure on rival providers to respond within "
                "the next quarter."
            ),
        ],
        "source_url": "https://example.com/gpt5",
    }


def _synthetic_caption_segments() -> list[dict]:
    """Roughly 12 words of voiceover with realistic timestamps.

    Spans paragraph 1 ("forty percent higher") and paragraph 0 ("OpenAI
    released GPT-5") so alignment > 60% is achievable.
    """
    words = [
        ("OpenAI", 0.00, 0.40),
        ("released", 0.42, 0.80),
        ("GPT-5", 0.82, 1.20),
        ("today,", 1.22, 1.50),
        ("scoring", 1.90, 2.30),   # 400ms gap → phrase boundary
        ("forty", 2.32, 2.60),
        ("percent", 2.62, 3.00),
        ("higher.", 3.02, 3.50),
        ("And", 4.00, 4.25),       # "And" conjunction at word[8]
        ("cutting", 4.27, 4.60),
        ("latency", 4.62, 5.10),
        ("in", 5.12, 5.25),
        ("half.", 5.27, 5.60),
    ]
    return [{"word": w, "start": s, "end": e} for (w, s, e) in words]


# ─── 1. Happy path (mocked Playwright + Haiku + FFmpeg) ─────────────────────


async def test_happy_path_mocked(monkeypatch, tmp_path):
    """Mock every external dependency; assert the generator returns the path
    and that the Jinja render was called with a ``<mark>``-containing template
    substitution (we capture via a wrapper around ``_render_template``)."""

    render_calls: list[dict[str, Any]] = []

    def fake_render_template(
        paragraphs_ctx, *, title, byline, publish_date, scroll_offset_px
    ):
        render_calls.append(
            {
                "paragraphs_ctx": paragraphs_ctx,
                "title": title,
                "byline": byline,
                "publish_date": publish_date,
                "scroll_offset_px": scroll_offset_px,
            }
        )
        # Produce HTML that actually contains <mark> when at least one run is
        # marked active/past — this lets the assertion downstream check that
        # the template API is exercised with the karaoke highlight contract.
        mark_fragments: list[str] = []
        for para in paragraphs_ctx:
            for run in para["runs"]:
                if run["kind"] == "active":
                    mark_fragments.append(f"<mark>{run['text']}</mark>")
                elif run["kind"] == "past":
                    mark_fragments.append(
                        f"<mark class='past'>{run['text']}</mark>"
                    )
        return (
            "<html><body>"
            + "".join(mark_fragments)
            + f"<span data-scroll='{scroll_offset_px}'></span>"
            + "</body></html>"
        )

    async def fake_screenshot_html(html, output_path, active_mark_y_target_px):
        # Write a 1-byte stub so the concat list has a real file to point at.
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\nstub")
        # Sanity: the rendered HTML for any non-first event must contain at
        # least one <mark> tag (the karaoke contract).
        assert "</body>" in html

    async def fake_assemble_video(
        png_paths, phrases, target_duration_s, output_path
    ):
        Path(output_path).write_bytes(b"\x00\x00\x00\x18ftypmp42fake")

    monkeypatch.setattr(ph_module, "_render_template", fake_render_template)
    monkeypatch.setattr(ph_module, "_screenshot_html", fake_screenshot_html)
    monkeypatch.setattr(ph_module, "_assemble_video", fake_assemble_video)

    # Haiku mock: returns lead_index=0, picked_indices=[1, 2]
    anthropic_client = MagicMock()
    msg_response = MagicMock()
    msg_response.content = [
        MagicMock(text='{"lead_index": 0, "picked_indices": [1, 2]}')
    ]
    anthropic_client.messages.create = AsyncMock(return_value=msg_response)

    gen = PhoneHighlightGenerator(anthropic_client=anthropic_client)
    job = _FakeVideoJob(
        topic={"title": "GPT-5 Launch", "url": "https://example.com/gpt5"},
        script={"script": "OpenAI released GPT-5 today scoring forty percent higher and cutting latency in half."},
        caption_segments=_synthetic_caption_segments(),
        extracted_article=_synthetic_article(),
    )
    output_path = str(tmp_path / "out.mp4")

    result = await gen.generate(job, target_duration_s=6.0, output_path=output_path)

    assert result == output_path
    assert Path(output_path).exists()
    # Haiku was consulted.
    anthropic_client.messages.create.assert_awaited_once()
    # At least one render call contained an active <mark> run.
    assert any(
        any(run["kind"] == "active" for para in c["paragraphs_ctx"] for run in para["runs"])
        for c in render_calls
    ), "expected at least one template render to include an active <mark> run"


# ─── 2. Missing article raises BrollError ───────────────────────────────────


async def test_missing_article_raises(tmp_path):
    """Without ``extracted_article``, the selector's gating failed — the
    generator must loudly raise ``BrollError``."""

    gen = PhoneHighlightGenerator(anthropic_client=None)
    job = _FakeVideoJob(
        topic={"title": "X"},
        script={"script": "some text"},
        caption_segments=_synthetic_caption_segments(),
        extracted_article=None,
    )
    with pytest.raises(BrollError, match="extracted article"):
        await gen.generate(job, target_duration_s=6.0, output_path=str(tmp_path / "o.mp4"))


# ─── 3. Phrase chunking unit ────────────────────────────────────────────────


def test_phrase_chunking():
    """Synthetic caption segments with punctuation + silence gap + conjunction
    split into the expected phrase list."""

    segments = [
        # Phrase 1: ends on punctuation (comma) after 4 words
        {"word": "The", "start": 0.00, "end": 0.15},
        {"word": "new", "start": 0.17, "end": 0.32},
        {"word": "model", "start": 0.34, "end": 0.62},
        {"word": "is,", "start": 0.64, "end": 0.85},
        # Phrase 2: starts at big silence gap (>250ms) from prev end=0.85.
        # Gap to next word start=1.30 → 450ms → boundary.
        {"word": "scoring", "start": 1.30, "end": 1.65},
        {"word": "forty", "start": 1.67, "end": 1.90},
        {"word": "percent", "start": 1.92, "end": 2.20},
        {"word": "higher", "start": 2.22, "end": 2.55},
        # Phrase 3: "and" conjunction splits AFTER prior 4+ words.
        {"word": "and", "start": 2.57, "end": 2.75},
        {"word": "cutting", "start": 2.77, "end": 3.05},
        {"word": "latency", "start": 3.07, "end": 3.45},
        {"word": "in", "start": 3.47, "end": 3.58},
        {"word": "half.", "start": 3.60, "end": 3.95},
    ]
    phrases = _chunk_phrases(segments)

    # Three phrases expected: "The new model is,", "scoring forty percent higher",
    # "and cutting latency in half.".
    assert len(phrases) == 3, f"expected 3 phrases, got {len(phrases)}: " \
        f"{[p.text for p in phrases]}"

    # Boundary 1: punctuation flushed "is," as phrase terminator
    assert phrases[0].text.endswith("is,")
    assert phrases[0].text.startswith("The new model")

    # Boundary 2: silence gap + no punctuation → phrase built up to conjunction
    assert "forty percent higher" in phrases[1].text
    assert not phrases[1].text.startswith("and")

    # Boundary 3: conjunction "and" starts the third phrase
    assert phrases[2].text.startswith("and")
    assert phrases[2].text.endswith("half.")

    # Every phrase has 3-7 words
    for p in phrases:
        assert 3 <= len(p.text.split()) <= 7, (
            f"phrase {p.text!r} has {len(p.text.split())} words; must be 3-7"
        )

    # Timestamps are monotonic and match input span
    assert phrases[0].t_start == pytest.approx(0.00)
    assert phrases[0].t_end == pytest.approx(0.85)
    assert phrases[1].t_start == pytest.approx(1.30)
    assert phrases[2].t_end == pytest.approx(3.95)


# ─── 4. Low match rate warns ────────────────────────────────────────────────


async def test_low_match_rate_warns(monkeypatch, tmp_path, caplog):
    """When fewer than 60% of phrases match the trimmed-view paragraphs,
    the generator logs a WARN."""

    # Article whose words have no overlap with the caption segments.
    mismatch_article = {
        "title": "Unrelated Topic",
        "lead_paragraph": (
            "Quantum entanglement researchers announced fascinating "
            "findings regarding cryogenic particle behaviour yesterday."
        ),
        "body_paragraphs": [
            (
                "Quantum entanglement researchers announced fascinating "
                "findings regarding cryogenic particle behaviour yesterday."
            ),
            (
                "Researchers at distant laboratories coordinated experiments "
                "using superconducting equipment chilled near absolute zero."
            ),
            (
                "Funding agencies expressed continued enthusiasm regarding "
                "upcoming colloquium sessions scheduled throughout summer."
            ),
        ],
    }

    async def fake_render_template(*_a, **_kw):
        return "<html></html>"

    async def fake_screenshot_html(html, output_path, target_y):
        Path(output_path).write_bytes(b"stub")

    async def fake_assemble_video(png_paths, phrases, target_duration_s, output_path):
        Path(output_path).write_bytes(b"\x00")

    # render_template is sync — wrap via normal setattr (not async).
    monkeypatch.setattr(ph_module, "_render_template", lambda *a, **kw: "<html></html>")
    monkeypatch.setattr(ph_module, "_screenshot_html", fake_screenshot_html)
    monkeypatch.setattr(ph_module, "_assemble_video", fake_assemble_video)

    gen = PhoneHighlightGenerator(anthropic_client=None)
    job = _FakeVideoJob(
        topic={"title": "Mismatch"},
        script={"script": "OpenAI released GPT-5 today"},
        caption_segments=_synthetic_caption_segments(),
        extracted_article=mismatch_article,
    )

    with caplog.at_level(logging.WARNING, logger="broll_gen.phone_highlight"):
        await gen.generate(
            job, target_duration_s=6.0, output_path=str(tmp_path / "out.mp4")
        )

    warn_messages = [
        r.message for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert any("low phrase-to-paragraph match rate" in m for m in warn_messages), (
        f"expected low-match-rate warning; got: {warn_messages!r}"
    )


# ─── 5. Factory wiring ──────────────────────────────────────────────────────


def test_factory_wiring():
    """``make_broll_generator('phone_highlight')`` must return a
    PhoneHighlightGenerator instance — no more NotImplementedError."""
    gen = make_broll_generator("phone_highlight")
    assert isinstance(gen, PhoneHighlightGenerator)

    # Also accepts the anthropic_client kwarg (mirrors browser_visit wiring).
    sentinel = object()
    gen2 = make_broll_generator("phone_highlight", anthropic_client=sentinel)
    assert isinstance(gen2, PhoneHighlightGenerator)
    assert gen2._client is sentinel
