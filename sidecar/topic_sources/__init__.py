"""
Pluggable topic sources for the daily pipeline trigger.

A topic source is any backend that returns a list of candidate stories
(title + url + optional summary) shaped the same way downstream whether
the raw data originally came from a TLDR newsletter email, the Hacker
News Firebase API, an RSS feed, a subreddit, or anything else.

Adding a new source is three steps:

1. Create a new module under ``sidecar/topic_sources/`` exporting a class
   that implements :class:`TopicSource`.
2. Register it in :data:`_REGISTRY` below by its short name.
3. Add the short name to ``PIPELINE_TOPIC_SOURCES`` in the NAS .env —
   comma-separated, e.g. ``PIPELINE_TOPIC_SOURCES=gmail,hackernews``.

The ``daily_trigger`` job loads every enabled source that is also
configured (``is_configured(settings) == True``), fetches items from all
of them, merges, scores the combined set with Claude, and persists the
top N. Source-level failures are isolated: one broken source never takes
down the rest of the run.
"""
from __future__ import annotations

import logging
from typing import Iterable

from .base import TopicSource
from .gmail_source import GmailTopicSource
from .hackernews_source import HackerNewsTopicSource

logger = logging.getLogger(__name__)

# --- Registry: short-name -> class --------------------------------------
# Keep keys lowercase and free of punctuation so the env var is forgiving
# ("gmail", "hackernews", "hn" as an alias, etc.).
_REGISTRY: dict[str, type[TopicSource]] = {
    "gmail": GmailTopicSource,
    "hackernews": HackerNewsTopicSource,
    "hn": HackerNewsTopicSource,  # alias
}

DEFAULT_ENABLED = "gmail"


def _parse_enabled(raw: str) -> list[str]:
    names: list[str] = []
    for token in (raw or "").split(","):
        name = token.strip().lower()
        if name:
            names.append(name)
    # de-duplicate while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            out.append(n)
            seen.add(n)
    return out


def load_enabled_sources(settings) -> list[TopicSource]:
    """Return the list of topic source instances enabled in settings.

    Reads ``PIPELINE_TOPIC_SOURCES`` from the sidecar settings (comma-
    separated short names) and instantiates each matching class. Unknown
    names are logged and skipped, never raised. Sources whose
    ``is_configured(settings)`` returns False are also skipped (e.g. Gmail
    before the OAuth token file has been uploaded).
    """
    raw = getattr(settings, "PIPELINE_TOPIC_SOURCES", "") or DEFAULT_ENABLED
    names = _parse_enabled(raw)
    if not names:
        logger.warning(
            "load_enabled_sources: PIPELINE_TOPIC_SOURCES is empty; nothing to load"
        )
        return []

    loaded: list[TopicSource] = []
    for name in names:
        cls = _REGISTRY.get(name)
        if cls is None:
            logger.warning(
                "load_enabled_sources: unknown source %r — known: %s",
                name,
                sorted(set(_REGISTRY.keys())),
            )
            continue
        try:
            instance = cls()
        except Exception as exc:
            logger.warning(
                "load_enabled_sources: %s construction failed: %s", name, exc
            )
            continue
        if not instance.is_configured(settings):
            logger.info(
                "load_enabled_sources: %s skipped (not configured)", instance.name
            )
            continue
        loaded.append(instance)

    return loaded


def registered_source_names() -> Iterable[str]:
    """For introspection / dashboard display."""
    return sorted(set(_REGISTRY.keys()))


__all__ = [
    "TopicSource",
    "load_enabled_sources",
    "registered_source_names",
    "DEFAULT_ENABLED",
]
