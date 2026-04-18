"""Article body extractor using Trafilatura.

Takes a topic URL (from news sourcing) and returns a clean structured extract
of the article — title, lead paragraph, body paragraphs, publish date, byline —
so downstream b-roll generators (notably R1 phone-highlight and R5 tweet quote
extraction) can pull real words from the source instead of paraphrasing.

Public surface:
    ArticleExtract      — dataclass holding the structured extract.
    extract_article_text(url) — fetch + parse + filter + cache. None on failure.

Design contract (see Unit 0.4 in docs/plans/2026-04-18-001-feat-engagement-layer-v2-plan.md):
    - Uses `trafilatura.fetch_url` + `trafilatura.extract(..., output_format="json")`.
    - Paragraphs shorter than 40 chars (likely captions/CTAs) are dropped.
    - Paragraphs matching /sponsored content|advertisement|continue reading/i
      are stripped.
    - Returns None when extracted body < 80 chars (paywall or garbage).
    - Disk cache by URL hash under ~/.cache/commoncreed_articles/<hash>.json,
      7-day TTL. Re-runs are free.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ─── Tunables (match the plan contract verbatim) ──────────────────────────────

_MIN_PARAGRAPH_CHARS = 40
_MIN_BODY_CHARS = 80
_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days
_STRIP_PATTERN = re.compile(
    r"sponsored content|advertisement|continue reading",
    re.IGNORECASE,
)


def _default_cache_dir() -> Path:
    return Path.home() / ".cache" / "commoncreed_articles"


# ─── Data model ───────────────────────────────────────────────────────────────


@dataclass
class ArticleExtract:
    """Structured output from `extract_article_text`.

    Fields:
        title            — article title (or empty string).
        lead_paragraph   — first body paragraph after filtering.
        body_paragraphs  — all filtered body paragraphs (including the lead).
        publish_date     — ISO-ish date string from Trafilatura, or None.
        byline           — author byline from Trafilatura, or None.
        source_url       — the URL passed to `extract_article_text`.
    """

    title: str
    lead_paragraph: str
    body_paragraphs: list[str] = field(default_factory=list)
    publish_date: str | None = None
    byline: str | None = None
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable dict for stashing on a topic dict / writing to cache."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArticleExtract":
        """Inverse of `to_dict` — used when reading cache files."""
        return cls(
            title=data.get("title", "") or "",
            lead_paragraph=data.get("lead_paragraph", "") or "",
            body_paragraphs=list(data.get("body_paragraphs") or []),
            publish_date=data.get("publish_date"),
            byline=data.get("byline"),
            source_url=data.get("source_url", "") or "",
        )


# ─── Cache helpers ────────────────────────────────────────────────────────────


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _cache_path(url: str, cache_dir: Path) -> Path:
    return cache_dir / f"{_url_hash(url)}.json"


def _read_cache(url: str, cache_dir: Path) -> ArticleExtract | None:
    """Return a cached ArticleExtract if present and fresh; else None."""
    path = _cache_path(url, cache_dir)
    try:
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > _CACHE_TTL_SECONDS:
            logger.debug("cache stale for %s (age=%.0fs)", url, age)
            return None
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return ArticleExtract.from_dict(data)
    except Exception as exc:
        logger.warning("cache read failed for %s: %s", url, exc)
        return None


def _write_cache(article: ArticleExtract, cache_dir: Path) -> None:
    """Best-effort cache write; never raises."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = _cache_path(article.source_url, cache_dir)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(article.to_dict(), fh, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning(
            "cache write failed for %s: %s", article.source_url, exc
        )


# ─── Paragraph filtering ──────────────────────────────────────────────────────


def _filter_paragraphs(raw_text: str) -> list[str]:
    """Split raw article body into paragraphs and apply the contract filters.

    1. Split on blank lines (Trafilatura joins paragraphs with \\n\\n).
    2. Drop paragraphs shorter than 40 chars.
    3. Drop paragraphs matching /sponsored content|advertisement|continue reading/i.
    """
    if not raw_text:
        return []
    paragraphs: list[str] = []
    for chunk in re.split(r"\n\s*\n", raw_text):
        stripped = chunk.strip()
        if len(stripped) < _MIN_PARAGRAPH_CHARS:
            continue
        if _STRIP_PATTERN.search(stripped):
            continue
        paragraphs.append(stripped)
    return paragraphs


# ─── Public API ───────────────────────────────────────────────────────────────


def extract_article_text(
    url: str,
    *,
    cache_dir: Path | None = None,
) -> ArticleExtract | None:
    """Fetch and extract the article body at `url`.

    Returns an ArticleExtract, or None if the article body is too short
    (< 80 chars after filtering — typical for paywalls, login walls, or
    JavaScript-only pages) or fetching/parsing fails.

    Pure-I/O + pure-compute; never raises. Failures become None + a log line.

    Args:
        url:       The article URL.
        cache_dir: Override the on-disk cache location (primarily for tests).
                   Defaults to ~/.cache/commoncreed_articles/.
    """
    if not url or not isinstance(url, str):
        logger.warning("extract_article_text: invalid url %r", url)
        return None

    effective_cache_dir = cache_dir if cache_dir is not None else _default_cache_dir()

    # 1. Cache hit → return immediately, no network.
    cached = _read_cache(url, effective_cache_dir)
    if cached is not None:
        logger.info("article cache hit for %s", url)
        return cached

    # 2. Import lazily so the module remains importable even when trafilatura
    # is not installed in the current environment (the test suite mocks it).
    try:
        import trafilatura  # type: ignore[import-not-found]
    except ImportError as exc:
        logger.warning("trafilatura not installed: %s", exc)
        return None

    # 3. Fetch + extract.
    try:
        downloaded = trafilatura.fetch_url(url)
    except Exception as exc:
        logger.warning("trafilatura.fetch_url failed for %s: %s", url, exc)
        return None
    if not downloaded:
        logger.warning("trafilatura.fetch_url returned empty for %s", url)
        return None

    try:
        extracted_json = trafilatura.extract(downloaded, output_format="json")
    except Exception as exc:
        logger.warning("trafilatura.extract failed for %s: %s", url, exc)
        return None
    if not extracted_json:
        logger.warning("trafilatura.extract returned nothing for %s", url)
        return None

    try:
        payload = json.loads(extracted_json)
    except (ValueError, TypeError) as exc:
        logger.warning("trafilatura JSON parse failed for %s: %s", url, exc)
        return None

    raw_text: str = payload.get("text") or payload.get("raw_text") or ""
    paragraphs = _filter_paragraphs(raw_text)
    body_chars = sum(len(p) for p in paragraphs)

    if body_chars < _MIN_BODY_CHARS:
        logger.warning(
            "article body <%d chars after filtering (%d chars) for %s — "
            "likely paywall or JS-only page",
            _MIN_BODY_CHARS, body_chars, url,
        )
        return None

    article = ArticleExtract(
        title=(payload.get("title") or "").strip(),
        lead_paragraph=paragraphs[0],
        body_paragraphs=paragraphs,
        publish_date=payload.get("date") or payload.get("publish_date"),
        byline=payload.get("author") or payload.get("byline"),
        source_url=url,
    )

    _write_cache(article, effective_cache_dir)
    logger.info(
        "extracted %d paragraphs from %s (lead %d chars)",
        len(paragraphs), url, len(article.lead_paragraph),
    )
    return article
