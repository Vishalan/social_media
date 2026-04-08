"""
GitHub Trending topic source — scrapes https://github.com/trending (daily
scope) and returns repos that are gaining real traction today.

There is no official JSON API for trending, so we parse the HTML with
BeautifulSoup. Like every other TopicSource, this one degrades gracefully:
network failure, HTML drift, or a totally empty page all return ``([], label)``
rather than raising.

Two knobs come from settings (both optional, read via ``getattr``):
- ``GITHUB_TRENDING_MAX_ITEMS``       — cap on returned items (default 15)
- ``GITHUB_TRENDING_MIN_STARS_TODAY`` — drop low-signal repos (default 10)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_TRENDING_URL = "https://github.com/trending?since=daily"


class GitHubTrendingTopicSource:
    name = "github_trending"

    def is_configured(self, settings: Any) -> bool:
        # Public HTML page, no credentials required.
        return True

    def fetch_items(self, settings: Any) -> tuple[list[dict], str]:
        label = f"github_trending@{datetime.utcnow().isoformat(timespec='seconds')}Z"

        try:
            import httpx
            from bs4 import BeautifulSoup
        except ImportError as exc:
            logger.warning("github_trending source: dependency missing: %s", exc)
            return [], label

        max_items = int(getattr(settings, "GITHUB_TRENDING_MAX_ITEMS", 15) or 15)
        min_stars = int(getattr(settings, "GITHUB_TRENDING_MIN_STARS_TODAY", 10) or 10)

        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                r = client.get(
                    _TRENDING_URL,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; CommonCreedBot/1.0)"},
                )
                if r.status_code != 200:
                    logger.warning(
                        "github_trending source: HTTP %d", r.status_code
                    )
                    return [], label
                html = r.text
        except Exception as exc:
            logger.warning("github_trending source: fetch failed: %s", exc)
            return [], label

        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:
            logger.warning("github_trending source: parse failed: %s", exc)
            return [], label

        items: list[dict] = []
        for article in soup.select("article.Box-row"):
            try:
                h2 = article.select_one("h2.h3.lh-condensed") or article.select_one("h2")
                if not h2:
                    continue
                a = h2.find("a")
                if not a or not a.get("href"):
                    continue
                href = a["href"].strip()
                slug = href.lstrip("/")
                if "/" not in slug:
                    continue
                owner, repo = slug.split("/", 1)

                desc_el = article.select_one("p.col-9.color-fg-muted.my-1.pr-4") or article.find("p")
                description = desc_el.get_text(strip=True) if desc_el else ""
                if not description:
                    # Signal-poor: skip undescribed repos.
                    continue

                stars_today = 0
                stars_el = article.select_one("span.d-inline-block.float-sm-right")
                if stars_el:
                    text = stars_el.get_text(" ", strip=True)
                    m = re.search(r"([\d,]+)\s+stars\s+today", text)
                    if m:
                        stars_today = int(m.group(1).replace(",", ""))

                if stars_today < min_stars:
                    continue

                repo_name = f"{owner}/{repo}"
                title = f"{repo_name}: {description}"[:200]
                items.append(
                    {
                        "title": title,
                        "url": f"https://github.com/{owner}/{repo}",
                        "summary": f"{description} — {stars_today} stars today",
                        "source": self.name,
                    }
                )
                if len(items) >= max_items:
                    break
            except Exception as exc:
                logger.info("github_trending source: row parse skipped: %s", exc)
                continue

        logger.info(
            "github_trending source: returning %d items (min_stars=%d)",
            len(items),
            min_stars,
        )
        return items, label
