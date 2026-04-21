"""Topic-signal sources — informers, never content ingesters.

A topic-signal source fetches post titles + engagement metadata from a
public feed (Reddit, RSS, HN, etc.) and returns :class:`TopicSignal`
objects. Channels use topic signals to pick which LLM-original story
to generate that day. Post *bodies* are never ingested — this is the
research-driven content posture for Vesper (see plan Unit 6 + content-
curation-tos-review).
"""

from __future__ import annotations

from ._types import TopicSignal

__all__ = ["TopicSignal"]
