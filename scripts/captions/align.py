"""Align ASR word timings onto the ground-truth script.

The pipeline transcribes its own synthesised narration to get word-level
timings for captions. That is the right way to get TIMING and the wrong way to
get TEXT: we already know exactly what was said, because we wrote it.

Trusting the transcript put three visible errors into a published video:

    script says "GPT-5.6 Sol"      -> Whisper heard "GPT-5.6 sold"
    script says "John Crepezzi"    -> Whisper heard "John Krapidze"
    script says "Ultrafast"        -> Whisper heard "UltraFast"

Proper nouns are exactly where ASR fails and exactly where being wrong is most
damaging — misspelling a real person at a real firm, on screen, under the
owner's own face.

This module keeps Whisper's timings and replaces its words with the script's,
using a standard sequence alignment so insertions, deletions and substitutions
all land on sensible timestamps.
"""
from __future__ import annotations

import difflib
import logging
import re
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

_NORM_RE = re.compile(r"[^a-z0-9]+")


def _norm(word: str) -> str:
    """Fold to a comparison key: lowercase, strip punctuation and spacing."""
    return _NORM_RE.sub("", word.lower())


def _script_words(script: str) -> list[str]:
    return [w for w in re.split(r"\s+", script.strip()) if w]


def align_words(
    asr_words: list[dict],
    script: str,
    *,
    report: bool = True,
) -> list[dict]:
    """Return script words carrying ASR timings.

    Args:
        asr_words: [{"word", "start", "end"}, ...] from faster-whisper.
        script: the narration text that was actually synthesised.
        report: log a summary of substitutions made.

    Returns:
        A list in SCRIPT order, each entry {"word", "start", "end"}. Where the
        alignment is ambiguous, timings are interpolated across the span so
        cues never overlap or run backwards.
    """
    if not asr_words:
        return []
    target = _script_words(script)
    if not target:
        return list(asr_words)

    a_keys = [_norm(w["word"]) for w in asr_words]
    b_keys = [_norm(w) for w in target]

    matcher = difflib.SequenceMatcher(a=a_keys, b=b_keys, autojunk=False)
    out: list[Optional[dict]] = [None] * len(target)
    subs: list[tuple[str, str]] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(j2 - j1):
                out[j1 + k] = {
                    "word": target[j1 + k],
                    "start": asr_words[i1 + k]["start"],
                    "end": asr_words[i1 + k]["end"],
                }
        elif tag in ("replace", "delete", "insert"):
            # Spread the ASR span for this region evenly across the script
            # words it corresponds to. For a pure insert (ASR missed words
            # entirely) borrow a zero-width span from the neighbouring word.
            span = asr_words[i1:i2]
            if span:
                t0, t1 = span[0]["start"], span[-1]["end"]
            else:
                prev_end = asr_words[i1 - 1]["end"] if i1 > 0 else 0.0
                t0 = t1 = prev_end
            n = max(1, j2 - j1)
            step = (t1 - t0) / n if t1 > t0 else 0.0
            for k in range(j2 - j1):
                out[j1 + k] = {
                    "word": target[j1 + k],
                    "start": round(t0 + step * k, 3),
                    "end": round(t0 + step * (k + 1), 3) if step else t1,
                }
            if tag == "replace":
                heard = " ".join(w["word"] for w in span)
                said = " ".join(target[j1:j2])
                if _norm(heard) != _norm(said):
                    subs.append((heard, said))

    # Any word the alignment could not place at all — should be rare — gets a
    # zero-width slot after its predecessor rather than being dropped.
    last_end = 0.0
    for idx, item in enumerate(out):
        if item is None:
            out[idx] = {"word": target[idx], "start": last_end, "end": last_end}
        last_end = out[idx]["end"]

    if report and subs:
        logger.info("Caption alignment corrected %d ASR error(s):", len(subs))
        for heard, said in subs[:12]:
            logger.info("    heard %-28r -> script %r", heard, said)

    return [w for w in out if w is not None]


def group_cues(
    words: list[dict],
    *,
    per_cue: int = 3,
    max_chars: int = 28,
) -> list[tuple[float, float, str]]:
    """Group aligned words into caption cues.

    Caps both word count and character count so a cue never wraps — a wrapped
    caption costs a second eye fixation, which is the whole thing short-form
    captions exist to avoid.
    """
    cues: list[tuple[float, float, str]] = []
    i = 0
    while i < len(words):
        grp = [words[i]]
        j = i + 1
        while j < len(words) and len(grp) < per_cue:
            candidate = " ".join(w["word"] for w in grp + [words[j]])
            if len(candidate) > max_chars:
                break
            grp.append(words[j])
            j += 1
        text = " ".join(w["word"] for w in grp).strip()
        cues.append((grp[0]["start"], grp[-1]["end"], text))
        i = j
    return cues
