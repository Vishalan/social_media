"""
Reddit meme source — fetches top posts from a configured subreddit via
the Reddit OAuth2 API. Anonymous JSON access stopped working 2026-05-28,
so this module now requires REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET and a
script-app password grant (REDDIT_USERNAME / REDDIT_PASSWORD).

The source returns a candidate dict per fetched image/video post, with
enough metadata for the media-pipeline to download + credit-overlay + repost.

Subreddit is resolved per-source-name via the ``MEME_SUBREDDIT_MAP`` setting
(comma-separated ``name:subreddit`` pairs). Defaults below.

When OAuth creds are missing fetch_candidates returns [] and logs a
single warning per source — the trigger flow tolerates empty source lists
without raising.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_SUBREDDITS = {
    "reddit_programmerhumor": "ProgrammerHumor",
    "reddit_techhumor": "techhumor",
    # Unit 4 — widen the top-of-funnel for strict humor+relevance filtering
    "reddit_cscareerquestions": "cscareerquestions",
    "reddit_webdev": "webdev",
    "reddit_programminghorror": "programminghorror",
    # AI-niche tier — higher video density, most on-niche for @commoncreed
    "reddit_chatgpt": "ChatGPT",
    "reddit_localllama": "LocalLLaMA",
    "reddit_openai": "OpenAI",
    "reddit_singularity": "singularity",
    "reddit_artificial": "artificial",
    # Round-out
    "reddit_dataisbeautiful": "DataIsBeautiful",
    "reddit_homelab": "homelab",
    "reddit_mechanicalkeyboards": "MechanicalKeyboards",
}

# Module-level token cache shared across all RedditMemeSource instances —
# every trigger fetches ~13 subreddits, so caching the bearer avoids 13x
# auth roundtrips per run. Reddit tokens expire after 3600s; we refresh
# 60s before expiry to be safe.
_TOKEN_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}  # client_id -> (token, expires_at_epoch)


def _get_access_token(settings: Any) -> str | None:
    """Return a valid Reddit OAuth bearer token, refreshing if expired.

    Uses the script-app password grant: needs CLIENT_ID/CLIENT_SECRET
    (from reddit.com/prefs/apps) plus the developer USERNAME/PASSWORD.
    Returns None if creds are missing or auth fails.
    """
    client_id = getattr(settings, "REDDIT_CLIENT_ID", "") or ""
    client_secret = getattr(settings, "REDDIT_CLIENT_SECRET", "") or ""
    username = getattr(settings, "REDDIT_USERNAME", "") or ""
    password = getattr(settings, "REDDIT_PASSWORD", "") or ""
    if not (client_id and client_secret and username and password):
        return None

    now = time.time()
    with _TOKEN_LOCK:
        cached = _TOKEN_CACHE.get(client_id)
        if cached and cached[1] > now + 60:
            return cached[0]

    user_agent_tpl = getattr(
        settings, "REDDIT_USER_AGENT", "CommonCreedBot/0.2 by u/{username}"
    ) or "CommonCreedBot/0.2 by u/{username}"
    user_agent = user_agent_tpl.replace("{username}", username)

    try:
        import httpx

        with httpx.Client(timeout=10.0) as client:
            r = client.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=(client_id, client_secret),
                data={
                    "grant_type": "password",
                    "username": username,
                    "password": password,
                },
                headers={"User-Agent": user_agent},
            )
            if r.status_code != 200:
                logger.warning(
                    "reddit oauth: token request HTTP %d body=%s",
                    r.status_code,
                    r.text[:200],
                )
                return None
            payload = r.json()
    except Exception as exc:
        logger.warning("reddit oauth: token request raised: %s", exc)
        return None

    token = payload.get("access_token") or ""
    expires_in = int(payload.get("expires_in") or 3600)
    if not token:
        logger.warning("reddit oauth: empty access_token in response")
        return None

    with _TOKEN_LOCK:
        _TOKEN_CACHE[client_id] = (token, now + expires_in)
    return token


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
        return bool(
            getattr(settings, "REDDIT_CLIENT_ID", "")
            and getattr(settings, "REDDIT_CLIENT_SECRET", "")
            and getattr(settings, "REDDIT_USERNAME", "")
            and getattr(settings, "REDDIT_PASSWORD", "")
        )

    def fetch_candidates(self, settings: Any) -> list[dict]:
        try:
            import httpx
        except ImportError as exc:
            logger.warning("reddit meme source: httpx missing: %s", exc)
            return []

        token = _get_access_token(settings)
        if not token:
            logger.warning(
                "reddit meme source %s: skipped (no OAuth creds; set "
                "REDDIT_CLIENT_ID/SECRET/USERNAME/PASSWORD)",
                self.name,
            )
            return []

        subreddit = self._resolve_subreddit(settings)
        # See mastodon_memes.py note — `or N` fallback coerces 0 to N
        time_filter = getattr(settings, "REDDIT_MEME_TIME_FILTER", "day") or "day"
        limit = int(getattr(settings, "REDDIT_MEME_MAX_ITEMS", 25))
        min_score = int(getattr(settings, "REDDIT_MEME_MIN_SCORE", 500))

        username = getattr(settings, "REDDIT_USERNAME", "") or ""
        user_agent_tpl = getattr(
            settings, "REDDIT_USER_AGENT", "CommonCreedBot/0.2 by u/{username}"
        ) or "CommonCreedBot/0.2 by u/{username}"
        user_agent = user_agent_tpl.replace("{username}", username)

        url = f"https://oauth.reddit.com/r/{subreddit}/top"
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": user_agent,
        }
        params = {"t": time_filter, "limit": str(limit)}

        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                r = client.get(url, headers=headers, params=params)
                if r.status_code == 401:
                    # Token may have been revoked mid-flight; invalidate cache
                    # and let next call refresh.
                    with _TOKEN_LOCK:
                        cid = getattr(settings, "REDDIT_CLIENT_ID", "") or ""
                        _TOKEN_CACHE.pop(cid, None)
                    logger.warning(
                        "reddit meme source %s: HTTP 401 (token invalidated)",
                        self.name,
                    )
                    return []
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
