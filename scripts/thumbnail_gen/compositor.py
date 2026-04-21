"""Pillow-based thumbnail compositor for 1080x1920 vertical thumbnails.

Per-channel style is driven by :class:`ThumbnailConfig`. ``None`` defaults
to CommonCreed's palette + font + PiP-enabled layout (byte-identical to
the pre-Unit-4 rendering, since the dataclass defaults mirror the
previous module-level constants). Vesper (Unit 5) passes its own config
with the horror palette, CormorantGaramond font, and ``pip_enabled=False``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

# ─── Canvas + safe-zone constants (aspect-locked to 9:16 for v1) ─────────────

CANVAS_W = 1080
CANVAS_H = 1920
TOP_SAFE_END = 288            # 15% reserved for platform UI
BOTTOM_SAFE_START = 1536      # 80%, reserved for platform UI

HEADLINE_REGION = (60, 620, 1020, 1380)  # (x1, y1, x2, y2)
LOGO_REGION = (60, 320, 1020, 580)
LOGO_MAX_HEIGHT = 220
LOGO_MAX_WIDTH = 720

# Circle PiP avatar
PIP_DIAMETER = 280
PIP_MARGIN = 60
PIP_CENTER = (
    CANVAS_W - PIP_MARGIN - PIP_DIAMETER // 2,
    BOTTOM_SAFE_START - PIP_MARGIN - PIP_DIAMETER // 2,
)
PIP_RING_WIDTH = 10

# ─── Default CommonCreed palette + font (module-level for back-compat) ──────

# Retained as module-level constants so any existing importer keeps working.
# :class:`ThumbnailConfig` mirrors these by default.
BRAND_NAVY = (24, 46, 89)             # background
BRAND_NAVY_DEEP = (16, 32, 64)        # bottom of gradient
BRAND_ACCENT_BLUE = (96, 156, 232)    # light blue text accent
BRAND_WHITE = (250, 250, 252)         # primary text

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_FONT_CANDIDATES = [_PROJECT_ROOT / "assets" / "fonts" / "Inter-Black.ttf"]


# ─── Per-channel style config ────────────────────────────────────────────────


@dataclass(frozen=True)
class ThumbnailConfig:
    """Per-channel thumbnail style.

    Fields default to CommonCreed's palette, font, and PiP-enabled layout
    so ``compose_thumbnail(...)`` with ``config=None`` keeps rendering
    byte-identical to the pre-Unit-4 behavior. Vesper's Unit 5 config
    overrides the palette to bone/oxidized-blood/graphite, the font to
    CormorantGaramond, and turns PiP off (faceless channel).
    """

    # Palette (RGB tuples).
    bg: Tuple[int, int, int] = BRAND_NAVY
    bg_deep: Tuple[int, int, int] = BRAND_NAVY_DEEP
    accent: Tuple[int, int, int] = BRAND_ACCENT_BLUE
    primary: Tuple[int, int, int] = BRAND_WHITE

    # Typography.
    font_candidates: Tuple[Path, ...] = field(
        default_factory=lambda: tuple(_FONT_CANDIDATES)
    )

    # PiP badge (face-forward CommonCreed). Vesper sets False (faceless).
    pip_enabled: bool = True

    # Future v1.1 knob: aspect. Only "9:16" is implemented; anything else
    # raises NotImplementedError at render time so the configuration
    # surface is honest (long-form thumbnails land in v1.1 with 16:9 work).
    aspect: str = "9:16"


_DEFAULT_CONFIG = ThumbnailConfig()


# ─── Primitive helpers ────────────────────────────────────────────────────────


def _vertical_gradient(
    size: Tuple[int, int],
    top_color: Tuple[int, int, int],
    bottom_color: Tuple[int, int, int],
) -> Image.Image:
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


def _load_font(
    size: int,
    candidates: Tuple[Path, ...] = tuple(_FONT_CANDIDATES),
) -> ImageFont.ImageFont:
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except Exception:  # pragma: no cover
                continue
    logger.warning("No font found among %s, using PIL default", candidates)
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


def _build_darken_overlay(bg_color: Tuple[int, int, int]) -> Image.Image:
    """Heavy darkening for image backgrounds — keeps the image as texture only.

    ``bg_color`` controls the tint of the overlay (CommonCreed darkens
    toward navy; Vesper darkens toward near-black).
    """
    overlay = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    px = overlay.load()
    for y in range(CANVAS_H):
        if y < TOP_SAFE_END:
            alpha = 200
        elif y > BOTTOM_SAFE_START:
            alpha = 200
        else:
            d = abs(y - CANVAS_H / 2) / (CANVAS_H / 2)
            alpha = int(140 + 60 * d)
        for x in range(CANVAS_W):
            px[x, y] = (bg_color[0] // 4, bg_color[1] // 4, bg_color[2] // 4, alpha)
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


def _circle_pip(
    cutout_path: Path,
    diameter: int,
    ring_color: Tuple[int, int, int],
) -> Image.Image | None:
    """Crop the portrait into a circular badge with a thin accent ring. Returns RGBA."""
    try:
        src = Image.open(cutout_path).convert("RGBA")
    except Exception as e:
        logger.warning("Failed to load cutout for PiP: %s", e)
        return None

    sw, sh = src.size
    head_h = int(sh * 0.55)
    if head_h < 10 or sw < 10:
        return None
    side = min(sw, head_h)
    cx = sw // 2
    cy = head_h // 2
    left = max(0, cx - side // 2)
    top = max(0, cy - side // 2)
    head = src.crop((left, top, left + side, top + side)).resize(
        (diameter, diameter), Image.LANCZOS
    )

    mask = Image.new("L", (diameter, diameter), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((0, 0, diameter, diameter), fill=255)

    badge = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    bd.ellipse((0, 0, diameter, diameter), fill=ring_color + (255,))
    head.putalpha(mask)
    inner_pad = PIP_RING_WIDTH
    inner_size = diameter - 2 * inner_pad
    head_inner = head.resize((inner_size, inner_size), Image.LANCZOS)
    badge.alpha_composite(head_inner, (inner_pad, inner_pad))
    return badge


def _place_brand_logo(
    canvas: Image.Image,
    logo_path: Path,
    plate_color: Tuple[int, int, int],
) -> Image.Image:
    """Composite a brand logo badge above the headline. ``plate_color`` is the
    rounded-rectangle plate fill behind the logo."""
    try:
        logo = Image.open(logo_path).convert("RGBA")
    except Exception as e:
        logger.warning("Failed to load brand logo %s: %s", logo_path, e)
        return canvas

    lw, lh = logo.size
    scale = min(LOGO_MAX_WIDTH / lw, LOGO_MAX_HEIGHT / lh)
    new_w = max(1, int(lw * scale))
    new_h = max(1, int(lh * scale))
    logo = logo.resize((new_w, new_h), Image.LANCZOS)

    pad_x, pad_y = 60, 36
    plate_w = new_w + pad_x * 2
    plate_h = new_h + pad_y * 2
    radius = 36
    plate = Image.new("RGBA", (plate_w, plate_h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(plate)
    pd.rounded_rectangle((0, 0, plate_w, plate_h), radius=radius, fill=plate_color + (245,))

    region_x1, region_y1, region_x2, region_y2 = LOGO_REGION
    region_cx = (region_x1 + region_x2) // 2
    region_cy = (region_y1 + region_y2) // 2
    plate_x = region_cx - plate_w // 2
    plate_y = region_cy - plate_h // 2

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
    *,
    config: Optional[ThumbnailConfig] = None,
) -> Path:
    """Render a 1080x1920 thumbnail and save as PNG.

    Args:
        headline: Title text to place in the headline region.
        background_path: Optional background image; falls back to a
            vertical palette gradient when missing.
        cutout_path: Owner-portrait cutout used for the PiP badge.
            Ignored when ``config.pip_enabled`` is False (e.g., Vesper).
        output_path: Where to write the PNG.
        brand_logo_path: Optional wordmark/logo plate above the headline.
        config: Per-channel style overrides. ``None`` uses CommonCreed
            defaults (byte-identical to pre-Unit-4).

    Returns:
        ``output_path`` (as a Path).
    """
    cfg = config or _DEFAULT_CONFIG

    if cfg.aspect != "9:16":
        raise NotImplementedError(
            f"thumbnail aspect {cfg.aspect!r} is not implemented; "
            "long-form (16:9) landing with v1.1 per "
            "docs/plans/2026-04-21-001-feat-vesper-horror-channel-plan.md Phase 2."
        )

    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), cfg.bg)

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
        bg = _vertical_gradient((CANVAS_W, CANVAS_H), cfg.bg, cfg.bg_deep)
    canvas.paste(bg, (0, 0))

    # 2. Darken overlay — tint derived from channel bg color
    overlay = _build_darken_overlay(cfg.bg)
    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba = Image.alpha_composite(canvas_rgba, overlay)
    canvas = canvas_rgba.convert("RGB")

    # 3. Brand logo badge (above headline)
    if brand_logo_path is not None and Path(brand_logo_path).exists():
        canvas = _place_brand_logo(canvas, Path(brand_logo_path), plate_color=cfg.primary)

    # 4. Headline text — two-tone alternating per line, crisp outline
    draw = ImageDraw.Draw(canvas)
    region_x1, region_y1, region_x2, region_y2 = HEADLINE_REGION
    max_w = region_x2 - region_x1
    words = headline.split()
    longest_word = max(words, key=len) if words else ""

    size = 200
    font = _load_font(size, cfg.font_candidates)
    while size > 80:
        font = _load_font(size, cfg.font_candidates)
        if (
            _text_width(draw, longest_word, font) <= max_w
            and _text_width(draw, headline, font) <= max_w * 2.6
        ):
            break
        size -= 10
    if size < 80:
        size = 80
    font = _load_font(size, cfg.font_candidates)

    lines = _wrap_lines(draw, words, font, max_w, max_lines=3)

    line_heights = [_text_height(draw, ln, font) for ln in lines]
    line_spacing = int(size * 0.18)
    total_h = sum(line_heights) + line_spacing * max(len(lines) - 1, 0)

    region_h = region_y2 - region_y1
    start_y = region_y1 + (region_h - total_h) // 2

    cur_y = start_y
    cx = CANVAS_W // 2
    # Two-tone: primary for first/last, accent for middle (or alternating if 2 lines)
    if len(lines) == 1:
        colors = [cfg.primary]
    elif len(lines) == 2:
        colors = [cfg.accent, cfg.primary]
    else:  # 3 lines
        colors = [cfg.accent, cfg.primary, cfg.accent]

    outline_width = max(2, size // 40)
    for ln, lh, color in zip(lines, line_heights, colors):
        _draw_text_with_outline(
            draw,
            (cx, cur_y),
            ln,
            font,
            fill=color,
            outline=cfg.bg_deep,
            outline_width=outline_width,
            anchor="mt",
        )
        cur_y += lh + line_spacing

    # 5. Circle PiP avatar badge (bottom-right) — skipped for faceless channels
    if cfg.pip_enabled:
        pip = _circle_pip(cutout_path, PIP_DIAMETER, ring_color=cfg.primary)
        if pip is not None:
            canvas_rgba = canvas.convert("RGBA")
            px = PIP_CENTER[0] - PIP_DIAMETER // 2
            py = PIP_CENTER[1] - PIP_DIAMETER // 2
            shadow = Image.new(
                "RGBA", (PIP_DIAMETER + 40, PIP_DIAMETER + 40), (0, 0, 0, 0)
            )
            sd = ImageDraw.Draw(shadow)
            sd.ellipse(
                (20, 20, PIP_DIAMETER + 20, PIP_DIAMETER + 20),
                fill=(0, 0, 0, 140),
            )
            shadow = shadow.filter(ImageFilter.GaussianBlur(radius=12))
            canvas_rgba.alpha_composite(shadow, (px - 20, py - 12))
            canvas_rgba.alpha_composite(pip, (px, py))
            canvas = canvas_rgba.convert("RGB")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
    return output_path


__all__ = [
    "BRAND_ACCENT_BLUE",
    "BRAND_NAVY",
    "BRAND_NAVY_DEEP",
    "BRAND_WHITE",
    "CANVAS_H",
    "CANVAS_W",
    "ThumbnailConfig",
    "compose_thumbnail",
]
