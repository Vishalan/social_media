"""Types for the story generator + mod filter."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


@dataclass(frozen=True)
class StoryDraft:
    """A single LLM-generated story draft.

    Carries only the sanitized output — intermediate raw Claude
    responses are not persisted to avoid accidental storage of
    prompt-injection attempts as "content history".
    """

    archivist_script: str       # the narrated story text
    word_count: int             # accurate count over ``archivist_script``
    setting_tag: str            # short tag from the archetype (e.g. "night_shift")
    archetype_id: str           # which archetype seeded this draft
    flagged_topics: List[str] = field(default_factory=list)  # self-flagged by LLM


class ModDecision(str, Enum):
    """Decisions the monetization-first mod filter can emit."""

    PASS = "pass"
    REWRITE = "rewrite"    # borderline — regenerate with tighter prompt
    REJECT = "reject"      # hard rejection — skip this topic


@dataclass(frozen=True)
class ModResult:
    """Outcome of a :class:`MonetizationModFilter` evaluation."""

    decision: ModDecision
    reasons: List[str] = field(default_factory=list)
    # Content-hash of the rejected text — per Security Posture S7 we log
    # the hash + reason, NEVER the raw rejected text.
    content_sha256: Optional[str] = None
