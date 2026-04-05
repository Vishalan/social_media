"""
Parse a TLDR AI newsletter PDF (saved from Gmail) to extract articles.

Uses PyMuPDF (fitz) to extract both text content and hyperlink annotations,
then matches each article link to its title and summary text.
Short links (links.tldrnewsletter.com) are resolved to real URLs via HTTP redirect.

Usage::

    from newsletter.pdf_parser import parse_tldr_pdf
    articles = await parse_tldr_pdf("/path/to/newsletter.pdf")
    # returns list of {title, url, summary, section, read_time}
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# URL patterns to skip (sponsors, navigation, social, referral)
_SKIP_URL_PATTERNS = [
    "advertise.tldr", "tldr.tech/ai?utm", "refer.tldr",
    "cursor.com", "scroll.ai", "littlebird.ai",     # known sponsors in this edition
    "twitter.com", "linkedin.com", "mailto:",
    "hub.sparklp.co", "jobs.ashby", "unsubscribe",
    "manage?email", "web-version",
    "github.com/microsoft/agent-lightning",          # repo, not article
    "fb.com/news",                                   # FB press release
]

# Text patterns that indicate sponsor content
_SPONSOR_TEXT = [
    "sponsor", "advertisement", "try it free", "free trial",
    "use code tldr", "promo code", "get your first month",
    "download now", "start building",
]

# TLDR newsletter section headers
_SECTIONS = [
    "headlines & launches",
    "deep dives & analysis",
    "engineering & research",
    "miscellaneous",
    "quick links",
]

_READ_TIME_RE = re.compile(r"\((\d+)\s+minute\s+read\)", re.IGNORECASE)


def _decode_tldr_tracking(url: str) -> str:
    """Decode a TLDR tracking URL to the real destination URL."""
    # Format: https://tracking.tldrnewsletter.com/CL0/{url_encoded_real_url}/...
    m = re.search(r"/CL0/([^/]+)/", url)
    if m:
        return urllib.parse.unquote(m.group(1))
    return url


def _is_skip_url(url: str) -> bool:
    url_lower = url.lower()
    return any(pat in url_lower for pat in _SKIP_URL_PATTERNS)


def _is_sponsor_text(text: str) -> bool:
    text_lower = text.lower()
    return any(pat in text_lower for pat in _SPONSOR_TEXT)


async def _resolve_short_url(url: str) -> str:
    """Follow redirects to get the real article URL."""
    if "links.tldrnewsletter.com" not in url and "tldrnewsletter.com" not in url:
        return url
    try:
        async with httpx.AsyncClient(
            timeout=8.0, follow_redirects=True, max_redirects=5
        ) as client:
            resp = await client.head(url)
            return str(resp.url)
    except Exception as exc:
        logger.debug("Could not resolve short URL %s: %s", url, exc)
        return url


async def parse_tldr_pdf(pdf_path: str) -> list[dict]:
    """
    Parse a TLDR AI newsletter PDF and return article candidates.

    Args:
        pdf_path: Path to the Gmail-exported newsletter PDF.

    Returns:
        List of article dicts: {title, url, summary, section, read_time}.
        Returns empty list if fitz is not installed.
    """
    try:
        import fitz
    except ImportError:
        logger.error("pymupdf not installed — run: pip install pymupdf")
        return []

    doc = fitz.open(pdf_path)

    # ── Step 1: Collect all text blocks and links across all pages ─────────
    all_blocks: list[dict] = []   # {text, y0, y1, page}
    all_links: list[dict] = []    # {url, y0, y1, x0, x1, page}

    for page_num, page in enumerate(doc):
        # Text blocks: (x0, y0, x1, y1, text, block_no, block_type)
        for block in page.get_text("blocks"):
            text = block[4].strip()
            if text:
                all_blocks.append({
                    "text": text,
                    "y0": block[1] + page_num * 10000,  # offset per page
                    "y1": block[3] + page_num * 10000,
                    "page": page_num,
                })

        for link in page.get_links():
            uri = link.get("uri", "")
            if not uri:
                continue
            real_url = _decode_tldr_tracking(uri)
            rect = link["from"]
            all_links.append({
                "url": real_url,
                "y0": rect.y0 + page_num * 10000,
                "y1": rect.y1 + page_num * 10000,
                "x0": rect.x0,
                "x1": rect.x1,
                "page": page_num,
            })

    doc.close()

    # ── Step 2: Filter to article links only ───────────────────────────────
    article_links: list[dict] = []
    seen_urls: set[str] = set()
    for link in all_links:
        url = link["url"]
        if _is_skip_url(url):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        article_links.append(link)

    # ── Step 3: For each article link, find its title and summary text ─────
    # Sort blocks by position
    all_blocks.sort(key=lambda b: b["y0"])
    article_links.sort(key=lambda l: l["y0"])

    # Find current section by scanning text blocks for section headers
    def _find_section(y_pos: float) -> str:
        current = "Headlines & Launches"
        for block in all_blocks:
            if block["y0"] > y_pos:
                break
            text_lower = block["text"].lower().strip()
            for sec in _SECTIONS:
                if sec in text_lower:
                    current = block["text"].strip().split("\n")[0]
        return current

    raw_articles: list[dict] = []
    for link in article_links:
        # Find title: text block overlapping the link's y-range
        title = ""
        for block in all_blocks:
            # Block should be at roughly the same vertical position as the link
            if abs(block["y0"] - link["y0"]) < 25:
                text = block["text"].strip().replace("\n", " ")
                if len(text) > 10:
                    title = text
                    break

        if not title:
            continue
        if _is_sponsor_text(title):
            continue

        # Parse read time from title
        m = _READ_TIME_RE.search(title)
        read_time = f"{m.group(1)} min" if m else ""
        clean_title = _READ_TIME_RE.sub("", title).strip().rstrip("(").strip()

        # Find summary: the first text block below the title that's a real paragraph
        summary = ""
        for block in all_blocks:
            if block["y0"] > link["y1"] + 5 and block["y0"] < link["y1"] + 300:
                text = block["text"].strip().replace("\n", " ")
                # Skip section headers, short lines, sponsor text
                if (len(text) > 60
                        and not any(s in text.lower() for s in _SECTIONS)
                        and not _is_sponsor_text(text)):
                    summary = text[:300]
                    break

        section = _find_section(link["y0"])

        raw_articles.append({
            "title": clean_title,
            "url": link["url"],
            "summary": summary,
            "section": section,
            "read_time": read_time,
        })

    # ── Step 4: Resolve short URLs concurrently ────────────────────────────
    async def _resolve(article: dict) -> dict:
        article["url"] = await _resolve_short_url(article["url"])
        return article

    resolved = await asyncio.gather(*(_resolve(a) for a in raw_articles))
    articles = [a for a in resolved if a["url"]]

    logger.info("PDF parser: extracted %d articles from %s", len(articles), pdf_path)
    return articles
