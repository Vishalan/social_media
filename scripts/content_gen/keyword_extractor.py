"""Unit A3 — Haiku-based keyword-punch extractor with drift guard.

Given a short-form script and the Whisper-transcribed ``caption_segments``
(on the trimmed-audio clock — Tier 0 invariant), ask Claude Haiku for the
4–7 highest-value tokens that deserve a visual emphasis punch, then
**drift-guard** each keyword against the real caption timeline.

The drift guard is critical: Haiku occasionally hallucinates words that
never appear in the final transcript (domain-term mismatch, optimistic
rewording). If a keyword has no case-insensitive match in
``caption_segments``, it is DROPPED and a ``WARN`` is logged — never
emitted as a zoom-punch landing on empty silence.

Public surface:

* :class:`KeywordPunch` — ``NamedTuple(word, t_start, t_end, intensity)``.
* :func:`extract_keyword_punches` — async Haiku + drift-guard + shape check.

The returned timestamps live on the **trimmed-audio clock**, inherited
verbatim from ``caption_segments`` (no re-resolution). Callers feed the
result to the combined ``_apply_engagement_pass`` ffmpeg pass which maps
them onto zoompan bell curves; see ``video_edit/video_editor.py``.
"""

from __future__ import annotations

import json
import logging
from typing import Iterable, Literal, NamedTuple, Optional

__all__ = [
    "KeywordPunch",
    "KeywordIntensity",
    "extract_keyword_punches",
]

logger = logging.getLogger(__name__)

# ─── Types ────────────────────────────────────────────────────────────────────

KeywordIntensity = Literal["light", "medium", "heavy"]
_VALID_INTENSITIES: frozenset[str] = frozenset({"light", "medium", "heavy"})
_DEFAULT_INTENSITY: KeywordIntensity = "medium"


class KeywordPunch(NamedTuple):
    """One keyword-punch event in trimmed-audio time.

    ``t_start`` / ``t_end`` come verbatim from the matched
    ``caption_segments`` entry — they are NEVER re-resolved via any other
    clock. This preserves the Tier 0 invariant that all engagement-layer
    signals share the same timeline as the caption track.
    """

    word: str
    t_start: float
    t_end: float
    intensity: KeywordIntensity


# ─── Haiku prompt ─────────────────────────────────────────────────────────────

_HAIKU_SYSTEM = """\
You identify the 4–7 highest-value tokens in a short-form video script \
that deserve a visual emphasis punch (a ~1.15x zoom over ~200 ms).

Prefer, in order:
  1. Proper nouns — model names, company names, product names.
  2. Dollar figures and round monetary amounts.
  3. Percentages and ratios ("40%", "3x faster").
  4. Version numbers ("GPT-5", "Claude 4.6", "v2.3").
  5. Specific metrics ("82 tokens/sec", "128k context").

Return ONLY a JSON array. Each element is an object with:
  - "word": the exact token as written in the script (case and punctuation preserved).
  - "intensity": one of "light", "medium", "heavy".

Intensity rubric:
  - "heavy": a headline reveal (new model name, huge number).
  - "medium": a notable stat or comparison.
  - "light": a supporting proper noun.

Emit NO keys beyond "word" and "intensity". Do not wrap the array in \
any enclosing object. Do not emit markdown fences. 4 to 7 items total."""


_MAX_RESPONSE_TOKENS = 512
_HAIKU_MODEL = "claude-haiku-4-5"


# ─── Public API ──────────────────────────────────────────────────────────────


async def extract_keyword_punches(
    script_text: str,
    caption_segments: list[dict],
    anthropic_client=None,
) -> list[KeywordPunch]:
    """Extract keyword-punch events from a script + its Whisper captions.

    Failure isolation: this function NEVER raises. All paths return a list
    (possibly empty). Haiku / parsing / drift-guard failures are logged at
    ``WARN`` and degrade to an empty result so the surrounding pipeline can
    continue without zoom-punches.

    Args:
        script_text: The raw voiceover script.
        caption_segments: Whisper-emitted word segments, each shaped
            ``{"word": str, "start": float, "end": float}``. Already on the
            trimmed-audio clock.
        anthropic_client: An ``AsyncAnthropic``-shaped client (anything
            exposing ``.messages.create(...)`` that returns a response with
            ``.content[0].text`` containing a JSON array). If ``None``, the
            function returns ``[]`` without calling the API — useful for
            tests and dry-runs.

    Returns:
        A list of ``KeywordPunch`` in ``caption_segments`` order, filtered
        by the drift guard. Empty if Haiku fails, the script is empty, or
        no emitted word survives the guard.
    """
    if not script_text or not script_text.strip():
        return []
    if anthropic_client is None:
        logger.info(
            "keyword_extractor: no anthropic_client supplied — returning []"
        )
        return []
    if not caption_segments:
        # Even if Haiku returned tokens, none could survive the drift guard.
        logger.info("keyword_extractor: empty caption_segments — returning []")
        return []

    # 1. Ask Haiku.
    raw_tokens = await _ask_haiku(anthropic_client, script_text)
    if not raw_tokens:
        return []

    # 2. Build a case-insensitive index of caption words → (index, start, end).
    # Stored as a list so we can match trailing-punctuation variants.
    caption_index: list[tuple[str, float, float]] = []
    for seg in caption_segments:
        w = seg.get("word", "")
        if not isinstance(w, str):
            continue
        w_clean = w.strip().lower().rstrip(".,!?;:\"'")
        if not w_clean:
            continue
        caption_index.append((w_clean, float(seg["start"]), float(seg["end"])))

    # 3. Drift-guard each token.
    punches: list[KeywordPunch] = []
    for tok in raw_tokens:
        word = tok.get("word", "")
        if not isinstance(word, str) or not word.strip():
            logger.warning(
                "keyword_extractor: drift drop — invalid/empty word %r",
                word,
            )
            continue
        needle = word.strip().lower().rstrip(".,!?;:\"'")
        match = _find_match(needle, caption_index)
        if match is None:
            logger.warning(
                "keyword_extractor: drift drop — %r not found in captions",
                word,
            )
            continue

        intensity = tok.get("intensity", _DEFAULT_INTENSITY)
        if intensity not in _VALID_INTENSITIES:
            logger.info(
                "keyword_extractor: normalising unknown intensity %r → %s",
                intensity, _DEFAULT_INTENSITY,
            )
            intensity = _DEFAULT_INTENSITY

        t_start, t_end = match
        punches.append(
            KeywordPunch(
                word=word.strip(),
                t_start=t_start,
                t_end=t_end,
                intensity=intensity,  # type: ignore[arg-type]
            )
        )

    # 4. Sort by t_start so the downstream zoompan sum is monotonic.
    punches.sort(key=lambda p: p.t_start)
    return punches


# ─── Internals ───────────────────────────────────────────────────────────────


async def _ask_haiku(client, script_text: str) -> list[dict]:
    """Call Haiku; return the parsed JSON list or ``[]`` on any failure."""
    user_prompt = f"Script:\n{script_text.strip()}"
    try:
        response = await client.messages.create(
            model=_HAIKU_MODEL,
            max_tokens=_MAX_RESPONSE_TOKENS,
            system=_HAIKU_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        logger.warning(
            "keyword_extractor: Haiku call failed (%s) — returning []",
            exc,
        )
        return []

    try:
        raw = response.content[0].text
    except (AttributeError, IndexError) as exc:
        logger.warning(
            "keyword_extractor: malformed Haiku response (%s) — returning []",
            exc,
        )
        return []

    parsed = _parse_json_array(raw)
    if parsed is None:
        logger.warning(
            "keyword_extractor: could not parse Haiku JSON %r — returning []",
            raw[:200],
        )
        return []
    if not isinstance(parsed, list):
        logger.warning(
            "keyword_extractor: Haiku returned non-list %r — returning []",
            type(parsed).__name__,
        )
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _parse_json_array(raw: str) -> Optional[object]:
    """Parse ``raw`` as JSON, tolerating wrapping backticks / prose.

    Haiku sometimes emits ```json\n[...]\n``` despite the instruction to
    skip fences. We strip common wrappers then ``json.loads`` once.
    """
    if not raw:
        return None
    text = raw.strip()
    # Strip triple-backtick fences (with or without language hint).
    if text.startswith("```"):
        # Drop everything up to the first newline, then drop trailing ```.
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[: -3]
        text = text.strip()
    # If prose precedes the JSON array, find the first '[' and the last ']'.
    if not text.startswith("["):
        lo = text.find("[")
        hi = text.rfind("]")
        if lo == -1 or hi == -1 or hi <= lo:
            return None
        text = text[lo : hi + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _find_match(
    needle: str,
    caption_index: list[tuple[str, float, float]],
) -> Optional[tuple[float, float]]:
    """Return the ``(start, end)`` of the first caption word matching ``needle``.

    Matching is case-insensitive and punctuation-insensitive (both sides
    already ``strip().lower().rstrip(".,!?;:\"'")``). Multi-token needles
    ("gpt-5", "40%") match against the normalised caption tokens as-is —
    Whisper generally emits them as single tokens with punctuation baked
    onto the adjacent word.
    """
    for word, t_start, t_end in caption_index:
        if word == needle:
            return t_start, t_end
    # Fall back: if the needle is a substring of a caption word (e.g.
    # "40%" → caption "40%,"), the earlier rstrip already stripped the
    # trailing comma so this path is rarely hit. Kept for robustness.
    for word, t_start, t_end in caption_index:
        if needle and (needle in word or word in needle):
            return t_start, t_end
    return None
