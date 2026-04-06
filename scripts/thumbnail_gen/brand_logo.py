"""Brand detection and logo fetching for thumbnails.

Detects well-known brand mentions in a script/headline and fetches a logo via
Google's public favicon service (no API key, works for any domain, returns PNG).
Cached to disk so subsequent runs are instant and offline-friendly.
"""
from __future__ import annotations

import logging
import re
import urllib.request
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Brand catalog: keyword -> domain. Order matters: more specific keywords first
# so "google deepmind" beats "google", "meta ai" beats "meta", etc.
# Add new brands here as the news cycle demands — flat data table, not config.
_BRAND_CATALOG = [
    # AI labs / model providers
    ("google deepmind", "deepmind.google"),
    ("deepmind", "deepmind.google"),
    ("openai", "openai.com"),
    ("chatgpt", "openai.com"),
    ("anthropic", "anthropic.com"),
    ("claude", "anthropic.com"),
    ("gemini", "google.com"),
    ("veo", "google.com"),
    ("imagen", "google.com"),
    ("google", "google.com"),
    ("meta ai", "meta.com"),
    ("llama", "meta.com"),
    ("meta", "meta.com"),
    ("mistral", "mistral.ai"),
    ("perplexity", "perplexity.ai"),
    ("grok", "x.ai"),
    ("xai", "x.ai"),
    ("midjourney", "midjourney.com"),
    ("runway", "runwayml.com"),
    ("stability ai", "stability.ai"),
    ("hugging face", "huggingface.co"),
    ("cohere", "cohere.com"),
    # Big tech
    ("microsoft", "microsoft.com"),
    ("github", "github.com"),
    ("apple", "apple.com"),
    ("nvidia", "nvidia.com"),
    ("amazon", "amazon.com"),
    ("aws", "aws.amazon.com"),
    ("netflix", "netflix.com"),
    ("tesla", "tesla.com"),
    ("spacex", "spacex.com"),
    ("tiktok", "tiktok.com"),
    ("instagram", "instagram.com"),
    ("youtube", "youtube.com"),
    # Devtools / infra commonly in AI news
    ("vercel", "vercel.com"),
    ("supabase", "supabase.com"),
    ("cloudflare", "cloudflare.com"),
    ("databricks", "databricks.com"),
    ("snowflake", "snowflake.com"),
]

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_LOGO_CACHE_DIR = _PROJECT_ROOT / "assets" / "brand_logos"
_FAVICON_URL = "https://www.google.com/s2/favicons?domain={domain}&sz={size}"
_USER_AGENT = "Mozilla/5.0 commoncreed-pipeline"


def detect_brand(text: str) -> Optional[str]:
    """Find the first brand mentioned in text. Returns its domain or None.

    "First" means earliest position in the text — so the brand the script leads
    with wins, even if other brands also appear.
    """
    if not text:
        return None
    lowered = text.lower()
    matches = []
    for keyword, domain in _BRAND_CATALOG:
        pattern = r"\b" + re.escape(keyword) + r"\b"
        m = re.search(pattern, lowered)
        if m:
            matches.append((m.start(), domain))
    if not matches:
        return None
    matches.sort(key=lambda x: x[0])
    domain = matches[0][1]
    logger.info("Brand detected: %s", domain)
    return domain


def detect_brands(text: str, max_count: int = 2) -> List[str]:
    """Find up to N distinct brands mentioned in text, ordered by first occurrence."""
    if not text:
        return []
    lowered = text.lower()
    matches = []
    seen = set()
    for keyword, domain in _BRAND_CATALOG:
        pattern = r"\b" + re.escape(keyword) + r"\b"
        m = re.search(pattern, lowered)
        if m and domain not in seen:
            matches.append((m.start(), domain))
            seen.add(domain)
    matches.sort(key=lambda x: x[0])
    return [d for _, d in matches[:max_count]]


def fetch_brand_logo(domain: str, cache_dir: Path | None = None, size: int = 256) -> Optional[Path]:
    """Fetch a brand logo via Google's favicon service, caching to disk.

    Returns path or None on failure. Always returns PNG bytes (favicon service
    serves a PNG even when the source is JPEG/ICO — Pillow handles both fine).
    """
    cache_dir = cache_dir or _LOGO_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_name = domain.replace("/", "_").replace(":", "_")
    cache_path = cache_dir / f"{safe_name}.png"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path

    url = _FAVICON_URL.format(domain=domain, size=size)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = r.read()
        if not data or len(data) < 100:
            logger.warning("Empty/tiny logo response for %s (%d bytes)", domain, len(data))
            return None
        cache_path.write_bytes(data)
        logger.info("Fetched logo for %s -> %s (%d bytes)", domain, cache_path, len(data))
        return cache_path
    except Exception as e:
        logger.warning("Failed to fetch logo for %s: %s", domain, e)
        return None


def get_logo_for_text(text: str) -> Optional[Path]:
    """Convenience: detect brand from text and return its cached/fetched logo path."""
    domain = detect_brand(text)
    if not domain:
        return None
    return fetch_brand_logo(domain)
