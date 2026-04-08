"""
arXiv topic source — pulls fresh preprints from cs.AI / cs.CL RSS feeds
and returns structured items for topic scoring.

We use arXiv strictly as a topic-signal source: title + abstract + URL feed
the original-script generator. We do NOT reshare paper PDFs or figures, so
the per-paper license doesn't gate inclusion. License (when surfaced by the
feed) is appended to the summary so downstream prompts can reference it.

Settings consumed (all optional):
- ``ARXIV_MAX_ITEMS``    — cap on returned items (default 15)
- ``ARXIV_CATEGORIES``   — comma-separated arXiv category list
                            (default ``"cs.AI,cs.CL"``)

Prefers ``feedparser`` if installed; falls back to ``xml.etree.ElementTree``
otherwise. Either path must work — no hard dependency.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

try:
    import feedparser  # type: ignore
    _HAS_FEEDPARSER = True
except Exception:  # pragma: no cover - exercised via fallback path
    feedparser = None  # type: ignore
    _HAS_FEEDPARSER = False

_RSS_URL = "http://export.arxiv.org/rss/{category}"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ARXIV_SUFFIX_RE = re.compile(r"\s*\(arXiv:[^)]*\)\s*$")


def _clean_title(title: str) -> str:
    if not title:
        return ""
    # Strip "(arXiv:2601.12345v1 [cs.AI])" suffix if present.
    cleaned = _ARXIV_SUFFIX_RE.sub("", title).strip()
    if cleaned.endswith("."):
        cleaned = cleaned[:-1].rstrip()
    return cleaned


def _clean_abstract(text: str) -> str:
    if not text:
        return ""
    no_tags = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", no_tags).strip()


def _build_summary(abstract: str, category: str, license_str: str | None) -> str:
    snippet = abstract[:400]
    if len(abstract) > 400:
        snippet += "..."
    base = f"{snippet} — arXiv {category} preprint"
    if license_str:
        base = f"{base} (license: {license_str})"
    return base


def _parse_with_feedparser(xml_text: str) -> list[dict]:
    parsed = feedparser.parse(xml_text)  # type: ignore[union-attr]
    out: list[dict] = []
    for entry in getattr(parsed, "entries", []) or []:
        out.append(
            {
                "title": getattr(entry, "title", "") or "",
                "link": getattr(entry, "link", "") or "",
                "summary": getattr(entry, "summary", "")
                or getattr(entry, "description", "")
                or "",
                "license": getattr(entry, "rights", "") or "",
            }
        )
    return out


def _parse_with_stdlib(xml_text: str) -> list[dict]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_text)
    # arXiv RSS is RSS 1.0 / RDF with dc + content namespaces.
    ns = {
        "rss": "http://purl.org/rss/1.0/",
        "dc": "http://purl.org/dc/elements/1.1/",
        "atom": "http://www.w3.org/2005/Atom",
    }
    out: list[dict] = []
    # Try RSS 1.0 items first, then plain <item>, then Atom <entry>.
    items = root.findall(".//rss:item", ns) or root.findall(".//item")
    for it in items:
        title_el = it.find("rss:title", ns)
        if title_el is None:
            title_el = it.find("title")
        link_el = it.find("rss:link", ns)
        if link_el is None:
            link_el = it.find("link")
        desc_el = it.find("rss:description", ns)
        if desc_el is None:
            desc_el = it.find("description")
        rights_el = it.find("dc:rights", ns)
        out.append(
            {
                "title": (title_el.text or "") if title_el is not None else "",
                "link": (link_el.text or "") if link_el is not None else "",
                "summary": (desc_el.text or "") if desc_el is not None else "",
                "license": (rights_el.text or "") if rights_el is not None else "",
            }
        )
    if out:
        return out
    # Atom fallback.
    for entry in root.findall(".//atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        link_el = entry.find("atom:link", ns)
        summary_el = entry.find("atom:summary", ns)
        out.append(
            {
                "title": (title_el.text or "") if title_el is not None else "",
                "link": (link_el.get("href") or "") if link_el is not None else "",
                "summary": (summary_el.text or "") if summary_el is not None else "",
                "license": "",
            }
        )
    return out


def _parse_feed(xml_text: str) -> list[dict]:
    if _HAS_FEEDPARSER:
        try:
            entries = _parse_with_feedparser(xml_text)
            if entries:
                return entries
        except Exception as exc:
            logger.info("arxiv source: feedparser failed, falling back: %s", exc)
    return _parse_with_stdlib(xml_text)


class ArxivTopicSource:
    name = "arxiv"

    def is_configured(self, settings: Any) -> bool:
        # Public RSS, no credentials required.
        return True

    def fetch_items(self, settings: Any) -> tuple[list[dict], str]:
        try:
            import httpx
        except ImportError as exc:
            logger.warning("arxiv source: httpx not available: %s", exc)
            return [], ""

        max_items = int(getattr(settings, "ARXIV_MAX_ITEMS", 15) or 15)
        cats_raw = getattr(settings, "ARXIV_CATEGORIES", "cs.AI,cs.CL") or "cs.AI,cs.CL"
        categories = [c.strip() for c in str(cats_raw).split(",") if c.strip()]
        label = f"arxiv@{datetime.utcnow().isoformat(timespec='seconds')}Z"

        items: list[dict] = []
        seen_urls: set[str] = set()

        try:
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                for category in categories:
                    try:
                        r = client.get(_RSS_URL.format(category=category))
                    except Exception as exc:
                        logger.info(
                            "arxiv source: %s fetch failed: %s", category, exc
                        )
                        continue
                    if r.status_code != 200:
                        logger.warning(
                            "arxiv source: %s HTTP %d", category, r.status_code
                        )
                        continue
                    try:
                        entries = _parse_feed(r.text)
                    except Exception as exc:
                        logger.warning(
                            "arxiv source: %s parse failed: %s", category, exc
                        )
                        continue
                    for entry in entries:
                        url = (entry.get("link") or "").strip()
                        title = _clean_title((entry.get("title") or "").strip())
                        abstract = _clean_abstract(entry.get("summary") or "")
                        if not url or not title:
                            continue
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        items.append(
                            {
                                "title": title,
                                "url": url,
                                "summary": _build_summary(
                                    abstract, category, entry.get("license") or ""
                                ),
                                "source": self.name,
                            }
                        )
        except Exception as exc:
            logger.warning("arxiv source: fetch failed: %s", exc)
            return [], label

        if len(items) > max_items:
            items = items[:max_items]

        logger.info(
            "arxiv source: returning %d items across %d categories",
            len(items),
            len(categories),
        )
        return items, label
