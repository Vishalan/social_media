"""Monetization-first mod filter for Vesper story output.

Rejects (or asks for rewrite) stories that trigger YouTube advertiser-
friendly guideline violations or platform-policy risks. Filter is
intentionally *monetization-first*: it rejects things that would
demonetize or get the channel shadow-banned, not just age-gated.

Per plan Unit 7 Approach + Security Posture S7:
  * Rejection logs persist only ``(reason_category, sha256_hash)`` —
    never the raw rejected text. The exception is a debug flag
    ``KEEP_REJECTED_STORIES=1`` that retains text for 7 days.

Layers (today):
  * **Regex rules** for deterministic patterns (method-specificity on
    self-harm, sexual-violence terms, URL presence, specific high-risk
    named entities).
  * **Pluggable LLM classifier** interface for categories that need
    semantic judgment (real-person detection, primary-vs-atmospheric
    gore). The pipeline supplies a concrete classifier at runtime;
    pre-launch, unit tests pass a mock classifier.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Protocol

from ._types import ModDecision, ModResult
from .prompt_guardrail import content_sha256

logger = logging.getLogger(__name__)


# ─── Regex rules ────────────────────────────────────────────────────────────


# Self-harm method specificity — atmospheric mention OK, step-by-step NOT.
# The patterns target phrasing that names a method with quantitative or
# procedural detail.
_SELF_HARM_METHOD_RE = re.compile(
    r"\b(?:"
    r"(?:\d+(?:\.\d+)?)\s?(?:pills|tablets|mg|milligrams|grams?)"  # dosages
    r"|(?:tied|fashioned|knotted)\s+(?:a|the)\s+(?:rope|noose|ligature)"
    r"|(?:slit|slashed|opened)\s+(?:my|his|her|their)\s+(?:wrists?|throat)"
    r"|(?:loaded|chambered)\s+(?:a|the|my|his|her)\s+(?:gun|pistol|revolver|rifle)"
    r")\b",
    re.I,
)

# Sexual-violence terms — hard reject.
_SEXUAL_VIOLENCE_RE = re.compile(
    r"\b(?:rape[ds]?|raping|rapist|sexual(?:ly)? assault(?:ed|ing|s)?|molest(?:ed|ing|s)?)\b",
    re.I,
)

# Minor-as-victim / perpetrator markers — conservative catch.
_MINOR_MARKERS_RE = re.compile(
    r"\b(?:"
    r"(?:the\s+)?child(?:ren)?[',]?s?\s+(?:body|corpse|remains|screams?|blood)"
    r"|(?:age[sd]?|aged)\s+(?:[4-9]|1[0-5])\b"        # aged 4-15
    r"|(?:a|the)\s+(?:\d)\s?[- ](?:year|yr)[- ]old"   # single-digit ages
    r"|kindergartener|grade[- ]school(?:er)?"
    r"|(?:infant|toddler|newborn|baby)"
    r")",
    re.I,
)

# Real-person high-risk markers — rough catch (LLM classifier is primary).
_REAL_PERSON_REGEX_MARKERS = re.compile(
    r"\b(?:"
    # Presidents / heads of state / high-profile names can sneak in
    r"president\s+\w+"
    r"|(?:mr\.?|ms\.?|mrs\.?|dr\.?)\s+[A-Z][a-z]+ [A-Z][a-z]+"  # "Mr. Firstname Lastname"
    r")",
    re.I,
)

# Gore-as-primary detector — heuristic only; LLM classifier does the
# primary-vs-atmospheric judgment. Counts explicit viscera words.
_GORE_WORDS_RE = re.compile(
    r"\b(?:viscera|entrails|disemboweled|decapitat(?:ed|ion)|dismember(?:ed|ment)|"
    r"eviscerated|gory|gore|bloody\s+(?:stump|limb|body))\b",
    re.I,
)

# URL presence — archivist never cites external URLs.
_URL_RE = re.compile(r"https?://\S+", re.I)


# ─── LLM classifier interface ───────────────────────────────────────────────


class ModClassifier(Protocol):
    """Pluggable LLM-classifier for categories that need semantic judgment.

    Implementations call a cheap model (Haiku) with category-specific
    prompts. The story pipeline injects a concrete classifier at
    runtime; tests can pass a mock that returns pre-scripted decisions.
    """

    def classify_named_real_person(self, text: str) -> bool:
        """True if ``text`` names a real living person."""
        ...

    def classify_gore_primary_focus(self, text: str) -> bool:
        """True if gore is the story's primary driver (vs atmospheric)."""
        ...

    def classify_identifiable_real_crime(self, text: str) -> bool:
        """True if ``text`` describes a specific real-world crime
        (named location + dated event)."""
        ...


class _PassthroughClassifier:
    """Default classifier that says "not this category" to everything.

    Used when the pipeline hasn't wired a real LLM classifier yet. Keeps
    the regex layer fully functional and lets unit tests run without an
    Anthropic key.
    """

    def classify_named_real_person(self, text: str) -> bool:
        return False

    def classify_gore_primary_focus(self, text: str) -> bool:
        return False

    def classify_identifiable_real_crime(self, text: str) -> bool:
        return False


# ─── Filter ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MonetizationModFilter:
    """Run the full monetization-first mod filter over a story draft."""

    classifier: ModClassifier = _PassthroughClassifier()
    # Gore word-count over which the classifier is consulted (cheap-pass-first).
    gore_regex_threshold: int = 3

    def evaluate(self, script: str) -> ModResult:
        """Evaluate ``script`` and return a :class:`ModResult`.

        Categories (all monetization-first, not just age-gate):
          1. URLs in script → REJECT (archivist never cites URLs)
          2. Self-harm method specificity → REJECT
          3. Sexual violence terms → REJECT
          4. Minor-as-victim/perpetrator markers → REJECT
          5. Real-person regex markers → REWRITE (classifier confirms)
          6. Gore word density → REWRITE if classifier says primary-focus
          7. Real-crime classification → REJECT if classifier confirms
        """
        reasons: List[str] = []
        decision = ModDecision.PASS

        if _URL_RE.search(script):
            reasons.append("url_in_script")
            decision = ModDecision.REJECT

        if _SELF_HARM_METHOD_RE.search(script):
            reasons.append("self_harm_method_specificity")
            decision = ModDecision.REJECT

        if _SEXUAL_VIOLENCE_RE.search(script):
            reasons.append("sexual_violence")
            decision = ModDecision.REJECT

        if _MINOR_MARKERS_RE.search(script):
            reasons.append("minor_victim_or_perpetrator")
            decision = ModDecision.REJECT

        # Real-person check: regex catches obvious cases, classifier
        # confirms. Either-or triggers rewrite (borderline category —
        # the Archivist can usually rework to avoid the name).
        real_person_regex = bool(_REAL_PERSON_REGEX_MARKERS.search(script))
        real_person_classifier = self.classifier.classify_named_real_person(script)
        if real_person_regex or real_person_classifier:
            reasons.append("real_person_named")
            if decision == ModDecision.PASS:
                decision = ModDecision.REWRITE

        # Gore check: regex counts viscera words; above threshold, ask
        # the classifier whether gore is the primary driver. Primary-gore
        # → REWRITE (atmospheric gore stays).
        gore_matches = len(_GORE_WORDS_RE.findall(script))
        if gore_matches >= self.gore_regex_threshold:
            if self.classifier.classify_gore_primary_focus(script):
                reasons.append("gore_primary_focus")
                if decision == ModDecision.PASS:
                    decision = ModDecision.REWRITE

        # Real-crime classification — classifier-only (no reliable regex).
        if self.classifier.classify_identifiable_real_crime(script):
            reasons.append("identifiable_real_crime")
            decision = ModDecision.REJECT

        result = ModResult(
            decision=decision,
            reasons=reasons,
            content_sha256=content_sha256(script),
        )
        # Log only (reason, hash) — never the raw rejected text, per S7.
        logger.info(
            "mod_filter: decision=%s reasons=%s hash=%s",
            decision.value, reasons, result.content_sha256[:12],
        )
        return result


__all__ = [
    "ModClassifier",
    "MonetizationModFilter",
    "_PassthroughClassifier",
]
