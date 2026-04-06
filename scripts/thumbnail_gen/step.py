"""Pipeline step: produce a thumbnail PNG with full failure isolation.

This module's `step_thumbnail` MUST NEVER raise. Any failure degrades to a
text-only fallback PNG, and as a last resort, a solid black PNG.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

CANVAS_W = 1080
CANVAS_H = 1920

_DEFAULT_PORTRAIT = (
    Path(__file__).resolve().parents[2] / "assets" / "logos" / "owner-portrait-9x16.jpg"
)
_PEXELS_URL = "https://api.pexels.com/v1/search"


def _fetch_pexels_background(query: str, out_dir: Path) -> Path | None:
    """Fetch a portrait Pexels image for the given query. Returns None on failure."""
    try:
        key = os.environ.get("PEXELS_API_KEY", "")
        if not key:
            logger.info("PEXELS_API_KEY not set; skipping background fetch")
            return None
        url = f"{_PEXELS_URL}?query={urllib.parse.quote(query)}&per_page=3&orientation=portrait"
        req = urllib.request.Request(
            url,
            headers={"Authorization": key, "User-Agent": "Mozilla/5.0 commoncreed-pipeline"},
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())
        photos = data.get("photos") or []
        if not photos:
            return None
        img_url = photos[0].get("src", {}).get("large2x") or photos[0].get("src", {}).get("large")
        if not img_url:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "thumbnail_bg.jpg"
        req2 = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req2, timeout=15) as r:
            out_path.write_bytes(r.read())
        return out_path
    except Exception as e:
        logger.warning("Pexels background fetch failed for %r: %s", query, e)
        return None


def _topic_query_from_script(script_text: str, headline: str) -> str:
    """Build a Pexels search query from the script + headline.

    Strategy: use the brand catalog to find the dominant brand/product (e.g.
    'google ai', 'openai chatgpt'), fall back to first ~6 words of the script.
    """
    try:
        try:
            from thumbnail_gen.brand_logo import detect_brand
        except ImportError:
            from scripts.thumbnail_gen.brand_logo import detect_brand
        domain = detect_brand((script_text or "") + " " + (headline or ""))
        if domain:
            brand = domain.split(".")[0]
            return f"{brand} ai technology"
    except Exception:
        pass
    # Fallback: first meaningful words of the script
    words = (script_text or "").split()[:8]
    return (" ".join(words) + " technology") if words else "ai technology"


def _script_fallback_headline(script_text: str) -> str:
    """First 3 cleaned words of script, uppercased. Else 'BREAKING NEWS'."""
    try:
        if not script_text:
            return "BREAKING NEWS"
        cleaned = re.sub(r"[^\w\s]", " ", script_text)
        words = [w for w in cleaned.split() if w]
        if len(words) < 2:
            return "BREAKING NEWS"
        return " ".join(words[:3]).upper()
    except Exception:
        return "BREAKING NEWS"


def _blank_cutout_png() -> Path:
    """Create a 1x1 fully-transparent PNG and return its path."""
    from PIL import Image
    tmp = Path(tempfile.gettempdir()) / "thumbnail_blank_cutout.png"
    if not tmp.exists():
        Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(tmp, "PNG")
    return tmp


def _text_only_fallback(headline: str, output_path: Path) -> Path:
    """Render headline on a solid black background. Must not raise."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (CANVAS_W, CANVAS_H), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = None
        for size in (140, 100, 72):
            try:
                font = ImageFont.truetype(
                    "/System/Library/Fonts/Helvetica.ttc", size
                )
                break
            except Exception:
                pass
        if font is None:
            font = ImageFont.load_default()

        # Word wrap
        words = (headline or "BREAKING NEWS").split()
        lines: list[str] = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip()
            bbox = draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] > CANVAS_W - 120 and cur:
                lines.append(cur)
                cur = w
            else:
                cur = test
        if cur:
            lines.append(cur)

        # Center vertically
        line_h = draw.textbbox((0, 0), "Ay", font=font)[3] + 20
        total_h = line_h * len(lines)
        y = (CANVAS_H - total_h) // 2
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font)
            x = (CANVAS_W - (bbox[2] - bbox[0])) // 2
            draw.text((x, y), line, fill=(255, 255, 255), font=font)
            y += line_h

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, "PNG")
        return output_path
    except Exception as e:
        logger.warning("text-only fallback failed: %s; writing black PNG", e)
        return _black_png(output_path)


def _black_png(output_path: Path) -> Path:
    """Final-of-final fallback: solid black PNG. Must not raise."""
    try:
        from PIL import Image
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (CANVAS_W, CANVAS_H), (0, 0, 0)).save(output_path, "PNG")
    except Exception as e:
        logger.error("black PNG fallback failed: %s; writing raw bytes", e)
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            # Minimal 1x1 black PNG
            output_path.write_bytes(
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
                b"\x00\x0cIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4"
                b"\x00\x00\x00\x00IEND\xaeB`\x82"
            )
        except Exception:
            pass
    return output_path


def step_thumbnail(
    script_text: str,
    run_dir: Path,
    background_image: Path | None = None,
    portrait_path: Path | None = None,
) -> Path:
    """Produce <run_dir>/thumbnail.png. NEVER raises."""
    output_path = Path(run_dir) / "thumbnail.png"
    try:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning("could not create run_dir %s: %s", run_dir, e)

        # 1. Headline
        headline = ""
        try:
            try:
                from thumbnail_gen.headline import generate_headline
            except ImportError:
                from scripts.thumbnail_gen.headline import generate_headline
            headline = generate_headline(script_text)
        except Exception as e:
            logger.warning("generate_headline failed: %s; using script fallback", e)
            headline = _script_fallback_headline(script_text)
        if not headline:
            headline = _script_fallback_headline(script_text)

        # 2. Cutout — best-effort. If rembg fails, fall back to the raw portrait
        # (the circular PiP mask will hide most of the background anyway).
        cutout_path: Path | None = None
        src = Path(portrait_path) if portrait_path else _DEFAULT_PORTRAIT
        try:
            try:
                from thumbnail_gen.cutout import ensure_portrait_cutout
            except ImportError:
                from scripts.thumbnail_gen.cutout import ensure_portrait_cutout
            cutout_path = ensure_portrait_cutout(src)
        except Exception as e:
            logger.warning("ensure_portrait_cutout failed: %s; using raw portrait", e)
            if src.exists():
                cutout_path = src
            else:
                cutout_path = None

        # 3. Brand logo (best-effort, no failure ever)
        brand_logo: Path | None = None
        try:
            try:
                from thumbnail_gen.brand_logo import get_logo_for_text
            except ImportError:
                from scripts.thumbnail_gen.brand_logo import get_logo_for_text
            # Detect from BOTH script and headline so brand wins even if headline drops it
            brand_logo = get_logo_for_text((script_text or "") + " " + (headline or ""))
        except Exception as e:
            logger.warning("brand logo lookup failed: %s; skipping logo", e)
            brand_logo = None

        # 3b. Background image — if caller didn't pass one, auto-fetch from Pexels
        bg_image = background_image
        if bg_image is None:
            try:
                query = _topic_query_from_script(script_text, headline)
                logger.info("auto-fetching Pexels background for query: %r", query)
                bg_image = _fetch_pexels_background(query, Path(run_dir))
            except Exception as e:
                logger.warning("auto background fetch failed: %s", e)
                bg_image = None

        # 4. Compose
        try:
            try:
                from thumbnail_gen.compositor import compose_thumbnail
            except ImportError:
                from scripts.thumbnail_gen.compositor import compose_thumbnail
            cp = cutout_path if cutout_path is not None else _blank_cutout_png()
            return compose_thumbnail(headline, bg_image, cp, output_path, brand_logo_path=brand_logo)
        except Exception as e:
            logger.warning("compose_thumbnail failed: %s; text-only fallback", e)
            return _text_only_fallback(headline, output_path)

    except Exception as e:
        logger.error("step_thumbnail catastrophic failure: %s", e)
        try:
            return _text_only_fallback(_script_fallback_headline(script_text), output_path)
        except Exception:
            return _black_png(output_path)
