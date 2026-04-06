"""Pillow-based thumbnail compositor for 1080x1920 vertical thumbnails.

CommonCreed visual style:
- Dark navy background (with optional darkened on-topic image)
- Inter Black headline, two-tone (light blue + white) alternating by line
- Soft outline, no harsh drop shadow
- Owner portrait as a small circular PiP badge in the bottom safe area
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

CANVAS_W = 1080
CANVAS_H = 1920
TOP_SAFE_END = 288  # 15% reserved for platform UI
BOTTOM_SAFE_START = 1536  # 80%, reserved for platform UI

# Headline must live inside the center-safe zone that survives 1:1 crop
HEADLINE_REGION = (60, 620, 1020, 1380)  # (x1, y1, x2, y2)

# Brand logo badge zone (above the headline, inside the safe area)
LOGO_REGION = (60, 320, 1020, 580)  # (x1, y1, x2, y2)
LOGO_MAX_HEIGHT = 220
LOGO_MAX_WIDTH = 720

# CommonCreed brand palette (sampled from reference image)
BRAND_NAVY = (24, 46, 89)             # background
BRAND_NAVY_DEEP = (16, 32, 64)        # bottom of gradient
BRAND_ACCENT_BLUE = (96, 156, 232)    # light blue text accent
BRAND_WHITE = (250, 250, 252)         # primary text

# Circle PiP avatar
PIP_DIAMETER = 280
PIP_MARGIN = 60
PIP_CENTER = (CANVAS_W - PIP_MARGIN - PIP_DIAMETER // 2, BOTTOM_SAFE_START - PIP_MARGIN - PIP_DIAMETER // 2)
PIP_RING_WIDTH = 10

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FONT_CANDIDATES = [_PROJECT_ROOT / "assets" / "fonts" / "Inter-Black.ttf"]


def _vertical_gradient(size, top_color, bottom_color) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size, top_color)
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        r = int(top_color[0] * (1 - t) + bottom_color[0] * t)
        g = int(top_color[1] * (1 - t) + bottom_color[1] * t)
        b = int(top_color[2] * (1 - t) + bottom_color[2] * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def _cover_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    src_w, src_h = img.size
    src_ratio = src_w / src_h
    tgt_ratio = target_w / target_h
    if src_ratio > tgt_ratio:
        new_h = target_h
        new_w = int(src_ratio * new_h)
    else:
        new_w = target_w
        new_h = int(new_w / src_ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def _load_font(size: int) -> ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except Exception:  # pragma: no cover
                continue
    logger.warning("No bold font found in assets/fonts/, using PIL default")
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _text_height(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[3] - bbox[1]


def _wrap_lines(draw, words: List[str], font, max_w: int, max_lines: int = 3) -> List[str]:
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if _text_width(draw, candidate, font) <= max_w:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]


def _build_darken_overlay() -> Image.Image:
    """Heavy darkening for image backgrounds — keeps the image as texture only."""
    overlay = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    px = overlay.load()
    for y in range(CANVAS_H):
        # darker top and bottom (UI safe zones), slightly lighter mid
        if y < TOP_SAFE_END:
            alpha = 200
        elif y > BOTTOM_SAFE_START:
            alpha = 200
        else:
            d = abs(y - CANVAS_H / 2) / (CANVAS_H / 2)
            alpha = int(140 + 60 * d)
        for x in range(CANVAS_W):
            px[x, y] = (BRAND_NAVY[0] // 4, BRAND_NAVY[1] // 4, BRAND_NAVY[2] // 4, alpha)
    return overlay


def _draw_text_with_outline(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    font,
    fill: Tuple[int, int, int],
    outline: Tuple[int, int, int] = (0, 0, 0),
    outline_width: int = 3,
    anchor: str = "mt",
) -> None:
    """Crisp outline text — multiple offsets in a circle, no blur. Cleaner than drop shadow."""
    cx, cy = xy
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            if dx * dx + dy * dy > outline_width * outline_width:
                continue
            draw.text((cx + dx, cy + dy), text, font=font, fill=outline, anchor=anchor)
    draw.text((cx, cy), text, font=font, fill=fill, anchor=anchor)


def _circle_pip(cutout_path: Path, diameter: int) -> Image.Image | None:
    """Crop the portrait into a circular badge with a thin accent ring. Returns RGBA."""
    try:
        src = Image.open(cutout_path).convert("RGBA")
    except Exception as e:
        logger.warning("Failed to load cutout for PiP: %s", e)
        return None

    # Take the head region: top ~55% of the portrait, square-cropped on horizontal center
    sw, sh = src.size
    head_h = int(sh * 0.55)
    if head_h < 10 or sw < 10:
        return None
    side = min(sw, head_h)
    cx = sw // 2
    cy = head_h // 2
    left = max(0, cx - side // 2)
    top = max(0, cy - side // 2)
    head = src.crop((left, top, left + side, top + side)).resize((diameter, diameter), Image.LANCZOS)

    # Circular mask
    mask = Image.new("L", (diameter, diameter), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((0, 0, diameter, diameter), fill=255)

    # Compose: white ring underneath, then masked head
    badge = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    bd.ellipse((0, 0, diameter, diameter), fill=BRAND_WHITE + (255,))
    head.putalpha(mask)
    inner_pad = PIP_RING_WIDTH
    inner_size = diameter - 2 * inner_pad
    head_inner = head.resize((inner_size, inner_size), Image.LANCZOS)
    badge.alpha_composite(head_inner, (inner_pad, inner_pad))
    return badge


def _place_brand_logo(canvas: Image.Image, logo_path: Path) -> Image.Image:
    """Composite a brand logo badge above the headline. Returns the modified canvas."""
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception as e:
        logger.warning("Failed to load brand logo %s: %s", logo_path, e)
        return canvas

    # Scale to fit within LOGO_MAX_WIDTH x LOGO_MAX_HEIGHT preserving aspect
    lw, lh = logo.size
    scale = min(LOGO_MAX_WIDTH / lw, LOGO_MAX_HEIGHT / lh)
    new_w = max(1, int(lw * scale))
    new_h = max(1, int(lh * scale))
    logo = logo.resize((new_w, new_h), Image.LANCZOS)

    # White rounded-rectangle plate behind the logo for legibility on any background
    pad_x, pad_y = 60, 36
    plate_w = new_w + pad_x * 2
    plate_h = new_h + pad_y * 2
    radius = 36
    plate = Image.new("RGBA", (plate_w, plate_h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(plate)
    pd.rounded_rectangle((0, 0, plate_w, plate_h), radius=radius, fill=BRAND_WHITE + (245,))

    # Position: horizontally centered, vertically centered in LOGO_REGION
    region_x1, region_y1, region_x2, region_y2 = LOGO_REGION
    region_cx = (region_x1 + region_x2) // 2
    region_cy = (region_y1 + region_y2) // 2
    plate_x = region_cx - plate_w // 2
    plate_y = region_cy - plate_h // 2

    # Soft shadow under the plate
    shadow = Image.new("RGBA", (plate_w + 40, plate_h + 40), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        (20, 20, plate_w + 20, plate_h + 20),
        radius=radius,
        fill=(0, 0, 0, 130),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=14))

    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(shadow, (plate_x - 20, plate_y - 12))
    canvas_rgba.alpha_composite(plate, (plate_x, plate_y))
    canvas_rgba.alpha_composite(logo, (plate_x + pad_x, plate_y + pad_y))
    return canvas_rgba.convert("RGB")


def compose_thumbnail(
    headline: str,
    background_path: Path | None,
    cutout_path: Path,
    output_path: Path,
    brand_logo_path: Path | None = None,
) -> Path:
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), BRAND_NAVY)

    # 1. Background
    bg = None
    if background_path is not None:
        try:
            loaded = Image.open(background_path).convert("RGB")
            bg = _cover_crop(loaded, CANVAS_W, CANVAS_H)
        except Exception as e:
            logger.warning("Failed to load background %s: %s", background_path, e)
            bg = None
    if bg is None:
        bg = _vertical_gradient((CANVAS_W, CANVAS_H), BRAND_NAVY, BRAND_NAVY_DEEP)
    canvas.paste(bg, (0, 0))

    # 2. Darken overlay
    overlay = _build_darken_overlay()
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba = Image.alpha_composite(canvas_rgba, overlay)
    canvas = canvas_rgba.convert("RGB")

    # 3. Brand logo badge (above headline)
    if brand_logo_path is not None and Path(brand_logo_path).exists():
        canvas = _place_brand_logo(canvas, Path(brand_logo_path))

    # 4. Headline text — two-tone alternating per line, crisp outline
    draw = ImageDraw.Draw(canvas)
    region_x1, region_y1, region_x2, region_y2 = HEADLINE_REGION
    max_w = region_x2 - region_x1
    words = headline.split()
    longest_word = max(words, key=len) if words else ""

    size = 200
    font = _load_font(size)
    while size > 80:
        font = _load_font(size)
        if _text_width(draw, longest_word, font) <= max_w and _text_width(draw, headline, font) <= max_w * 2.6:
            break
        size -= 10
    if size < 80:
        size = 80
    font = _load_font(size)

    lines = _wrap_lines(draw, words, font, max_w, max_lines=3)

    line_heights = [_text_height(draw, ln, font) for ln in lines]
    line_spacing = int(size * 0.18)
    total_h = sum(line_heights) + line_spacing * max(len(lines) - 1, 0)

    region_h = region_y2 - region_y1
    start_y = region_y1 + (region_h - total_h) // 2

    cur_y = start_y
    cx = CANVAS_W // 2
    # Two-tone: white for first/last, accent blue for middle (or alternating if 2 lines)
    if len(lines) == 1:
        colors = [BRAND_WHITE]
    elif len(lines) == 2:
        colors = [BRAND_ACCENT_BLUE, BRAND_WHITE]
    else:  # 3 lines
        colors = [BRAND_ACCENT_BLUE, BRAND_WHITE, BRAND_ACCENT_BLUE]

    outline_width = max(2, size // 40)
    for ln, lh, color in zip(lines, line_heights, colors):
        _draw_text_with_outline(
            draw,
            (cx, cur_y),
            ln,
            font,
            fill=color,
            outline=BRAND_NAVY_DEEP,
            outline_width=outline_width,
            anchor="mt",
        )
        cur_y += lh + line_spacing

    # 4. Circle PiP avatar badge (bottom-right, inside safe zone)
    pip = _circle_pip(cutout_path, PIP_DIAMETER)
    if pip is not None:
        canvas_rgba = canvas.convert("RGBA")
        px = PIP_CENTER[0] - PIP_DIAMETER // 2
        py = PIP_CENTER[1] - PIP_DIAMETER // 2
        # Soft drop shadow under the badge
        shadow = Image.new("RGBA", (PIP_DIAMETER + 40, PIP_DIAMETER + 40), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.ellipse((20, 20, PIP_DIAMETER + 20, PIP_DIAMETER + 20), fill=(0, 0, 0, 140))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=12))
        canvas_rgba.alpha_composite(shadow, (px - 20, py - 12))
        canvas_rgba.alpha_composite(pip, (px, py))
        canvas = canvas_rgba.convert("RGB")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
    return output_path
