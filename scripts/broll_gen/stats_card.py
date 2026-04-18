"""
B-roll type: stats_card (animated counter)

Claude extracts 2-4 numeric stats from the script.
Each stat is shown full-card with a number counting up from 0 (ease-out, 2s)
then holding for 1s, so the viewer feels the scale of the number.
A circular progress arc fills in sync with the count.

FFmpeg encodes at 30 fps.
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

if TYPE_CHECKING:
    from pipeline import VideoJob

logger = logging.getLogger(__name__)

# Card dimensions — match the half-screen slot in VideoEditor (OUTPUT_HEIGHT // 2)
_W = 1080
_H = 960
_FPS = 30

# Colours
_BG_TOP = (10, 10, 22)
_BG_BOT = (5, 5, 14)
_ACCENT = (99, 102, 241)       # indigo
_RING_BG = (30, 32, 60)        # dim ring track
_VALUE_COLOR = (255, 255, 255)
_UNIT_COLOR = (180, 185, 240)
_LABEL_COLOR = (130, 135, 175)
_DOT_ACTIVE = (99, 102, 241)
_DOT_INACTIVE = (40, 42, 70)

# Timing
_COUNT_FRAMES = 50   # 1.67s counting
_HOLD_FRAMES = 25    # 0.83s hold  → 2.5s total per stat
_FRAMES_PER_STAT = _COUNT_FRAMES + _HOLD_FRAMES

# Ring geometry
_RING_CX = _W // 2
_RING_CY = _H // 2 - 60
_RING_R = 290
_RING_THICK = 18

# Font candidates (bold for value, regular for label)
_BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
_REG_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

_STATS_SCHEMA = {
    "type": "object",
    "properties": {
        "stats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "numeric": {
                        "type": "number",
                        "description": "The bare number to animate (e.g. 15, 60, 0.08)",
                    },
                    "unit": {
                        "type": "string",
                        "description": (
                            "Text shown right after the number (e.g. 'x faster', '%', '/M tokens'). "
                            "Keep ≤ 12 chars."
                        ),
                    },
                    "label": {
                        "type": "string",
                        "description": "Short description shown below the value. Keep ≤ 30 chars.",
                    },
                },
                "required": ["numeric", "unit", "label"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["stats"],
    "additionalProperties": False,
}


def _try_font(candidates: list[str], size: int) -> ImageFont.ImageFont:
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, AttributeError):
            continue
    return ImageFont.load_default()


def _ease_out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def _draw_gradient(img: Image.Image) -> None:
    draw = ImageDraw.Draw(img)
    r0, g0, b0 = _BG_TOP
    r1, g1, b1 = _BG_BOT
    w, h = img.size
    for y in range(h):
        t = y / max(h - 1, 1)
        draw.line(
            [(0, y), (w, y)],
            fill=(
                int(r0 + (r1 - r0) * t),
                int(g0 + (g1 - g0) * t),
                int(b0 + (b1 - b0) * t),
            ),
        )


def _draw_ring(
    draw: ImageDraw.ImageDraw,
    progress: float,
    cx: int | None = None,
    cy: int | None = None,
) -> None:
    """Draw the background track ring and the filled progress arc."""
    rcx = _RING_CX if cx is None else cx
    rcy = _RING_CY if cy is None else cy
    bbox = [
        rcx - _RING_R,
        rcy - _RING_R,
        rcx + _RING_R,
        rcy + _RING_R,
    ]
    # Track (full ring, dim)
    draw.arc(bbox, start=0, end=360, fill=_RING_BG, width=_RING_THICK)

    # Progress arc — clockwise from 12 o'clock (-90°)
    if progress > 0.005:
        end_angle = -90 + 360 * min(progress, 1.0)
        draw.arc(bbox, start=-90, end=end_angle, fill=_ACCENT, width=_RING_THICK)

        # Bright dot at the arc tip
        tip_rad = math.radians(end_angle)
        tx = int(rcx + _RING_R * math.cos(tip_rad))
        ty = int(rcy + _RING_R * math.sin(tip_rad))
        r = _RING_THICK // 2 + 2
        draw.ellipse([tx - r, ty - r, tx + r, ty + r], fill=_ACCENT)


def _format_value(numeric: float, progress: float) -> str:
    """Return the animated numeric string at the given progress (0‑1)."""
    current = numeric * progress
    if numeric == int(numeric) and numeric < 1000:
        return str(int(round(current)))
    if numeric < 10:
        return f"{current:.1f}"
    return str(int(round(current)))


def _render_stat_frame(
    stat: dict,
    frame_idx: int,          # 0 … _FRAMES_PER_STAT-1
    stat_idx: int,
    total_stats: int,
    canvas_w: int | None = None,
) -> Image.Image:
    """Render one animation frame for one stat.

    ``canvas_w`` overrides the default card width (``_W``). Height is held at
    ``_H`` — the card is designed as a half-screen slot so vertical layout is
    the invariant. When ``canvas_w`` is <=0 or ``None`` the default width is
    used. At narrow widths (e.g. 540) the ring geometry (``_RING_R=290``)
    does not auto-scale; that is flagged as a follow-up per Unit B2 spec.
    """
    w = int(canvas_w) if canvas_w else _W
    img = Image.new("RGB", (w, _H))
    _draw_gradient(img)
    draw = ImageDraw.Draw(img)
    # Horizontal anchors derived from the actual canvas width. Ring geometry
    # (radius/thickness) is held at module defaults per the "no relayout"
    # constraint — a narrow canvas may visually clip the ring and text.
    ring_cx = w // 2
    ring_cy = _RING_CY

    # Progress (0→1 during count phase, stays 1 during hold)
    if frame_idx < _COUNT_FRAMES:
        t = frame_idx / _COUNT_FRAMES
        progress = _ease_out_cubic(t)
    else:
        progress = 1.0

    _draw_ring(draw, progress, cx=ring_cx, cy=ring_cy)

    numeric: float = float(stat["numeric"])
    unit: str = stat["unit"]
    label: str = stat["label"]

    # Value string (number)
    val_str = _format_value(numeric, progress)

    # Font sizes
    val_font = _try_font(_BOLD_CANDIDATES, 160)
    unit_font = _try_font(_BOLD_CANDIDATES, 72)
    label_font = _try_font(_REG_CANDIDATES, 44)
    dot_font = _try_font(_REG_CANDIDATES, 24)

    # Measure combined value + unit width to centre them together
    dummy = Image.new("RGB", (1, 1))
    dd = ImageDraw.Draw(dummy)
    val_bbox = dd.textbbox((0, 0), val_str, font=val_font)
    unit_bbox = dd.textbbox((0, 0), unit, font=unit_font)

    val_w = val_bbox[2] - val_bbox[0]
    unit_w = unit_bbox[2] - unit_bbox[0]
    gap = 12
    total_w = val_w + gap + unit_w

    # Draw value + unit centred inside the ring
    left_x = ring_cx - total_w // 2
    val_y = ring_cy - (val_bbox[3] - val_bbox[1]) // 2

    # Subtle glow behind number (slightly larger text in a dim colour)
    draw.text(
        (left_x - 1, val_y + 2),
        val_str,
        fill=(60, 62, 120),
        font=val_font,
    )
    draw.text((left_x, val_y), val_str, fill=_VALUE_COLOR, font=val_font)

    unit_x = left_x + val_w + gap
    unit_y = val_y + (val_bbox[3] - val_bbox[1]) - (unit_bbox[3] - unit_bbox[1]) - 8
    draw.text((unit_x, unit_y), unit, fill=_UNIT_COLOR, font=unit_font)

    # Label below the ring
    label_y = ring_cy + _RING_R + 40
    draw.text((w // 2, label_y), label.upper(), fill=_LABEL_COLOR,
              font=label_font, anchor="mt")

    # Dot indicators at the bottom
    dot_spacing = 24
    total_dots_w = total_stats * dot_spacing
    dot_x0 = (w - total_dots_w) // 2 + dot_spacing // 2
    dot_y = _H - 50
    for d in range(total_stats):
        cx = dot_x0 + d * dot_spacing
        r = 7 if d == stat_idx else 5
        fill = _DOT_ACTIVE if d == stat_idx else _DOT_INACTIVE
        draw.ellipse([cx - r, dot_y - r, cx + r, dot_y + r], fill=fill)

    # Thin top accent line
    draw.rectangle([0, 0, w, 4], fill=_ACCENT)

    return img


async def render_single_stat_clip(
    stat: dict,
    duration_s: float,
    output_path: str,
    tmp_dir: Path,
) -> None:
    """
    Render a single stat animation to output_path, padded/trimmed to duration_s.
    Called by the mixed timeline assembler — bypasses Claude extraction.
    """
    frame_paths: list[Path] = []
    for f_idx in range(_FRAMES_PER_STAT):
        img = _render_stat_frame(stat, f_idx, 0, 1)
        p = tmp_dir / f"stat_{f_idx:03d}.png"
        img.save(p, optimize=False)
        frame_paths.append(p)

    # Hold the final completed frame to reach duration_s
    natural_s = _FRAMES_PER_STAT / _FPS
    if duration_s > natural_s:
        hold_frames = int((duration_s - natural_s) * _FPS)
        last = frame_paths[-1]
        for i in range(hold_frames):
            p = tmp_dir / f"stat_hold_{i:04d}.png"
            import shutil as _sh
            _sh.copy2(last, p)
            frame_paths.append(p)

    concat_file = tmp_dir / "stat_concat.txt"
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


class StatsCardGenerator(BrollBase):
    """
    Animated counter b-roll: each stat counts up from 0 with a circular
    progress ring. Much more engaging than static text cards.

    Claude extracts numeric stats (value + unit + label). Each stat plays
    as a 2.5-second animation: ~1.7s counting + ~0.8s hold.

    Raises:
        BrollError: If Claude returns fewer than 2 stats, or if FFmpeg fails.
    """

    def __init__(
        self,
        anthropic_client: AsyncAnthropic,
        width_override: int | None = None,
    ) -> None:
        """
        Args:
            anthropic_client: AsyncAnthropic client for extracting stats.
            width_override: If provided, overrides the default card width
                (``_W`` = 1080). At narrow widths (e.g. 540) the ring
                geometry does not auto-scale; flagged as a follow-up.
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

        logger.debug("StatsCardGenerator: calling Claude to extract numeric stats")
        response = await self._client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=500,
            system=(
                "You are a data extractor for short-form video. Extract the most "
                "compelling numeric stats or comparisons from the text. Each stat "
                "needs a bare number (numeric), a short unit string, and a brief label."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Extract 2-4 numeric stats from this AI & Technology script.\n\n"
                        f"{script_text[:1000]}"
                    ),
                }
            ],
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": _STATS_SCHEMA,
                }
            },
        )

        data = json.loads(response.content[0].text)
        stats: list[dict] = data["stats"]

        if len(stats) < 2:
            raise BrollError(
                f"insufficient stats: Claude returned {len(stats)}, need ≥ 2"
            )

        # Cap to 4 stats so the clip doesn't run too long
        stats = stats[:4]
        logger.info("StatsCardGenerator: %d stats extracted", len(stats))

        # Render all animation frames
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix="stats_"))
        try:
            frame_paths: list[Path] = []
            for s_idx, stat in enumerate(stats):
                for f_idx in range(_FRAMES_PER_STAT):
                    img = _render_stat_frame(
                        stat, f_idx, s_idx, len(stats),
                        canvas_w=self._canvas_w,
                    )
                    p = tmp_dir / f"f_{s_idx:02d}_{f_idx:03d}.png"
                    img.save(p, optimize=False)
                    frame_paths.append(p)

            # Write concat manifest (1 frame = 1/30 s)
            concat_file = tmp_dir / "concat.txt"
            frame_duration = 1.0 / _FPS
            with open(concat_file, "w") as f:
                for p in frame_paths:
                    f.write(f"file '{p}'\nduration {frame_duration:.6f}\n")
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
            logger.debug("StatsCardGenerator ffmpeg: %s", " ".join(cmd))
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
            "StatsCardGenerator: saved %s (stats=%d, %.1fs)",
            output_path, len(stats), actual_duration,
        )
        return output_path
