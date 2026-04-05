"""
Scrape the TLDR AI web archive page to extract article candidates.

Usage::

    from newsletter.tldr_scraper import scrape_tldr_ai
    articles = await scrape_tldr_ai("https://tldr.tech/ai/2026-04-01")
    # returns list of {title, url, summary, section, read_time}

TLDR newsletter web archive is at https://tldr.tech/ai/YYYY-MM-DD.
Sponsor items are filtered out automatically.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

# Patterns that indicate an item is a sponsor / ad
_SPONSOR_SIGNALS = [
    "sponsor", "advertisement", "presented by", "powered by",
    "try it free", "get started free", "sign up free", "download now",
    "use code tldr", "promo code", "free trial",
]

# Section headers in TLDR AI newsletter
_SECTION_HEADERS = [
    "headlines & launches",
    "deep dives & analysis",
    "engineering & research",
    "miscellaneous",
    "quick links",
]


def _is_sponsor(title: str, summary: str) -> bool:
    combined = (title + " " + summary).lower()
    return any(sig in combined for sig in _SPONSOR_SIGNALS)


async def scrape_tldr_ai(url: str) -> list[dict]:
    """
    Scrape a TLDR AI archive page and return non-sponsor articles.

    Args:
        url: TLDR archive URL, e.g. ``https://tldr.tech/ai/2026-04-01``.

    Returns:
        List of dicts with keys: title, url, summary, section, read_time.
        Empty list if Playwright is unavailable or the page is unreachable.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("playwright not installed — cannot scrape TLDR")
        return []

    articles: list[dict] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)

                # Extract articles via JavaScript — handle multiple TLDR layouts
                raw = await page.evaluate("""
                () => {
                    const results = [];
                    let current_section = "Headlines & Launches";

                    // Strategy 1: look for article cards / link blocks
                    // TLDR web uses <article> or <div> with a heading+link+summary pattern
                    const anchors = Array.from(document.querySelectorAll('a[href]'));

                    for (const a of anchors) {
                        const href = a.href || '';
                        const title = (a.textContent || '').trim();

                        // Skip navigation, footer, social links
                        if (!href.startsWith('http')) continue;
                        if (href.includes('tldr.tech') && !href.includes('/p/')) continue;
                        if (title.length < 15 || title.length > 200) continue;

                        // Try to find an associated summary paragraph
                        let summary = '';
                        let read_time = '';

                        // Look at parent/sibling elements for summary text
                        let parent = a.closest('div, article, section, li');
                        if (parent) {
                            const paras = Array.from(parent.querySelectorAll('p'));
                            for (const p of paras) {
                                const t = p.textContent.trim();
                                if (t.length > 40 && t !== title) {
                                    summary = t.substring(0, 300);
                                    break;
                                }
                            }
                        }

                        // Parse "(X minute read)" from title
                        const m = title.match(/\\((\\d+)\\s+minute\\s+read\\)/i);
                        if (m) {
                            read_time = m[1] + ' min';
                        }

                        // Detect section from nearest heading
                        let heading = null;
                        let el = a;
                        while (el && el !== document.body) {
                            el = el.parentElement;
                            if (!el) break;
                            const prev = el.previousElementSibling;
                            if (prev && /^h[1-4]$/i.test(prev.tagName)) {
                                heading = prev.textContent.trim();
                                break;
                            }
                        }

                        results.push({
                            title: title.replace(/\\s*\\(\\d+ minute read\\)/i, '').trim(),
                            url: href,
                            summary: summary,
                            section: heading || current_section,
                            read_time: read_time,
                        });
                    }
                    return results;
                }
                """)

                # Deduplicate by URL
                seen_urls: set[str] = set()
                for item in raw:
                    url_key = item.get("url", "")
                    if url_key in seen_urls:
                        continue
                    seen_urls.add(url_key)

                    title = item.get("title", "").strip()
                    summary = item.get("summary", "").strip()

                    if not title or _is_sponsor(title, summary):
                        continue

                    articles.append({
                        "title": title,
                        "url": url_key,
                        "summary": summary,
                        "section": item.get("section", ""),
                        "read_time": item.get("read_time", ""),
                    })

            finally:
                await browser.close()

    except Exception as exc:
        logger.warning("TLDR scraper error: %s", exc)
        return []

    logger.info("TLDR scraper: found %d articles from %s", len(articles), url)
    return articles


def build_tldr_url(date_str: str) -> str:
    """Build TLDR AI archive URL from a date string (YYYY-MM-DD or 'today')."""
    if date_str == "today":
        from datetime import date
        date_str = date.today().isoformat()
    return f"https://tldr.tech/ai/{date_str}"
