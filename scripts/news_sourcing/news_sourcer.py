"""
News sourcing for the CommonCreed pipeline.

Fetches 2-3 tech news topics per day from RSS feeds and the Hacker News API.
Sanitizes raw feed content before any LLM use (HTML stripped, field lengths capped).
Deduplicates against the AnalyticsTracker SQLite news_items table (7-day window).
Raises InsufficientTopicsError if fewer than 2 unique topics are found, and
optionally sends a Telegram alert before raising.
"""

import html
import logging
import re

logger = logging.getLogger(__name__)


class InsufficientTopicsError(RuntimeError):
    pass


class NewsSourcer:
    GOOGLE_NEWS_TECH_RSS = (
        "https://news.google.com/rss/topics/"
        "CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtVnVHZ0pWVXlBQlAB"
    )
    HN_TOP_STORIES_API = "https://hacker-news.firebaseio.com/v0/topstories.json"
    HN_ITEM_API = "https://hacker-news.firebaseio.com/v0/item/{}.json"

    MAX_TITLE_LEN = 200
    MAX_SUMMARY_LEN = 1000
    MIN_TOPICS = 2

    def __init__(self, tracker, telegram_bot=None, max_topics: int = 3):
        """
        tracker: AnalyticsTracker instance (provides is_duplicate_topic + record_news_item).
        telegram_bot: Optional TelegramApprovalBot — used to send low-topic alerts.
        max_topics: Maximum number of topics to return per day.
        """
        self.tracker = tracker
        self.telegram_bot = telegram_bot
        self.max_topics = max_topics

    def fetch(self) -> list[dict]:
        """
        Fetch and return up to max_topics unique tech news topics.

        Each item: {title, url, summary, source}

        Raises InsufficientTopicsError (after sending Telegram alert) if
        fewer than MIN_TOPICS unique topics are found.
        """
        candidates: list[dict] = []
        candidates.extend(self._fetch_google_news())
        if len(candidates) < self.max_topics:
            candidates.extend(self._fetch_hacker_news())

        unique: list[dict] = []
        for item in candidates:
            if self.tracker.is_duplicate_topic(item["url"], item["title"]):
                logger.debug("Skipping duplicate topic: %s", item["title"])
                continue
            unique.append(item)
            if len(unique) == self.max_topics:
                break

        if len(unique) < self.MIN_TOPICS:
            msg = (
                f"CommonCreed pipeline: only {len(unique)} unique tech topic(s) found "
                f"today (need {self.MIN_TOPICS}). Skipping generation."
            )
            logger.warning(msg)
            if self.telegram_bot is not None:
                import asyncio
                try:
                    asyncio.get_event_loop().run_until_complete(
                        self.telegram_bot.send_alert(msg)
                    )
                except Exception as exc:
                    logger.error("Failed to send Telegram alert: %s", exc)
            raise InsufficientTopicsError(
                f"Only {len(unique)} unique topics found (minimum {self.MIN_TOPICS})"
            )

        for item in unique:
            self.tracker.record_news_item(item["url"], item["title"])

        logger.info("Fetched %d unique topics", len(unique))
        return unique

    # ─── Private: feed fetchers ────────────────────────────────────────────

    def _fetch_google_news(self) -> list[dict]:
        """Fetch tech news from Google News RSS. Returns [] on error."""
        try:
            import feedparser
        except ImportError:
            logger.error("feedparser not installed — cannot fetch Google News RSS")
            return []

        try:
            feed = feedparser.parse(self.GOOGLE_NEWS_TECH_RSS)
        except Exception as exc:
            logger.error("Google News RSS fetch failed: %s", exc)
            return []

        items = []
        for entry in feed.entries[:20]:
            title = self._sanitize_text(entry.get("title", ""), self.MAX_TITLE_LEN)
            url = entry.get("link", "").strip()
            summary = self._sanitize_text(entry.get("summary", ""), self.MAX_SUMMARY_LEN)
            if title and url:
                items.append(
                    {"title": title, "url": url, "summary": summary, "source": "google_news"}
                )
        logger.debug("Google News RSS returned %d candidates", len(items))
        return items

    def _fetch_hacker_news(self) -> list[dict]:
        """Fetch top tech stories from Hacker News API. Returns [] on error."""
        try:
            import requests
        except ImportError:
            logger.error("requests not installed — cannot fetch Hacker News")
            return []

        try:
            ids = requests.get(self.HN_TOP_STORIES_API, timeout=10).json()[:30]
        except Exception as exc:
            logger.error("Hacker News top stories fetch failed: %s", exc)
            return []

        items = []
        for story_id in ids:
            try:
                story = requests.get(
                    self.HN_ITEM_API.format(story_id), timeout=5
                ).json()
                if story.get("type") != "story" or not story.get("url"):
                    continue
                title = self._sanitize_text(
                    story.get("title", ""), self.MAX_TITLE_LEN
                )
                url = story["url"].strip()
                if title and url:
                    items.append(
                        {"title": title, "url": url, "summary": "", "source": "hacker_news"}
                    )
                if len(items) >= 10:
                    break
            except Exception as exc:
                logger.debug("Skipping HN story %s: %s", story_id, exc)
                continue

        logger.debug("Hacker News returned %d candidates", len(items))
        return items

    # ─── Private: sanitization ─────────────────────────────────────────────

    @staticmethod
    def _sanitize_text(text: str, max_len: int) -> str:
        """
        Strip HTML tags, unescape HTML entities, collapse whitespace,
        and cap length. Prevents prompt injection from raw feed content.
        """
        # Strip HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Unescape HTML entities
        text = html.unescape(text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        # Cap length
        return text[:max_len]
