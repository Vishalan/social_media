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

from .net import BROWSER_UA as _UA
from .color import to_rgb as rgb

logger = logging.getLogger(__name__)


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
    # Show the BRAND, not the hostname.
    #
    # "deploymentsafety.openai.com" is 27 characters and rendered as
    # "DEPLOYMENTSAFETY.OPENAI.C" — truncated mid-word in a kicker sized for a
    # publisher name. The subdomain is infrastructure detail no viewer needs;
    # the registrable domain is the part that means anything. Two labels are
    # kept so a genuine second-level domain like co.uk survives.
    parts = [x for x in domain.split(".") if x]
    if len(parts) > 2:
        tail = parts[-2:]
        if tail[0] in ("co", "com", "org", "net", "ac", "gov") and len(parts) > 3:
            tail = parts[-3:]
        domain = ".".join(tail)
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


def build_brand_card(*, out_png: str, icon: Optional[str], palette: list,
                     size: int = 640) -> str:
    """A branded still for a generated clip to start from.

    MiniMax H3's first_frame conditioning does two things at once, both
    verified on a real generation: the supplied image IS frame zero, and its
    colours propagate through the whole clip. Feeding the source's own mark
    therefore grounds generated footage in the story twice over — it opens on
    the publication's identity, and the scene that dissolves out of it inherits
    that palette rather than defaulting to generic teal.
    """
    from PIL import Image, ImageDraw


    bg = rgb(palette[0] if palette else "#0B0D11")
    accent = bg
    for c in reversed(palette or []):
        r, g, b = rgb(c, (0, 0, 0))
        if 60 < (r * 0.299 + g * 0.587 + b * 0.114) < 225:
            accent = (r, g, b)
            break

    img = Image.new("RGB", (size, size), bg)
    d = ImageDraw.Draw(img)
    # A soft radial bloom in the accent: gives the model colour to carry, and
    # keeps frame zero from being a flat rectangle.
    cx = cy = size // 2
    for i in range(size // 2, 0, -1):
        t = 1 - i / (size / 2)
        col = tuple(int(bg[k] + (accent[k] - bg[k]) * (t ** 3) * 0.55) for k in range(3))
        d.ellipse([cx - i, cy - i, cx + i, cy + i], fill=col)

    if icon and Path(icon).is_file():
        try:
            side = int(size * 0.40)
            ic = Image.open(icon).convert("RGBA").resize((side, side), Image.LANCZOS)
            img.paste(ic, ((size - side) // 2, (size - side) // 2), ic)
        except Exception as exc:                    # noqa: BLE001 — cosmetic
            logger.info("brand card icon skipped: %s", str(exc)[:80])

    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)
    logger.info("Brand card for generated footage: %s", out_png)
    return out_png


def fetch_subject_brand(domains: list, out_dir: str) -> dict:
    """Brand marks for what the story is ABOUT, not who reported it.

    This distinction was got wrong first time round and it showed: a story about
    X open-sourcing its ranking algorithm opened on the TechCrunch logo and wore
    TechCrunch green throughout, because the code treated "source" as one idea.
    The publication is a citation — it belongs on a quoted line. The subject is
    the identity the graphics should wear.

    Takes the first domain that yields a usable icon, so the script can list
    fallbacks in priority order.
    """
    for domain in (domains or []):
        d = str(domain).strip().lower().replace("https://", "").replace("http://", "")
        d = d.split("/")[0]
        if not d or "." not in d:
            continue
        brand = fetch_brand(f"https://{d}/", out_dir)
        if brand.get("icon"):
            logger.info("Subject brand: %s", d)
            return brand
        logger.info("No usable mark for subject %s — trying the next", d)
    return {"icon": None, "theme": None, "domain": ""}
