"""
Mastodon meme source — fetches recent posts from a hashtag timeline on a
specific Mastodon instance via the public API.

The public hashtag timeline endpoint requires no auth and has generous
rate limits (300 req / 5 min per IP per instance). This is the free
fallback after Reddit blanket-blocked anonymous JSON in May 2026.

Each registry entry maps a source_name to an (instance, tag) tuple. The
defaults below cover the highest media-density hashtags on the largest
tech-focused instances. Override via the MASTODON_SOURCE_MAP setting:
    name:instance|tag,name2:instance|tag,...

A status object becomes a candidate when:
  - it has at least one image / video / gifv media attachment
  - engagement (favourites + reblogs) clears MASTODON_MEME_MIN_SCORE
  - it isn't a reblog (we want originals so credit goes to the right author)
  - it isn't sensitive / hidden / replied-only
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


# Defaults chosen from a hashtag-density sweep on 2026-06-05:
#   fosstodon #techmemes        → 90% posts with media
#   fosstodon #programmerhumor  → 55%
#   fosstodon #devhumor         → 55%
#   mastodon.social #ai/#chatgpt → 30-40% (AI niche)
# Single class shared across all entries; per-instance state lives on the
# MastodonMemeSource instance, not in a module global.
_DEFAULTS: dict[str, tuple[str, str]] = {
    # Image-leaning sources (techmemes, programmerhumor, devhumor)
    "mastodon_fosstodon_techmemes": ("fosstodon.org", "techmemes"),
    "mastodon_fosstodon_programmerhumor": ("fosstodon.org", "programmerhumor"),
    "mastodon_fosstodon_devhumor": ("fosstodon.org", "devhumor"),
    "mastodon_hachyderm_devhumor": ("hachyderm.io", "devhumor"),
    "mastodon_mastodonsocial_chatgpt": ("mastodon.social", "chatgpt"),
    "mastodon_mastodonsocial_ai": ("mastodon.social", "ai"),
    # Video-leaning sources — sweep 2026-06-05 showed:
    #   fosstodon.org #aivideo  -> 10 vid / 40 posts (25% density)
    #   hachyderm.io  #aivideo  ->  7 vid / 40 posts (17%)
    #   fosstodon.org #aiart    ->  ~10% vid (gifv-heavy)
    # These two hashtags are well-federated, so fosstodon/hachyderm see
    # the same content mastodon.social produces — which we use instead of
    # mastodon.social directly because the server can't reach .social
    # over IPv6 (forced IPv4 fixes it, but it's simpler to use a peer
    # instance with v4 routing).
    "mastodon_fosstodon_aivideo": ("fosstodon.org", "aivideo"),
    "mastodon_hachyderm_aivideo": ("hachyderm.io", "aivideo"),
    "mastodon_fosstodon_aiart": ("fosstodon.org", "aiart"),
    "mastodon_hachyderm_aiart": ("hachyderm.io", "aiart"),
}


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(content: str) -> str:
    """Mastodon's `content` field is HTML; reduce to plain text for title use."""
    if not content:
        return ""
    text = _TAG_RE.sub(" ", content)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


class MastodonMemeSource:
    def __init__(self, source_name: str) -> None:
        self.name = source_name
        self._resolved: tuple[str, str] | None = None

    def _resolve(self, settings: Any) -> tuple[str, str]:
        if self._resolved is not None:
            return self._resolved

        raw_map = getattr(settings, "MASTODON_SOURCE_MAP", "") or ""
        mapping = dict(_DEFAULTS)
        for pair in raw_map.split(","):
            pair = pair.strip()
            if ":" not in pair or "|" not in pair:
                continue
            name, _, rhs = pair.partition(":")
            instance, _, tag = rhs.partition("|")
            mapping[name.strip().lower()] = (instance.strip(), tag.strip())

        # Fall back to the most general (mastodon.social + #ai) so an
        # unmapped name still produces something rather than silently
        # disabling itself.
        self._resolved = mapping.get(self.name, ("mastodon.social", "ai"))
        return self._resolved

    def is_configured(self, settings: Any) -> bool:
        return True  # public API, no credentials

    def fetch_candidates(self, settings: Any) -> list[dict]:
        try:
            import httpx
        except ImportError as exc:
            logger.warning("mastodon meme source: httpx missing: %s", exc)
            return []

        instance, tag = self._resolve(settings)
        # NOTE: no `or N` fallback — that pattern coerces a legit 0 value to N
        # because Python treats 0 as falsy. The Settings model already
        # supplies the default when the .env key is absent.
        limit = int(getattr(settings, "MASTODON_MEME_MAX_ITEMS", 30))
        min_score = int(getattr(settings, "MASTODON_MEME_MIN_SCORE", 0))
        user_agent = (
            getattr(settings, "MASTODON_USER_AGENT", "")
            or "CommonCreedBot/0.2 (+https://commoncreed.com)"
        )

        url = f"https://{instance}/api/v1/timelines/tag/{tag}"
        params = {"limit": str(limit)}
        headers = {"User-Agent": user_agent, "Accept": "application/json"}

        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                r = client.get(url, headers=headers, params=params)
                if r.status_code != 200:
                    logger.warning(
                        "mastodon meme source %s: HTTP %d (instance=%s tag=%s)",
                        self.name,
                        r.status_code,
                        instance,
                        tag,
                    )
                    return []
                data = r.json()
        except Exception as exc:
            logger.warning(
                "mastodon meme source %s: fetch failed: %s", self.name, exc
            )
            return []

        if not isinstance(data, list):
            logger.warning(
                "mastodon meme source %s: unexpected response shape", self.name
            )
            return []

        candidates: list[dict] = []
        for status in data:
            try:
                cand = self._to_candidate(status, instance, tag, min_score)
            except Exception as exc:
                logger.info(
                    "mastodon meme source: skipping malformed status: %s", exc
                )
                continue
            if cand is not None:
                candidates.append(cand)

        logger.info(
            "mastodon meme source %s: returning %d candidates (instance=%s tag=%s)",
            self.name,
            len(candidates),
            instance,
            tag,
        )
        return candidates

    def _to_candidate(
        self,
        status: dict,
        instance: str,
        tag: str,
        min_score: int,
    ) -> dict | None:
        # Skip reblogs — credit must go to the original author, not the boosting account
        if status.get("reblog"):
            return None
        # Skip sensitive / NSFW
        if status.get("sensitive"):
            return None
        # Direct replies (in_reply_to_id) tend to be conversation noise
        if status.get("in_reply_to_id"):
            return None

        favourites = int(status.get("favourites_count") or 0)
        reblogs = int(status.get("reblogs_count") or 0)
        replies = int(status.get("replies_count") or 0)
        score = favourites + reblogs
        if score < min_score:
            return None

        account = status.get("account") or {}
        acct = account.get("acct") or account.get("username") or ""
        if not acct:
            return None
        # account.acct is "username" for local accounts, "username@domain" for
        # remote — normalize to a full handle the credit overlay can render
        # consistently.
        author_handle = acct if "@" in acct else f"{acct}@{instance}"

        # Resolve a media URL + type from the first usable attachment.
        media_url: str | None = None
        media_type: str | None = None
        for att in status.get("media_attachments") or []:
            t = att.get("type")
            u = att.get("url")
            if not u:
                continue
            if t == "image":
                media_url = u
                media_type = "image"
                break
            if t == "video":
                media_url = u
                media_type = "video"
                break
            if t == "gifv":
                # Mastodon's gifv is a muted looping MP4 — treat as video
                media_url = u
                media_type = "video"
                break
            # ignore audio / unknown

        if not media_url or not media_type:
            return None

        # Title = stripped content, falling back to the spoiler/CW text if
        # the content itself is empty (some posts are pure media + alt text).
        title_raw = _strip_html(status.get("content") or "")
        if not title_raw:
            title_raw = (status.get("spoiler_text") or "").strip()
        title = title_raw[:200]

        source_url = status.get("url") or status.get("uri") or ""
        if not source_url:
            return None

        return {
            "source": self.name,
            "source_url": source_url,
            "author_handle": f"@{author_handle}",
            "title": title,
            "media_url": media_url,
            "media_type": media_type,
            "engagement": {
                "score": score,
                "favourites": favourites,
                "reblogs": reblogs,
                "replies": replies,
                "instance": instance,
                "tag": tag,
            },
            "published_at": (
                status.get("created_at")
                or datetime.utcnow().isoformat() + "Z"
            ),
        }
