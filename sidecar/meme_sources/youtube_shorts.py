"""
YouTube Shorts meme source — fetches recent shorts from curated funny tech
channels via YouTube Data API v3.

Uses channel-based fetching (playlistItems.list at 1 unit/call) instead of
search (100 units/call) to stay within the free 10,000 unit/day quota.

Each channel's uploads playlist ID is derived from the channel ID by
replacing the "UC" prefix with "UU" (YouTube convention).

Requires YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET in .env (already
configured for Postiz YouTube integration). Uses API key auth for
public read-only access — no OAuth user consent needed.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def _parse_iso8601_duration(duration: str) -> int:
    """Parse ISO 8601 duration (PT1M30S) to total seconds."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not m:
        return 0
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


class YouTubeShortsMemeSource:
    def __init__(self, source_name: str = "youtube_shorts") -> None:
        self.name = source_name

    def is_configured(self, settings: Any) -> bool:
        channel_ids = getattr(settings, "YOUTUBE_SHORTS_CHANNEL_IDS", "") or ""
        yt_api_key = getattr(settings, "YOUTUBE_API_KEY", "") or ""
        return bool(channel_ids.strip()) and bool(yt_api_key)

    def fetch_candidates(self, settings: Any) -> list[dict]:
        try:
            import httpx
        except ImportError as exc:
            logger.warning("youtube shorts source: httpx missing: %s", exc)
            return []

        channel_ids = [
            c.strip() for c in
            (getattr(settings, "YOUTUBE_SHORTS_CHANNEL_IDS", "") or "").split(",")
            if c.strip()
        ]
        min_views = int(getattr(settings, "YOUTUBE_SHORTS_MIN_VIEWS", 10000) or 10000)
        max_age_days = int(getattr(settings, "YOUTUBE_SHORTS_MAX_AGE_DAYS", 7) or 7)
        yt_api_key = getattr(settings, "YOUTUBE_API_KEY", "") or ""

        if not channel_ids or not yt_api_key:
            return []

        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        candidates: list[dict] = []

        for channel_id in channel_ids:
            try:
                items = self._fetch_channel_shorts(
                    channel_id, yt_api_key, min_views, cutoff
                )
                candidates.extend(items)
            except Exception as exc:
                logger.warning(
                    "youtube shorts %s: fetch failed: %s", channel_id, exc
                )

        logger.info(
            "youtube shorts source: returning %d candidates from %d channels",
            len(candidates), len(channel_ids),
        )
        return candidates

    def _fetch_channel_shorts(
        self,
        channel_id: str,
        api_key: str,
        min_views: int,
        cutoff: datetime,
    ) -> list[dict]:
        import httpx

        # Derive uploads playlist ID: UC... -> UU...
        if channel_id.startswith("UC"):
            playlist_id = "UU" + channel_id[2:]
        else:
            logger.warning("youtube shorts: unexpected channel ID format: %s", channel_id)
            return []

        # Step 1: Get recent playlist items (1 unit/call)
        url = (
            f"https://www.googleapis.com/youtube/v3/playlistItems"
            f"?part=snippet,contentDetails"
            f"&playlistId={playlist_id}"
            f"&maxResults=20"
            f"&key={api_key}"
        )
        with httpx.Client(timeout=15.0) as client:
            r = client.get(url)
            if r.status_code != 200:
                logger.warning("youtube shorts: playlistItems %d for %s", r.status_code, channel_id)
                return []
            items = r.json().get("items", [])

        if not items:
            return []

        # Collect video IDs for batch details lookup
        video_ids = [
            item["contentDetails"]["videoId"]
            for item in items
            if "contentDetails" in item and "videoId" in item["contentDetails"]
        ]
        if not video_ids:
            return []

        # Step 2: Get video details (duration, stats) — 1 unit/call
        details_url = (
            f"https://www.googleapis.com/youtube/v3/videos"
            f"?part=contentDetails,statistics,snippet"
            f"&id={','.join(video_ids)}"
            f"&key={api_key}"
        )
        with httpx.Client(timeout=15.0) as client:
            r = client.get(details_url)
            if r.status_code != 200:
                logger.warning("youtube shorts: videos.list %d", r.status_code)
                return []
            video_items = r.json().get("items", [])

        candidates: list[dict] = []
        for vid in video_items:
            cand = self._to_candidate(vid, channel_id, min_views, cutoff)
            if cand is not None:
                candidates.append(cand)

        return candidates

    def _to_candidate(
        self, vid: dict, channel_id: str, min_views: int, cutoff: datetime
    ) -> dict | None:
        content_details = vid.get("contentDetails", {})
        statistics = vid.get("statistics", {})
        snippet = vid.get("snippet", {})

        # Filter: must be short (under 60 seconds)
        duration_s = _parse_iso8601_duration(content_details.get("duration", ""))
        if duration_s == 0 or duration_s > 60:
            return None

        # Filter: recent enough
        published_at = snippet.get("publishedAt", "")
        try:
            pub_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00")).replace(tzinfo=None)
            if pub_dt < cutoff:
                return None
        except (ValueError, AttributeError):
            pass

        # Filter: minimum views
        view_count = int(statistics.get("viewCount", 0))
        if view_count < min_views:
            return None

        video_id = vid.get("id", "")
        title = snippet.get("title", "")
        channel_title = snippet.get("channelTitle", "")

        return {
            "source": self.name,
            "source_url": f"https://www.youtube.com/shorts/{video_id}",
            "author_handle": channel_title or channel_id,
            "title": title[:200],
            "media_url": f"https://www.youtube.com/shorts/{video_id}",
            "media_type": "video",
            "engagement": {
                "score": view_count,
                "views": view_count,
                "likes": int(statistics.get("likeCount", 0)),
                "channel": channel_title,
            },
            "published_at": published_at,
        }
