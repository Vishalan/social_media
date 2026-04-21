"""Keyword-punch detection from word-level caption segments.

Plan Key Decision #10 calls for "SFX-flash on keyword-punch" — a
short high-impact sound cue synchronized to the word the narrator
emphasizes. Since the Archivist writer produces prose (not JSON with
emphasis markers) and chatterbox doesn't tag stress, we detect
punches heuristically from the caption segments faster-whisper
produces. The heuristic is deliberately conservative — better to
miss a punch than plant a cue on the wrong word.

Punch detection rules (in order):
  1. **Capitalized mid-sentence words.** Proper nouns + emphasized
     all-caps words ("HE stared at me"). Excludes sentence-initial
     words since those are capitalized for grammar, not emphasis.
  2. **Long content words.** Words ≥8 chars that aren't sentence-
     initial and aren't common stopwords — these carry more weight
     in a sparse Archivist register ("whispered", "silhouette",
     "remembered").
  3. **Punctuation-adjacent words.** Words immediately before a
     period or ellipsis — the end-of-sentence beat is a natural
     punch moment in horror narration.

Density cap: no more than one punch per 2 seconds, and no more than
~1 punch per 12 words overall. Keeps the audio track from feeling
pinball-machine busy.

All three heuristics pay the same cost as a dict lookup — no LLM
calls, no external services. Runs O(N) on word count.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Sequence, Set

logger = logging.getLogger(__name__)


# Frequent function words that shouldn't fire the "long word" rule
# even if they're ≥ 8 chars (there aren't many, but "suddenly",
# "actually", "literally" all trend toward filler in prose generated
# from LLM writers; dropping them keeps punches rare + deliberate).
_STOPLIKE_LONG = frozenset({
    "actually", "literally", "suddenly", "basically", "generally",
    "eventually", "obviously", "probably", "everything", "something",
    "anything", "someone", "somebody", "anybody", "everywhere",
})

# Words that punctuate the sentence end — any word ending in one of
# these triggers the punctuation-adjacent rule.
_END_PUNCT = (".", "!", "?", "…")

# Min seconds between consecutive punches.
_MIN_PUNCH_GAP_S = 2.0

# Overall density cap: ~1 punch per N words. Set high enough that a
# 200-word Archivist short produces ~15 candidate punches, which then
# get gap-filtered down to ~6-8.
_MAX_PUNCH_DENSITY = 1 / 12


@dataclass(frozen=True)
class KeywordPunch:
    """A detected emphasis beat. ``word`` is informational; rendering
    code uses ``t_seconds`` to place the cue."""

    t_seconds: float
    word: str
    reason: str  # "capitalized" | "long_word" | "end_of_sentence"


def detect_keyword_punches(
    caption_segments: Sequence[dict],
) -> List[KeywordPunch]:
    """Return the detected punches for ``caption_segments``.

    ``caption_segments`` is the ``[{"word", "start", "end"}, ...]``
    list from :func:`scripts.vesper_pipeline.captions.transcribe_voice`.
    The list may be empty (captions disabled) — this function returns
    an empty list, which the SFX stage treats as a no-op.
    """
    if not caption_segments:
        return []

    candidates: List[KeywordPunch] = []
    prev_end_punct = True  # treat start-of-story as sentence-initial

    for seg in caption_segments:
        raw_word = str(seg.get("word") or "").strip()
        if not raw_word:
            continue
        t_start = float(seg.get("start", 0.0))
        # Is THIS word sentence-initial? (prev token ended a sentence)
        sentence_initial = prev_end_punct
        # Does THIS word END a sentence?
        ends_sentence = raw_word.endswith(_END_PUNCT)
        stripped = raw_word.rstrip("".join(_END_PUNCT) + ",;:-—\"'()[]")

        reason = _classify(stripped, sentence_initial)
        if reason == "end_of_sentence" and not ends_sentence:
            # Defensive — classifier shouldn't return this without
            # punct trigger. Skip.
            reason = None

        if ends_sentence and stripped and len(stripped) >= 4:
            # End-of-sentence emphasis rule fires independently of
            # length/casing — a period always closes a beat.
            reason = reason or "end_of_sentence"

        if reason:
            candidates.append(KeywordPunch(
                t_seconds=round(t_start, 3),
                word=stripped,
                reason=reason,
            ))

        prev_end_punct = ends_sentence

    return _apply_density_cap(candidates, total_words=len(caption_segments))


# ─── Internal helpers ──────────────────────────────────────────────────────


def _classify(stripped: str, sentence_initial: bool) -> str | None:
    """Return the punch reason for ``stripped``, or ``None`` if it
    doesn't qualify. Order of checks matches the rule list in the
    module docstring."""
    if not stripped:
        return None

    # Rule 1: mid-sentence capitalization. Skip sentence-initial
    # words (which are capitalized for grammar, not emphasis).
    if not sentence_initial and stripped[0].isupper():
        # Skip short acronyms (LA, OK) to avoid frequent fires.
        if len(stripped) >= 3:
            return "capitalized"

    # Rule 2: long content word — not stopword, not sentence-initial.
    if (
        not sentence_initial
        and len(stripped) >= 8
        and stripped.lower() not in _STOPLIKE_LONG
    ):
        return "long_word"

    return None


def _apply_density_cap(
    candidates: List[KeywordPunch],
    *,
    total_words: int,
) -> List[KeywordPunch]:
    """Enforce min-gap + global density. Greedy earliest-wins picking.

    With rules producing, say, 15 candidates across 200 words, this
    trims to ~6-8 evenly-spaced punches."""
    if not candidates:
        return []

    max_by_density = max(1, int(total_words * _MAX_PUNCH_DENSITY))

    kept: List[KeywordPunch] = []
    for c in candidates:
        if kept and (c.t_seconds - kept[-1].t_seconds) < _MIN_PUNCH_GAP_S:
            continue
        kept.append(c)
        if len(kept) >= max_by_density:
            break
    return kept


__all__ = ["KeywordPunch", "detect_keyword_punches"]
