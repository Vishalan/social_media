"""
Hacker News topic source — pulls the current top stories from the
Firebase HN API, skips anything without a URL (Ask HN / job posts), and
returns structured items ready for scoring.

No credentials, no LLM extraction step: HN gives us titles + urls + scores
directly. This source exists primarily to prove that the topic_sources
abstraction is not Gmail-shaped — if we can drop in a totally different
backend with no config beyond an env flag, the abstraction is doing its
job.

Two knobs come from settings:
- ``HACKERNEWS_MAX_ITEMS``       — how many top stories to fetch (default 20)
- ``HACKERNEWS_MIN_SCORE``       — skip items below this HN upvote score (default 50)

Both are optional. The source degrades gracefully if HN is unreachable —
returns an empty list with a label and never raises.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_TOPSTORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
_ITEM_URL = "https://hacker-news.firebaseio.com/v0/item/{id}.json"


class HackerNewsTopicSource:
    name = "hackernews"

    def is_configured(self, settings: Any) -> bool:
        # HN public API needs no credentials. The only reason to return
        # False would be if the operator explicitly disabled it via an
        # env flag, which we don't need yet.
        return True

    def fetch_items(self, settings: Any) -> tuple[list[dict], str]:
        try:
            import httpx
        except ImportError as exc:
            logger.warning("hackernews source: httpx not available: %s", exc)
            return [], ""

        max_items = int(getattr(settings, "HACKERNEWS_MAX_ITEMS", 20) or 20)
        min_score = int(getattr(settings, "HACKERNEWS_MIN_SCORE", 50) or 50)
        label = f"hackernews@{datetime.utcnow().isoformat(timespec='seconds')}Z"

        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.get(_TOPSTORIES_URL)
                if r.status_code != 200:
                    logger.warning(
                        "hackernews source: topstories HTTP %d", r.status_code
                    )
                    return [], label
                ids = r.json() or []
                ids = ids[: max(max_items, 1)]

                items: list[dict] = []
                for story_id in ids:
                    try:
                        ir = client.get(_ITEM_URL.format(id=story_id))
                        if ir.status_code != 200:
                            continue
                        story = ir.json() or {}
                    except Exception as exc:
                        logger.info(
                            "hackernews source: item %s fetch failed: %s",
                            story_id,
                            exc,
                        )
                        continue
                    if story.get("type") != "story":
                        continue
                    url = (story.get("url") or "").strip()
                    title = (story.get("title") or "").strip()
                    score = int(story.get("score") or 0)
                    if not url or not title:
                        # Ask HN / text posts have no url — skip: the
                        # browser_visit b-roll generator needs a real article
                        continue
                    if score < min_score:
                        continue
                    items.append(
                        {
                            "title": title,
                            "url": url,
                            "summary": f"Hacker News front page, {score} points",
                            "source": self.name,
                        }
                    )
        except Exception as exc:
            logger.warning("hackernews source: fetch failed: %s", exc)
            return [], label

        logger.info(
            "hackernews source: returning %d items (min_score=%d)",
            len(items),
            min_score,
        )
        return items, label
