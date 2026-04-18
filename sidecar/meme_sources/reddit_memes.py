"""
Reddit meme source — fetches top posts from a configured subreddit via
the public JSON API. No auth needed for the non-commercial listings tier.

The source returns a candidate dict per fetched image/video post, with
enough metadata for the media-pipeline to download + credit-overlay + repost.

Subreddit is resolved per-source-name via the ``MEME_SUBREDDIT_MAP`` setting
(comma-separated ``name:subreddit`` pairs). Defaults:
    reddit_programmerhumor:ProgrammerHumor
    reddit_techhumor:techhumor
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_SUBREDDITS = {
    "reddit_programmerhumor": "ProgrammerHumor",
    "reddit_techhumor": "techhumor",
    # Unit 4 — widen the top-of-funnel for strict humor+relevance filtering
    "reddit_cscareerquestions": "cscareerquestions",
    "reddit_webdev": "webdev",
    "reddit_dataisbeautiful": "DataIsBeautiful",
    "reddit_homelab": "homelab",
    "reddit_mechanicalkeyboards": "MechanicalKeyboards",
}


class RedditMemeSource:
    def __init__(self, source_name: str = "reddit_programmerhumor") -> None:
        self.name = source_name
        self._subreddit: str | None = None

    def _resolve_subreddit(self, settings: Any) -> str:
        if self._subreddit:
            return self._subreddit
        raw_map = getattr(settings, "MEME_SUBREDDIT_MAP", "") or ""
        mapping = dict(_DEFAULT_SUBREDDITS)
        for pair in raw_map.split(","):
            pair = pair.strip()
            if ":" not in pair:
                continue
            k, v = pair.split(":", 1)
            mapping[k.strip().lower()] = v.strip()
        self._subreddit = mapping.get(self.name, "ProgrammerHumor")
        return self._subreddit

    def is_configured(self, settings: Any) -> bool:
        return True  # public API, no credentials

    def fetch_candidates(self, settings: Any) -> list[dict]:
        try:
            import httpx
        except ImportError as exc:
            logger.warning("reddit meme source: httpx missing: %s", exc)
            return []

        subreddit = self._resolve_subreddit(settings)
        time_filter = getattr(settings, "REDDIT_MEME_TIME_FILTER", "day") or "day"
        limit = int(getattr(settings, "REDDIT_MEME_MAX_ITEMS", 25) or 25)
        min_score = int(getattr(settings, "REDDIT_MEME_MIN_SCORE", 500) or 500)

        url = (
            f"https://www.reddit.com/r/{subreddit}/top.json"
            f"?t={time_filter}&limit={limit}"
        )
        headers = {"User-Agent": "CommonCreedBot/0.1 (meme curator)"}

        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                r = client.get(url, headers=headers)
                if r.status_code != 200:
                    logger.warning(
                        "reddit meme source %s: HTTP %d", self.name, r.status_code
                    )
                    return []
                data = r.json()
        except Exception as exc:
            logger.warning("reddit meme source %s: fetch failed: %s", self.name, exc)
            return []

        children = (data.get("data") or {}).get("children") or []
        candidates: list[dict] = []
        for child in children:
            post = (child or {}).get("data") or {}
            try:
                cand = self._to_candidate(post, subreddit, min_score)
            except Exception as exc:
                logger.info(
                    "reddit meme source: skipping malformed post: %s", exc
                )
                continue
            if cand is not None:
                candidates.append(cand)

        logger.info(
            "reddit meme source %s: returning %d candidates (subreddit=%s)",
            self.name,
            len(candidates),
            subreddit,
        )
        return candidates

    def _to_candidate(
        self, post: dict, subreddit: str, min_score: int
    ) -> dict | None:
        if post.get("over_18"):
            return None
        if post.get("stickied"):
            return None
        score = int(post.get("score") or 0)
        if score < min_score:
            return None

        author = post.get("author") or ""
        if not author or author == "[deleted]":
            return None

        title = (post.get("title") or "").strip()
        permalink = "https://reddit.com" + (post.get("permalink") or "")
        post_hint = post.get("post_hint") or ""
        url = post.get("url") or ""

        # Resolve media_url and media_type
        media_url: str | None = None
        media_type: str | None = None

        if post_hint == "image" and url:
            media_url = url
            media_type = "image"
        elif post_hint == "hosted:video" or post.get("is_video"):
            # Reddit-hosted video
            reddit_video = ((post.get("media") or {}).get("reddit_video") or {})
            fallback = reddit_video.get("fallback_url") or ""
            if fallback:
                media_url = fallback
                media_type = "video"
        elif post_hint == "rich:video":
            # Third-party embeds (gfycat/streamable/imgur). Skip for v0 —
            # those need per-host handling and rights vary.
            return None
        elif post_hint == "link" and url.lower().endswith(
            (".jpg", ".jpeg", ".png", ".gif", ".webp")
        ):
            media_url = url
            media_type = "gif" if url.lower().endswith(".gif") else "image"

        if not media_url or not media_type:
            return None

        return {
            "source": self.name,
            "source_url": permalink,
            "author_handle": f"u/{author}",
            "title": title[:200],
            "media_url": media_url,
            "media_type": media_type,
            "engagement": {
                "score": score,
                "comments": int(post.get("num_comments") or 0),
                "subreddit": subreddit,
            },
            "published_at": datetime.utcfromtimestamp(
                int(post.get("created_utc") or 0)
            ).isoformat() + "Z",
        }
