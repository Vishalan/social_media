"""
B-roll type: emphasis card

Minimal dark transition card with a single centered phrase.
Used as a visual pause at topic transitions — "THE FIX", "WHY IT MATTERS".
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from video_edit.video_editor import FFMPEG

# Constants
_W = 1080
_H = 1920
_FPS = 30
_FADE_FRAMES = 8
_BG = (12, 12, 20)
_TEXT_COLOR = (240, 240, 245)
_ACCENT = (99, 102, 241)

# Font candidates (same list as headline_burst)
_BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _try_font(candidates: list[str], size: int) -> ImageFont.ImageFont:
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, AttributeError):
            continue
    return ImageFont.load_default()


def _auto_font_size(
    text: str,
    max_w: int,
    candidates: list[str],
    max_size: int = 200,
    min_size: int = 100,
) -> tuple[ImageFont.ImageFont, int]:
    """Return the largest font size where text fits within max_w pixels."""
    dummy = Image.new("RGB", (1, 1))
    dd = ImageDraw.Draw(dummy)
    size = max_size
    while size >= min_size:
        font = _try_font(candidates, size)
        bbox = dd.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_w:
            return font, size
        size -= 8
    return _try_font(candidates, min_size), min_size


def _ease_out_quad(t: float) -> float:
    return 1.0 - (1.0 - t) ** 2


def _render_frame(
    phrase: str,
    frame_idx: int,
    font: ImageFont.ImageFont,
) -> Image.Image:
    """Render one frame of the emphasis card."""
    img = Image.new("RGB", (_W, _H), _BG)
    draw = ImageDraw.Draw(img)

    # Compute fade alpha
    if frame_idx < _FADE_FRAMES:
        t = frame_idx / _FADE_FRAMES
        alpha = _ease_out_quad(t)
    else:
        alpha = 1.0

    cx = _W // 2
    cy = _H // 2

    # Text (alpha-modulated)
    tr = int(_TEXT_COLOR[0] * alpha)
    tg = int(_TEXT_COLOR[1] * alpha)
    tb = int(_TEXT_COLOR[2] * alpha)
    draw.text((cx, cy), phrase, fill=(tr, tg, tb), font=font, anchor="mm")

    # Accent line above text: 50% of canvas width, centered, 3px thick
    line_w = int(_W * 0.50)
    line_x0 = cx - line_w // 2
    line_x1 = cx + line_w // 2

    # Position the accent line above the text
    bbox = draw.textbbox((cx, cy), phrase, font=font, anchor="mm")
    text_top = bbox[1]
    line_y = text_top - 40

    ar = int(_ACCENT[0] * alpha)
    ag = int(_ACCENT[1] * alpha)
    ab = int(_ACCENT[2] * alpha)
    draw.line([(line_x0, line_y), (line_x1, line_y)], fill=(ar, ag, ab), width=3)

    # Bottom accent line (mirror)
    text_bot = bbox[3]
    draw.line([(line_x0, text_bot + 40), (line_x1, text_bot + 40)],
              fill=(ar, ag, ab), width=3)

    return img


async def render_emphasis_clip(
    phrase: str,
    duration_s: float,
    output_path: str,
    tmp_dir: Path,
) -> None:
    """
    Render a minimal emphasis card clip.

    A single phrase on a near-black background with a thin indigo accent line,
    fading in over 8 frames then holding for the remainder of the duration.
    """
    total_frames = max(1, int(round(duration_s * _FPS)))

    # Pick font size once
    max_text_w = int(_W * 0.88)
    font, _fsize = _auto_font_size(phrase, max_text_w, _BOLD_CANDIDATES)

    # Render frames
    frame_paths: list[Path] = []
    held_frame: Image.Image | None = None

    for f_idx in range(total_frames):
        p = tmp_dir / f"emp_{f_idx:04d}.png"
        if f_idx < _FADE_FRAMES:
            img = _render_frame(phrase, f_idx, font)
            if f_idx == _FADE_FRAMES - 1:
                held_frame = img
            img.save(p)
        else:
            # After fade-in, all frames are identical
            if held_frame is None:
                held_frame = _render_frame(phrase, _FADE_FRAMES, font)
            held_frame.save(p)
        frame_paths.append(p)

    # Write FFmpeg concat manifest
    concat_file = tmp_dir / "emp_concat.txt"
    frame_dur = 1.0 / _FPS
    with open(concat_file, "w") as f:
        for p in frame_paths:
            f.write(f"file '{p}'\nduration {frame_dur:.6f}\n")
        f.write(f"file '{frame_paths[-1]}'\nduration 0.001\n")

    # Encode
    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", str(_FPS), "-t", str(duration_s),
        str(output_path),
    ]
    await asyncio.to_thread(subprocess.run, cmd, check=True, capture_output=True)
