"""
Meme source registry.

Separate from ``topic_sources`` because memes flow through a
fundamentally different pipeline: they are *downloaded, overlaid with
credit, and republished* — not used as inputs to the generative video
pipeline. The shapes are incompatible and keeping them in one package
would force every caller to branch on a type discriminator.

A meme source returns ``MemeCandidate`` dicts with at minimum:
    - source          (e.g. "reddit_programmerhumor")
    - source_url      (permalink on origin platform)
    - author_handle   (e.g. "u/bryden_cruz")
    - title           (short description shown in Telegram)
    - media_url       (direct URL to the image/video we'll download)
    - media_type      ("image" | "video" | "gif")
    - engagement      dict with source-specific counts (score, comments)
    - published_at    ISO timestamp

Each source's ``fetch_candidates(settings) -> list[MemeCandidate]`` must
NEVER raise — it returns an empty list on any error so one broken source
doesn't take down the whole trigger.
"""
from __future__ import annotations

import logging
from typing import Any

from .reddit_memes import RedditMemeSource

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type] = {
    "reddit_programmerhumor": RedditMemeSource,
    "reddit_techhumor": RedditMemeSource,  # same class, subreddit via settings
    # Unit 4 — additional Reddit sources
    "reddit_cscareerquestions": RedditMemeSource,
    "reddit_webdev": RedditMemeSource,
    "reddit_dataisbeautiful": RedditMemeSource,
    "reddit_homelab": RedditMemeSource,
    "reddit_mechanicalkeyboards": RedditMemeSource,
}


def load_enabled_meme_sources(settings: Any) -> list:
    """Return configured meme source instances per ``MEME_SOURCES`` env var."""
    raw = getattr(settings, "MEME_SOURCES", "reddit_programmerhumor") or ""
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    out: list = []
    for name in names:
        cls = _REGISTRY.get(name)
        if cls is None:
            logger.warning("load_enabled_meme_sources: unknown source %r", name)
            continue
        try:
            instance = cls(source_name=name)
        except Exception as exc:
            logger.warning(
                "load_enabled_meme_sources: %s init failed: %s", name, exc
            )
            continue
        if not instance.is_configured(settings):
            logger.info(
                "load_enabled_meme_sources: %s skipped (not configured)", name
            )
            continue
        out.append(instance)
    return out


__all__ = ["RedditMemeSource", "load_enabled_meme_sources"]
