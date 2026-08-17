"""Karaoke-highlight article b-roll — adapter onto the existing generator.

`broll_gen.phone_highlight` already does exactly what a reading-focused b-roll
needs: it renders the source article in a phone mockup, wraps the
currently-spoken phrase in a highlight, dims phrases already spoken, and
auto-scrolls so the active phrase sits about a third down the viewport. It was
written for the CommonCreed channel and never wired into this pipeline; this
module adapts it rather than reimplementing it.

Two things the adapter has to supply:

* a ``VideoJob``-shaped object — the generator expects ``extracted_article``,
  ``caption_segments`` and ``script`` attributes.
* the story's palette — the generator defaulted to CommonCreed navy and sky
  blue, which would drag one channel's brand into another channel's video.

The scroll-and-highlight is the point. Plain page scrolling gives the viewer
nothing to read *to*; a moving highlight tells them which words matter and
paces them through it.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class HighlightError(RuntimeError):
    """Raised when highlight b-roll cannot be produced."""


@dataclass
class _JobShim:
    """Minimal stand-in for the pipeline's VideoJob.

    The generator reads four attributes off the job and nothing else, so a
    shim is honest here — inheriting the real VideoJob would drag in the whole
    CommonCreed pipeline for four fields.
    """
    extracted_article: dict
    caption_segments: list
    script: dict
    topic: dict = field(default_factory=dict)



def _load_generator():
    """Load phone_highlight WITHOUT executing broll_gen/__init__.py.

    That package's __init__ imports its factory, which imports ai_video, which
    imports the ComfyUI client — a GPU-video dependency chain this pipeline has
    no use for. Loading the two modules by path keeps the borrow narrow: the
    only thing adopted is the generator itself.
    """
    import importlib.util
    import sys

    pkg_dir = Path(__file__).resolve().parent.parent / "broll_gen"
    if not pkg_dir.exists():
        raise HighlightError(f"broll_gen not found at {pkg_dir}")

    def _load(name: str, path: Path):
        if name in sys.modules:
            return sys.modules[name]
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise HighlightError(f"cannot load {path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod

    # phone_highlight does `from .base import ...`, so a real package entry has
    # to exist for the relative import to resolve — but an EMPTY one, not the
    # repo's __init__ with its factory imports.
    if "_bg" not in sys.modules:
        import types
        pkg = types.ModuleType("_bg")
        pkg.__path__ = [str(pkg_dir)]           # type: ignore[attr-defined]
        sys.modules["_bg"] = pkg
    base = _load("_bg.base", pkg_dir / "base.py")
    ph = _load("_bg.phone_highlight", pkg_dir / "phone_highlight.py")
    return ph.PhoneHighlightGenerator, ph.set_palette, base.BrollError


def _paragraphs(text: str, *, min_len: int = 90, max_paras: int = 14,
                title_hint: str = "") -> list[str]:
    """Split source text into article-like paragraphs.

    Extraction gives one long block with newlines; the generator wants
    paragraph units. Short lines are dropped: on a news page they are bylines,
    image credits, nav labels and share prompts, not body copy.
    """
    raw = [p.strip() for p in re.split(r"\n{1,}", text) if p.strip()]
    out = [p for p in raw if len(p) >= min_len]
    # Extraction repeats the headline as the first text block, so the mockup
    # showed the title twice — once as the heading and again as body copy.
    # Drop any paragraph that is substantially the title.
    if out and title_hint:
        t = re.sub(r"\W+", "", title_hint.lower())[:60]
        out = [p for p in out
               if not (t and re.sub(r"\W+", "", p.lower())[:60] == t)]
    return out[:max_paras]


async def build_highlight_clip(*, source_text: str, source_title: str,
                         script: dict, words: list[dict], out_path: str,
                         duration_s: float, palette: Optional[list[str]] = None,
                         intelligence: Any = None, focus_paragraph: int = -1,
                         width: int = 1080, height: int = 1920) -> str:
    """Render one karaoke-highlight clip covering ``duration_s`` of narration.

    Args:
        source_text: extracted article body.
        source_title: article headline, shown in the mockup.
        script: the script dict (the generator reads ``script["script"]``).
        words: aligned word timings — ``[{"word", "start", "end"}]``.
        duration_s: how much narration this clip should cover.
        palette: the story's colours; index 2 is used as the highlight when
            available, matching how the design renderer picks its accent.
        intelligence: optional Anthropic-shaped client. With one, the generator
            asks which paragraphs are most relevant to the script; without, it
            falls back to lead-plus-two.
    """
    PhoneHighlightGenerator, set_palette, BrollError = _load_generator()

    paras = _paragraphs(source_text, title_hint=source_title)
    if len(paras) < 2:
        raise HighlightError(
            f"only {len(paras)} usable paragraphs in the source — "
            f"not enough body copy for a reading b-roll")

    if palette:
        highlight = palette[2] if len(palette) > 2 else palette[-1]
        # Paper/ink are chosen for contrast against the highlight rather than
        # taken from the palette wholesale: a story palette's first colour is
        # often near-black, and near-black paper with a dark highlight is
        # unreadable at phone size.
        set_palette(highlight=highlight, ink="#0B0D11", paper="#FFFFFF")
        logger.info("Highlight palette: %s on white", highlight)

    # The generator trims the article to lead-plus-two before rendering, so a
    # sentence living in paragraph 10 is highlighted on a view that does not
    # contain it — the highlight then matches nothing and the clip is a plain
    # scroll with a warning. Promote the focus paragraph into the visible set.
    if 0 <= focus_paragraph < len(paras):
        lead = paras[focus_paragraph]
        rest = [p for i, p in enumerate(paras) if i != focus_paragraph]
        logger.info("Focusing paragraph %d so the highlighted sentence is "
                    "on screen", focus_paragraph)
    else:
        lead, rest = paras[0], paras[1:]

    job = _JobShim(
        extracted_article={
            "title": source_title[:140],
            "byline": "",
            "publish_date": "",
            "lead_paragraph": lead,
            "body_paragraphs": rest,
        },
        caption_segments=words,
        script=script,
        topic={"title": source_title[:140]},
    )

    gen = PhoneHighlightGenerator(anthropic_client=intelligence)
    try:
        # await, not asyncio.run(): callers are already inside a loop, and
        # asyncio.run() from within one raises.
        return await gen.generate(job, duration_s, out_path)
    except BrollError as exc:
        raise HighlightError(str(exc)) from exc


def slice_words(words: list[dict], start: float, end: float) -> list[dict]:
    """Words falling inside a time window, re-based to start at zero.

    The generator times its highlight from the clip's own zero, so a window
    lifted from the middle of the narration has to be shifted back or every
    highlight fires late by the window's offset.
    """
    out = []
    for w in words:
        if w["start"] >= start and w["end"] <= end:
            out.append({"word": w["word"],
                        "start": round(w["start"] - start, 3),
                        "end": round(w["end"] - start, 3)})
    return out

# --------------------------------------------------------------------------
# Semantic alignment
#
# The generator matches script phrases against article text LEXICALLY. That
# suited the pipeline it was written for, where the script tracked the article
# closely. These scripts are written for the ear and paraphrase heavily, so a
# real run matched 33% of phrases and highlighted "details. That" — a fragment
# straddling a sentence boundary, which is worse than no highlight.
#
# The fix inverts the input. Rather than hoping the script's words appear in the
# article, ask which article SENTENCE the narration beat is about, then hand the
# generator that sentence's own words as the phrases to highlight. The match is
# then 100% by construction, and the highlight walks the sentence a viewer
# should be reading while they hear the paraphrase of it.
# --------------------------------------------------------------------------

_SENTENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "paragraph": {"type": "integer"},
        "sentence": {"type": "string"},
        "why": {"type": "string"},
    },
    "required": ["paragraph", "sentence"],
}


async def pick_sentence(*, paragraphs: list[str], narration: str,
                        intelligence: Any) -> Optional[tuple[int, str]]:
    """Choose the article sentence a narration beat is discussing.

    Returns (paragraph_index, sentence) or None when nothing fits — a wrong
    sentence highlighted under confident narration is worse than a plain
    scroll.
    """
    numbered = "\n".join(f"[{i}] {p}" for i, p in enumerate(paragraphs))
    prompt = (
        f"ARTICLE PARAGRAPHS:\n{numbered}\n\n"
        f"NARRATION AT THIS MOMENT:\n\"{narration}\"\n\n"
        f"Which single sentence from the article is this narration describing? "
        f"Copy it VERBATIM from the paragraph — do not paraphrase or trim it. "
        f"If no sentence genuinely corresponds, set sentence to an empty string."
    )
    try:
        resp = await intelligence.messages.create(
            model="claude-sonnet-4-5", max_tokens=600,
            system=("You align spoken narration to the source sentence it came "
                    "from. Reply with JSON only."),
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema",
                                      "schema": _SENTENCE_SCHEMA}},
        )
        import json as _json
        data = _json.loads(resp.content[0].text)
    except Exception as exc:                       # noqa: BLE001 — optional
        logger.warning("sentence alignment failed: %s", str(exc)[:160])
        return None

    sent = (data.get("sentence") or "").strip()
    idx = int(data.get("paragraph", 0))
    if not sent or not (0 <= idx < len(paragraphs)):
        return None
    # Verify the model actually quoted rather than paraphrased: a sentence it
    # invented will not appear in the paragraph, and highlighting words that
    # are not on screen silently does nothing.
    if sent[:40].lower() not in paragraphs[idx].lower():
        logger.warning("aligned sentence is not verbatim in paragraph %d — "
                       "ignoring", idx)
        return None
    logger.info("beat aligned to paragraph %d: %r", idx, sent[:70])
    return idx, sent


def synth_phrases(sentence: str, duration_s: float, *,
                  words_per_group: int = 3) -> list[dict]:
    """Turn a sentence into word timings that sweep across the clip.

    Timings are even rather than speech-derived: the highlight is pacing the
    viewer's reading, not tracking the audio word for word.

    Deliberate detail — a gap of at least _SILENCE_GAP_SECONDS (0.25s) is
    inserted every ``words_per_group`` words. The generator chunks phrases at
    punctuation, conjunctions, or silence gaps, so a 20-word sentence with no
    internal punctuation became FOUR phrases and the highlight sat almost
    still for six seconds. The synthetic gaps force it to emit a phrase every
    few words, which is what makes the highlight actually travel.
    """
    words = [w for w in re.split(r"\s+", sentence.strip()) if w]
    if not words:
        return []

    gap = 0.26                       # just over the generator's 0.25s threshold
    n_groups = max(1, (len(words) + words_per_group - 1) // words_per_group)
    # Hold the final group briefly so the sentence does not vanish on landing.
    usable = max(0.5, duration_s - 0.5) - gap * (n_groups - 1)
    per_word = usable / len(words)

    out: list[dict] = []
    t = 0.0
    for i, w in enumerate(words):
        if i and i % words_per_group == 0:
            t += gap                 # boundary the chunker will split on
        out.append({"word": w, "start": round(t, 3),
                    "end": round(t + per_word, 3)})
        t += per_word
    return out
