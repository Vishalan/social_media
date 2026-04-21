"""Types for topic-signal sources.

``TopicSignal`` intentionally carries NO body / selftext / content field.
This is the enforced contract separating signal (public metadata) from
content (subject to Reddit commercial-use TOS + DMCA exposure).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class TopicSignal:
    """One topic candidate for downstream story generation.

    Fields:
        source: Short identifier of the originating feed
            (e.g. ``"reddit"``, ``"hacker_news"``, ``"rss_google_news"``).
        source_url: Canonical URL for the post/article. Used as the
            dedup key by :class:`AnalyticsTracker`.
        subreddit: Subreddit/feed-namespace label, when applicable. Used
            by the ranker's ``subreddit_weight`` multiplier.
        title: Post title after PII/control-char canonicalization (Security
            Posture S5). Already truncated to ``MAX_TITLE_LEN`` chars.
        score: Numeric engagement score (upvotes / HN points).
        num_comments: Comment count — used by the rank heuristic's log-decay.
        fetched_at: UTC timestamp when this signal was fetched.

    What's deliberately missing:
        selftext / body / content — story generators seed from the
        title + archetype library, never from raw post text.
        author handle — avoided so author PII doesn't persist to
        analytics/logs/backups.
    """

    source: str
    source_url: str
    subreddit: str
    title: str
    score: int
    num_comments: int
    fetched_at: datetime = datetime.now()

    # Sanity guard — catches anyone who later adds a ``body``/``selftext``
    # attr by mistake. Dataclass's frozen=True + __slots__ isn't standard;
    # we use a __post_init__ check instead.
    def __post_init__(self) -> None:
        forbidden = {"body", "selftext", "content", "author", "author_handle"}
        present = forbidden.intersection(self.__dict__.keys())
        if present:
            raise ValueError(
                f"TopicSignal must not carry forbidden fields: {present!r}. "
                "Signal sources return metadata only; content belongs "
                "in the LLM-original story generator."
            )
