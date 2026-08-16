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

from .mastodon_memes import MastodonMemeSource
from .reddit_memes import RedditMemeSource

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type] = {
    "reddit_programmerhumor": RedditMemeSource,
    "reddit_techhumor": RedditMemeSource,  # same class, subreddit via settings
    # Unit 4 — additional Reddit sources (programmer/dev humor tier)
    "reddit_cscareerquestions": RedditMemeSource,
    "reddit_webdev": RedditMemeSource,
    "reddit_programminghorror": RedditMemeSource,
    # AI-niche tier (added after the v0 7-source pool felt too dev-heavy —
    # ChatGPT / LocalLLaMA / OpenAI / singularity / artificial bring
    # video-heavy on-niche content that the quality filter still has to
    # clear at humor+relevance >=7)
    "reddit_chatgpt": RedditMemeSource,
    "reddit_localllama": RedditMemeSource,
    "reddit_openai": RedditMemeSource,
    "reddit_singularity": RedditMemeSource,
    "reddit_artificial": RedditMemeSource,
    # Round-out tier
    "reddit_dataisbeautiful": RedditMemeSource,
    "reddit_homelab": RedditMemeSource,
    "reddit_mechanicalkeyboards": RedditMemeSource,
    # Mastodon — public API, no auth, free. Replaces Reddit when its
    # anonymous JSON is blocked or its OAuth setup isn't available.
    "mastodon_fosstodon_techmemes": MastodonMemeSource,
    "mastodon_fosstodon_programmerhumor": MastodonMemeSource,
    "mastodon_fosstodon_devhumor": MastodonMemeSource,
    "mastodon_hachyderm_devhumor": MastodonMemeSource,
    "mastodon_mastodonsocial_chatgpt": MastodonMemeSource,
    "mastodon_mastodonsocial_ai": MastodonMemeSource,
    # Mastodon video-leaning sources
    "mastodon_fosstodon_aivideo": MastodonMemeSource,
    "mastodon_hachyderm_aivideo": MastodonMemeSource,
    "mastodon_fosstodon_aiart": MastodonMemeSource,
    "mastodon_hachyderm_aiart": MastodonMemeSource,
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


__all__ = [
    "MastodonMemeSource",
    "RedditMemeSource",
    "load_enabled_meme_sources",
]
