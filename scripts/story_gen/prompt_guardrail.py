"""Prompt-injection + output-shape defenses for the story generator.

Two layers:

1. **Input canonicalization** — sanitize untrusted Reddit titles and
   archetype text before they enter the LLM prompt. Delegates to
   ``topic_signal.reddit_story_signal.canonicalize_title`` for shared
   rules (Unicode-tag strip, ANSI CSI strip, etc.) and adds a base64-
   decode pre-pass so smuggled instructions are revealed before prompt
   assembly.

2. **Output-shape validation** — after Claude returns, the response
   must match the expected JSON schema (``archivist_script``,
   ``word_count``, ``setting_tag``, ``flagged_topics``). Any deviation
   triggers a retry or rejects the draft.

Per plan Security Posture S5 + S9 (archetype library guardrail).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Reuse the Reddit canonicalizer for title-level rules.
try:
    from topic_signal.reddit_story_signal import canonicalize_title
except ImportError:  # pragma: no cover
    from scripts.topic_signal.reddit_story_signal import canonicalize_title


# ─── Input canonicalization ─────────────────────────────────────────────────


# Heuristic: long runs of base64-alphabet chars with no natural-text
# properties (no spaces for 40+ chars, ends with = padding or has the
# length-divisible-by-4 property). If matched, we strip and log.
_BASE64_SUSPECT_RE = re.compile(
    r"(?:[A-Za-z0-9+/]{40,}={0,2})"
)


def strip_suspected_base64(text: str) -> str:
    """Remove long base64-looking runs from untrusted input.

    Treated conservatively: we only strip matches that ALSO decode to
    plausible text (mostly ASCII, length-divisible-by-4 or =-padded).
    False positives here (stripping a legitimate base64 ID, though
    Reddit titles virtually never contain one) are safer than false
    negatives that let smuggled instructions through.
    """
    out = text
    for m in _BASE64_SUSPECT_RE.finditer(text):
        candidate = m.group(0)
        try:
            decoded = base64.b64decode(candidate + "=" * ((-len(candidate)) % 4),
                                       validate=False)
            # Heuristic: decoded bytes are mostly printable ASCII
            if decoded and sum(32 <= b < 127 for b in decoded) / len(decoded) > 0.8:
                logger.warning(
                    "prompt_guardrail: stripped suspected base64 payload "
                    "(len=%d, decoded_preview=%r)",
                    len(candidate), decoded[:60],
                )
                out = out.replace(candidate, "[REDACTED]")
        except Exception:
            # Not decodable; leave it alone.
            continue
    return out


def canonicalize_untrusted(text: str) -> str:
    """Full canonicalization for untrusted input entering the LLM prompt."""
    cleaned = canonicalize_title(text)
    cleaned = strip_suspected_base64(cleaned)
    return cleaned


# ─── Archetype-library guardrail (Security Posture S9) ─────────────────────


# Archetype-library injection patterns: seed data is first-party trusted
# today, but a future contributor could plant imperative instructions.
# We scrub at load time so a poisoned archetype can't steer the LLM.
_IMPERATIVE_LEAK_PATTERNS = [
    re.compile(r"\bignore (?:all |the )?previous (?:instructions?|prompt)\b", re.I),
    re.compile(r"\b(?:system|developer) prompt\b", re.I),
    re.compile(r"\balways (?:append|include|start|end) (?:with )?['\"\s]", re.I),
    re.compile(r"https?://", re.I),   # no URLs in archetype voice_patterns
]


def scan_archetype(archetype: Dict[str, Any]) -> List[str]:
    """Return a list of guardrail violations for one archetype.

    Called at archetype-library load time. An empty list means the
    archetype is safe to feed into the LLM prompt. A non-empty list is
    logged and the archetype is excluded from the rotation.
    """
    violations: List[str] = []
    blob = " ".join(
        str(v)
        for v in [
            archetype.get("setting_hint", ""),
            *(archetype.get("key_beats", []) or []),
            *(archetype.get("voice_patterns", []) or []),
        ]
    )
    for pat in _IMPERATIVE_LEAK_PATTERNS:
        if pat.search(blob):
            violations.append(f"imperative-leak pattern {pat.pattern!r}")
    return violations


# ─── Output-shape validation ────────────────────────────────────────────────


# Refusal / meta-leak markers — if these appear in archivist_script,
# the LLM fell back to its safety-training voice and the draft is
# unusable. Retry.
_REFUSAL_MARKERS = [
    re.compile(r"\bi (?:cannot|can't|will not|won't|am unable to)\b", re.I),
    re.compile(r"\bas an ai\b", re.I),
    re.compile(r"\bi'm an? (?:ai|assistant|language model)\b", re.I),
    re.compile(r"\bmy (?:guidelines|instructions|training)\b", re.I),
]


@dataclass(frozen=True)
class OutputShapeResult:
    """Outcome of the output-shape validation pass."""

    ok: bool
    payload: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None


def validate_output_shape(
    raw: str,
    *,
    min_words: int,
    max_words: int,
) -> OutputShapeResult:
    """Parse + validate Claude's JSON response.

    Expected shape (strict):
      {
        "archivist_script": str,
        "word_count": int,
        "setting_tag": str,
        "flagged_topics": list[str]
      }
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return OutputShapeResult(ok=False, reason=f"not valid JSON: {exc}")

    if not isinstance(payload, dict):
        return OutputShapeResult(ok=False, reason="payload is not an object")

    required = {"archivist_script", "word_count", "setting_tag", "flagged_topics"}
    missing = required - payload.keys()
    if missing:
        return OutputShapeResult(ok=False, reason=f"missing fields: {sorted(missing)}")

    extras = set(payload.keys()) - required
    if extras:
        return OutputShapeResult(ok=False, reason=f"unexpected fields: {sorted(extras)}")

    script = payload["archivist_script"]
    if not isinstance(script, str) or not script.strip():
        return OutputShapeResult(ok=False, reason="archivist_script must be non-empty str")

    flagged = payload["flagged_topics"]
    if not isinstance(flagged, list) or not all(isinstance(x, str) for x in flagged):
        return OutputShapeResult(ok=False, reason="flagged_topics must be list[str]")

    setting_tag = payload["setting_tag"]
    if not isinstance(setting_tag, str):
        return OutputShapeResult(ok=False, reason="setting_tag must be str")

    actual_words = len(script.split())
    if not (min_words <= actual_words <= max_words):
        return OutputShapeResult(
            ok=False,
            reason=f"word_count out of bounds: {actual_words} not in [{min_words}, {max_words}]",
        )

    # Refusal / meta-leak check.
    for marker in _REFUSAL_MARKERS:
        if marker.search(script):
            return OutputShapeResult(
                ok=False,
                reason=f"refusal/meta marker matched: {marker.pattern!r}",
            )

    # URL check — the Archivist does not cite URLs.
    if re.search(r"https?://", script, re.I):
        return OutputShapeResult(ok=False, reason="archivist_script contains URL")

    return OutputShapeResult(ok=True, payload=payload)


# ─── Hashing ────────────────────────────────────────────────────────────────


def content_sha256(text: str) -> str:
    """SHA-256 hex digest. Used when logging rejected content so the raw
    text is not persisted (Security Posture S7)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "OutputShapeResult",
    "canonicalize_untrusted",
    "content_sha256",
    "scan_archetype",
    "strip_suspected_base64",
    "validate_output_shape",
]
