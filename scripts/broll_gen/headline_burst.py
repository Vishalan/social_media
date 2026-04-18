"""
B-roll type: headline_burst

Claude extracts 3-5 short punchy lines from the script (the "one fact" format).
Each line appears full-screen on a flat bold color, fading in over 8 frames then
holding for 1.5s — the "did you know" reel style that dominates social feeds.

No external services needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic
from PIL import Image, ImageDraw, ImageFont

from .base import BrollBase, BrollError
from video_edit.video_editor import FFMPEG

# Dual-import so this module works whether pytest / CLI runs from repo root
# (``python -m scripts.pipeline``) or from ``scripts/`` directly.
try:
    from scripts.branding import (
        BOLD_FONT_CANDIDATES,
        REGULAR_FONT_CANDIDATES,
        find_font,
    )
except ImportError:  # pragma: no cover — fallback when cwd is scripts/
    from branding import (  # type: ignore[no-redef]
        BOLD_FONT_CANDIDATES,
        REGULAR_FONT_CANDIDATES,
        find_font,
    )

if TYPE_CHECKING:
    from pipeline import VideoJob

logger = logging.getLogger(__name__)

_W = 1080
_H = 960
_FPS = 30

# Each line: 8 frames fade-in + 37 frames hold = 45 frames = 1.5s
_FADE_FRAMES = 8
_HOLD_FRAMES = 37
_FRAMES_PER_LINE = _FADE_FRAMES + _HOLD_FRAMES

# Flat bold solid colors per line (cycles through these)
_FLAT_COLORS = [
    (255, 215, 0),    # Yellow
    (20, 30, 200),    # Deep blue
    (210, 45, 45),    # Coral/red
    (15, 155, 75),    # Emerald green
    (235, 235, 235),  # Off-white (text will be dark)
]
_ACCENT = (99, 102, 241)             # Indigo accent line
_TEXT_COLOR = (255, 255, 255)
_SUBTEXT_COLOR = (180, 185, 240)

# Font candidate lists come from scripts.branding — single source of truth.
# Relative paths (in-repo ``assets/fonts/...``) are resolved against the project
# root so downstream helpers (``_try_font``, ``_auto_font_size``) can iterate
# them directly via ``ImageFont.truetype`` regardless of the caller's CWD.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_candidate(c: str) -> str:
    p = Path(c)
    return str(p if p.is_absolute() else _PROJECT_ROOT / p)


_BOLD_CANDIDATES = [_resolve_candidate(c) for c in BOLD_FONT_CANDIDATES]
_REG_CANDIDATES = [_resolve_candidate(c) for c in REGULAR_FONT_CANDIDATES]

# Font validation: log at import time if no bold font is resolvable. We use
# branding.find_font (which returns an absolute, existing path) so the check
# matches what runtime rendering will actually load.
try:
    _resolved_bold = find_font("bold")
    logger.debug("headline_burst: bold font resolved to %s", _resolved_bold)
except FileNotFoundError:
    logger.critical(
        "headline_burst: no bold font found — tried: %s. "
        "Text will fall back to PIL default (low quality). "
        "Install a bold TTF font at one of the listed paths or ship "
        "assets/fonts/Inter-Bold.ttf in the image.",
        _BOLD_CANDIDATES,
    )

_LINES_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "string",
                "description": (
                    "A single punchy fact or claim from the script. "
                    "Max 6 words. No punctuation except % $ x."
                ),
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}


def _try_font(candidates: list[str], size: int) -> ImageFont.ImageFont:
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, AttributeError):
            continue
    return ImageFont.load_default()


def _ease_out_quad(t: float) -> float:
    return 1.0 - (1.0 - t) ** 2


def _auto_font_size(
    text: str,
    max_w: int,
    candidates: list[str],
    max_size: int = 160,
    min_size: int = 60,
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


def _render_line_frame(
    line: str,
    frame_idx: int,
    line_idx: int,
    total_lines: int,
    flat_color: tuple,
    canvas_w: int | None = None,
) -> Image.Image:
    """Render one animation frame for one headline line.

    ``canvas_w`` overrides the default card width (``_W`` = 1080). Height is
    held at ``_H``. Per Unit B2's "no relayout" constraint, font-size
    auto-scaling already happens via ``_auto_font_size`` so text always fits
    the narrower canvas.
    """
    w = int(canvas_w) if canvas_w else _W
    img = Image.new("RGB", (w, _H), flat_color)
    draw = ImageDraw.Draw(img)

    # Alpha / scale based on fade-in progress
    if frame_idx < _FADE_FRAMES:
        t = frame_idx / _FADE_FRAMES
        alpha = _ease_out_quad(t)           # 0.0 → 1.0
        scale = 0.75 + 0.25 * alpha         # 0.75 → 1.0
    else:
        alpha = 1.0
        scale = 1.0

    max_text_w = int(w * 0.88)
    font, fsize = _auto_font_size(line, max_text_w, _BOLD_CANDIDATES, max_size=220, min_size=80)

    # Render text to a temp surface so we can scale it for the pop-in effect
    if scale < 0.99:
        scaled_size = max(20, int(fsize * scale))
        font = _try_font(_BOLD_CANDIDATES, scaled_size)

    # Text color: dark on off-white card, white (alpha-modulated) on all others
    if flat_color == (235, 235, 235):
        _text_fill = (20, 20, 20)
        _shadow_fill = (180, 180, 180)
    else:
        text_r = int(255 * alpha)
        text_g = int(255 * alpha)
        text_b = int(255 * alpha)
        _text_fill = (text_r, text_g, text_b)
        _shadow_fill = (0, 0, 0)

    cx = w // 2
    cy = _H // 2

    # Shadow
    draw.text(
        (cx + 3, cy + 5),
        line,
        fill=_shadow_fill,
        font=font,
        anchor="mm",
    )
    draw.text((cx, cy), line, fill=_text_fill, font=font, anchor="mm")

    # Small label line at bottom: "LINE X OF Y"
    label_font = _try_font(_REG_CANDIDATES, 28)
    label_alpha = int(180 * alpha)
    label_text = f"{'─' * 3}  {line_idx + 1} / {total_lines}  {'─' * 3}"
    draw.text(
        (cx, _H - 56),
        label_text,
        fill=(label_alpha, label_alpha, int(label_alpha * 1.2)),
        font=label_font,
        anchor="mm",
    )

    # Top + bottom accent bars
    bar_alpha = int(255 * alpha)
    draw.rectangle([0, 0, w, 5], fill=_ACCENT)
    draw.rectangle([0, _H - 5, w, _H], fill=_ACCENT)

    # Thin horizontal rule above text (decorative)
    rule_y = cy - int(fsize * scale * 0.75)
    rule_alpha = int(80 * alpha)
    draw.line(
        [(w // 4, rule_y), (3 * w // 4, rule_y)],
        fill=(rule_alpha, rule_alpha, int(rule_alpha * 1.5)),
        width=1,
    )

    return img


async def render_lines_clip(
    lines: list[str],
    duration_s: float,
    output_path: str,
    tmp_dir: Path,
) -> None:
    """
    Render given lines to a clip of exactly duration_s.
    Called by the mixed timeline assembler — bypasses Claude extraction.
    Distributes frames evenly across lines to fill the target duration.
    """
    if not lines:
        lines = ["..."]

    total_frames = max(1, int(round(duration_s * _FPS)))
    frames_per_line = max(_FRAMES_PER_LINE, total_frames // len(lines))

    frame_paths: list[Path] = []
    for l_idx, line in enumerate(lines):
        flat_color = _FLAT_COLORS[l_idx % len(_FLAT_COLORS)]
        remaining = total_frames - len(frame_paths)
        is_last = (l_idx == len(lines) - 1)
        n_frames = remaining if is_last else frames_per_line
        for f_idx in range(n_frames):
            actual_f = min(f_idx, _FRAMES_PER_LINE - 1)
            img = _render_line_frame(line, actual_f, l_idx, len(lines), flat_color)
            p = tmp_dir / f"hl_{l_idx:02d}_{f_idx:04d}.png"
            img.save(p)
            frame_paths.append(p)
        if len(frame_paths) >= total_frames:
            break

    concat_file = tmp_dir / "hl_concat.txt"
    frame_dur = 1.0 / _FPS
    with open(concat_file, "w") as f:
        for p in frame_paths:
            f.write(f"file '{p}'\nduration {frame_dur:.6f}\n")
        f.write(f"file '{frame_paths[-1]}'\nduration 0.001\n")

    cmd = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", str(_FPS), "-t", str(duration_s),
        str(output_path),
    ]
    await asyncio.to_thread(subprocess.run, cmd, check=True, capture_output=True)


class HeadlineBurstGenerator(BrollBase):
    """
    Cinematic "one fact at a time" b-roll.

    Claude extracts 3-5 short punchy lines from the script (≤6 words each).
    Each line appears full-screen on a rich gradient with a fade+scale pop-in,
    then holds for a beat — the "did you know" format that performs well on
    TikTok, Reels, and Shorts.

    Raises:
        BrollError: If Claude returns fewer than 3 lines or FFmpeg fails.
    """

    def __init__(
        self,
        anthropic_client: AsyncAnthropic,
        width_override: int | None = None,
    ) -> None:
        """
        Args:
            anthropic_client: AsyncAnthropic client for extracting punchy lines.
            width_override: If provided, overrides the default card width
                (``_W`` = 1080). Font size auto-scales via ``_auto_font_size``
                so text fits the narrower canvas (e.g. 540).
        """
        self._client = anthropic_client
        self._canvas_w = int(width_override) if width_override else _W

    async def generate(
        self,
        job: "VideoJob",
        target_duration_s: float,
        output_path: str,
    ) -> str:
        script_text: str = job.script.get("script", job.script.get("body", ""))
        title: str = job.topic.get("title", "")

        logger.debug("HeadlineBurstGenerator: calling Claude for punchy lines")
        response = await self._client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=300,
            system=(
                "You extract the most attention-grabbing, shareable facts or claims "
                "from a short-form video script. Each line must be a punchy statement "
                "that works as a standalone 'did you know' slide. ≤6 words per line. "
                "No full sentences. No punctuation except % $ x and numbers."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Topic: {title}\n\n"
                        f"Script:\n{script_text[:1000]}\n\n"
                        "Extract 3-5 punchy facts or claims."
                    ),
                }
            ],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": _LINES_SCHEMA,
                }
            },
        )

        data = json.loads(response.content[0].text)
        lines: list[str] = data["lines"]

        if len(lines) < 3:
            raise BrollError(
                f"too few lines: Claude returned {len(lines)}, need ≥ 3"
            )
        lines = lines[:5]
        logger.info("HeadlineBurstGenerator: %d lines extracted", len(lines))

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix="headline_"))
        try:
            frame_paths: list[Path] = []
            for l_idx, line in enumerate(lines):
                flat_color = _FLAT_COLORS[l_idx % len(_FLAT_COLORS)]
                for f_idx in range(_FRAMES_PER_LINE):
                    img = _render_line_frame(
                        line, f_idx, l_idx, len(lines), flat_color,
                        canvas_w=self._canvas_w,
                    )
                    p = tmp_dir / f"f_{l_idx:02d}_{f_idx:03d}.png"
                    img.save(p)
                    frame_paths.append(p)

            concat_file = tmp_dir / "concat.txt"
            frame_dur = 1.0 / _FPS
            with open(concat_file, "w") as f:
                for p in frame_paths:
                    f.write(f"file '{p}'\nduration {frame_dur:.6f}\n")
                f.write(f"file '{frame_paths[-1]}'\nduration 0.001\n")

            actual_duration = len(frame_paths) / _FPS
            cmd = [
                FFMPEG, "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-r", str(_FPS),
                "-t", str(actual_duration),
                output_path,
            ]
            try:
                await asyncio.to_thread(
                    subprocess.run, cmd, check=True, capture_output=True
                )
            except subprocess.CalledProcessError as e:
                raise BrollError(
                    f"ffmpeg failed: {e.stderr.decode(errors='replace')[:500]}"
                ) from e
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        logger.info(
            "HeadlineBurstGenerator: saved %s (lines=%d, %.1fs)",
            output_path, len(lines), actual_duration,
        )
        return output_path
