"""Pull a source's own brand marks so graphics can wear them.

The palette already comes from the story's visual identity, but a colour alone
is a weak signal — a green card is not obviously "TechCrunch" to a viewer
scrolling past. The site's actual favicon and theme colour are, and both are
declared in the page's own head, so they cost one fetch and no guessing.

Everything here degrades to None rather than raising: a missing favicon must
never fail a build.
"""
from __future__ import annotations

import base64
import logging
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_ICON_RE = re.compile(
    r'<link[^>]+rel=["\'][^"\']*icon[^"\']*["\'][^>]*>', re.I)
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
_SIZES_RE = re.compile(r'sizes=["\'](\d+)', re.I)
_THEME_RE = re.compile(
    r'<meta[^>]+name=["\']theme-color["\'][^>]+content=["\']([^"\']+)["\']', re.I)


def _get(url: str, timeout: int = 20) -> Optional[bytes]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as exc:                       # noqa: BLE001 — optional
        logger.debug("fetch failed %s: %s", url, str(exc)[:100])
        return None


def fetch_brand(url: str, out_dir: str) -> dict:
    """Return {"icon": path|None, "theme": "#rrggbb"|None, "domain": str}.

    The icon is normalised to a square PNG so a composition can place it without
    knowing whether the site served an .ico, an .svg or a 180px apple-touch-icon.
    """
    domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
    out = {"icon": None, "theme": None, "domain": domain}
    if not url:
        return out

    html = _get(url)
    if not html:
        return out
    text = html.decode("utf-8", "replace")

    m = _THEME_RE.search(text)
    if m and re.fullmatch(r"#[0-9a-fA-F]{6}", m.group(1).strip()):
        out["theme"] = m.group(1).strip()

    # Prefer the largest declared icon; fall back to /favicon.ico.
    best, best_size = None, -1
    for tag in _ICON_RE.findall(text):
        href = _HREF_RE.search(tag)
        if not href:
            continue
        size = int(_SIZES_RE.search(tag).group(1)) if _SIZES_RE.search(tag) else 0
        # Skip SVG: rasterising it needs a browser, and every site that ships one
        # also ships a PNG or ICO.
        if href.group(1).lower().endswith(".svg"):
            continue
        if size > best_size:
            best, best_size = urllib.parse.urljoin(url, href.group(1)), size
    if best is None:
        best = urllib.parse.urljoin(url, "/favicon.ico")

    raw = _get(best)
    if not raw:
        return out

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    src = Path(out_dir) / "brand_icon_src"
    src.write_bytes(raw)
    png = Path(out_dir) / "brand_icon.png"
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(src),
         "-vf", "scale=192:192:force_original_aspect_ratio=decrease,"
                "pad=192:192:(ow-iw)/2:(oh-ih)/2:color=0x00000000",
         str(png)],
        capture_output=True, text=True)
    if r.returncode == 0 and png.exists() and png.stat().st_size > 0:
        out["icon"] = str(png)
        logger.info("Source brand: %s icon %s, theme %s", domain,
                    f"{png.stat().st_size // 1024}KB", out["theme"] or "none")
    return out


def icon_data_uri(path: Optional[str]) -> str:
    """Inline the icon so Remotion needs no static-file plumbing."""
    if not path or not Path(path).is_file():
        return ""
    return ("data:image/png;base64,"
            + base64.b64encode(Path(path).read_bytes()).decode("ascii"))
