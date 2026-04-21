"""LLM-original story generator for story-channel niches.

``ArchivistStoryWriter`` generates original horror stories in the
Archivist persona, seeded by a :class:`TopicSignal` + an archetype
from :data:`data/horror_archetypes.json`. The writer is wired behind:
  * a prompt-injection guardrail (input canonicalization + output schema)
  * a monetization-first mod filter (platform-policy rejections)

Contract: body/selftext from the upstream signal never reaches the
LLM. The story is LLM-original, using only the canonicalized *title*
of the topic signal as a seed.
"""

from __future__ import annotations

from ._types import ModResult, StoryDraft

__all__ = ["ModResult", "StoryDraft"]
