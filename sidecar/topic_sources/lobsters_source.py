"""
Lobste.rs topic source — pulls the current hottest stories from the
public ``hottest.json`` endpoint. Lobsters is a smaller, more tightly
moderated tech community than HN, so signal-to-noise is higher and the
default min-score threshold can be lower.

No credentials. Single HTTP request per fetch (be a good citizen — the
server is community-run and lightly resourced).

Settings knobs:
- ``LOBSTERS_MAX_ITEMS`` — cap on returned items (default 15)
- ``LOBSTERS_MIN_SCORE`` — drop entries below this upvote score (default 10)
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_HOTTEST_URL = "https://lobste.rs/hottest.json"
_USER_AGENT = "CommonCreed-Sidecar/1.0 (+https://lobste.rs)"
_PREFERRED_TAGS = {"ai", "ml", "programming", "llm", "devtools"}


class LobstersTopicSource:
    name = "lobsters"

    def is_configured(self, settings: Any) -> bool:
        # Public JSON endpoint, no credentials required.
        return True

    def fetch_items(self, settings: Any) -> tuple[list[dict], str]:
        try:
            import httpx
        except ImportError as exc:
            logger.warning("lobsters source: httpx not available: %s", exc)
            return [], ""

        max_items = int(getattr(settings, "LOBSTERS_MAX_ITEMS", 15) or 15)
        min_score = int(getattr(settings, "LOBSTERS_MIN_SCORE", 10) or 10)
        label = f"lobsters@{datetime.utcnow().isoformat(timespec='seconds')}Z"

        try:
            with httpx.Client(timeout=10.0, headers={"User-Agent": _USER_AGENT}) as client:
                r = client.get(_HOTTEST_URL)
                if r.status_code != 200:
                    logger.warning("lobsters source: hottest HTTP %d", r.status_code)
                    return [], label
                try:
                    entries = r.json() or []
                except Exception as exc:
                    logger.warning("lobsters source: malformed JSON: %s", exc)
                    return [], label
        except Exception as exc:
            logger.warning("lobsters source: fetch failed: %s", exc)
            return [], label

        items: list[dict] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = (entry.get("title") or "").strip()
            if not title:
                continue
            score = int(entry.get("score") or 0)
            if score < min_score:
                continue
            external_url = (entry.get("url") or "").strip()
            discussion_url = (entry.get("short_id_url") or "").strip()
            if not external_url and not discussion_url:
                continue
            url = external_url or discussion_url
            tags = entry.get("tags") or []
            if not isinstance(tags, list):
                tags = []
            comment_count = int(entry.get("comment_count") or 0)

            summary = (
                f"{score} points, {comment_count} comments on Lobste.rs. "
                f"Tags: {', '.join(tags)}"
            )
            if not external_url:
                summary += " | Discussion-only (no external link)"
            if any(t in _PREFERRED_TAGS for t in tags):
                summary += " | high-relevance tag"

            items.append(
                {
                    "title": title,
                    "url": url,
                    "summary": summary,
                    "source": self.name,
                }
            )
            if len(items) >= max_items:
                break

        logger.info(
            "lobsters source: returning %d items (min_score=%d)",
            len(items),
            min_score,
        )
        return items, label
