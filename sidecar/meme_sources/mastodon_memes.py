"""
Mastodon meme source — fetches posts from tech-focused Mastodon instances
via the public timeline/tag API. No authentication required.

Polls hashtags like #programmerhumor, #devhumor, #techmemes across
configured instances (default: fosstodon.org, hachyderm.io).

Returns the same candidate dict shape as RedditMemeSource so the
downstream pipeline (scoring, preview, publish) works unchanged.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    """Strip HTML tags and collapse whitespace to get plain text."""
    text = _HTML_TAG_RE.sub(" ", html or "")
    return _WHITESPACE_RE.sub(" ", text).strip()


class MastodonMemeSource:
    def __init__(self, source_name: str = "mastodon_techmemes") -> None:
        self.name = source_name

    def is_configured(self, settings: Any) -> bool:
        instances = getattr(settings, "MASTODON_MEME_INSTANCES", "") or ""
        hashtags = getattr(settings, "MASTODON_MEME_HASHTAGS", "") or ""
        return bool(instances.strip()) and bool(hashtags.strip())

    def fetch_candidates(self, settings: Any) -> list[dict]:
        try:
            import httpx
        except ImportError as exc:
            logger.warning("mastodon meme source: httpx missing: %s", exc)
            return []

        instances = [
            i.strip() for i in
            (getattr(settings, "MASTODON_MEME_INSTANCES", "") or "").split(",")
            if i.strip()
        ]
        hashtags = [
            h.strip().lstrip("#") for h in
            (getattr(settings, "MASTODON_MEME_HASHTAGS", "") or "").split(",")
            if h.strip()
        ]
        min_engagement = int(
            getattr(settings, "MASTODON_MEME_MIN_ENGAGEMENT", 10) or 10
        )
        max_items = int(
            getattr(settings, "MASTODON_MEME_MAX_ITEMS", 40) or 40
        )

        candidates: list[dict] = []
        seen_urls: set[str] = set()

        for instance in instances:
            for hashtag in hashtags:
                url = f"https://{instance}/api/v1/timelines/tag/{hashtag}?limit={max_items}"
                try:
                    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                        r = client.get(
                            url,
                            headers={"User-Agent": "CommonCreedBot/0.1 (meme curator)"},
                        )
                        if r.status_code != 200:
                            logger.warning(
                                "mastodon %s #%s: HTTP %d", instance, hashtag, r.status_code
                            )
                            continue
                        statuses = r.json()
                except Exception as exc:
                    logger.warning(
                        "mastodon %s #%s: fetch failed: %s", instance, hashtag, exc
                    )
                    continue

                for status in statuses:
                    cand = self._to_candidate(status, instance, min_engagement)
                    if cand is None:
                        continue
                    if cand["source_url"] in seen_urls:
                        continue
                    seen_urls.add(cand["source_url"])
                    candidates.append(cand)

        logger.info(
            "mastodon meme source: returning %d candidates from %d instances × %d hashtags",
            len(candidates), len(instances), len(hashtags),
        )
        return candidates

    def _to_candidate(
        self, status: dict, instance: str, min_engagement: int
    ) -> dict | None:
        # Skip boosts (reblogs) — we want original posts
        if status.get("reblog"):
            return None

        # Must have media attachments
        attachments = status.get("media_attachments") or []
        if not attachments:
            return None

        # Resolve media
        attachment = attachments[0]
        att_type = attachment.get("type", "")
        media_url = attachment.get("url") or ""
        if not media_url:
            return None

        if att_type == "image":
            media_type = "image"
        elif att_type == "video" or att_type == "gifv":
            media_type = "video"
        else:
            return None

        # Engagement filter
        favourites = int(status.get("favourites_count") or 0)
        reblogs = int(status.get("reblogs_count") or 0)
        engagement = favourites + reblogs
        if engagement < min_engagement:
            return None

        # Extract title from HTML content
        content_text = _strip_html(status.get("content") or "")
        title = content_text[:200] if content_text else "(no text)"

        # Author
        account = status.get("account") or {}
        handle = account.get("acct") or account.get("username") or "unknown"

        # Post URL
        source_url = status.get("url") or status.get("uri") or ""
        if not source_url:
            return None

        # Published at
        created = status.get("created_at") or ""

        return {
            "source": self.name,
            "source_url": source_url,
            "author_handle": f"@{handle}@{instance}",
            "title": title,
            "media_url": media_url,
            "media_type": media_type,
            "engagement": {
                "score": engagement,
                "favourites": favourites,
                "reblogs": reblogs,
                "instance": instance,
            },
            "published_at": created,
        }
