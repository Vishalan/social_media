"""Stand-ins for the stages that are too slow to sit in an iteration loop.

Two stages dominate build time and neither affects the decisions being made
when the graphics are being worked on: lip sync runs about 22 seconds of
compute per second of video, and each generated clip costs roughly ten
minutes of GPU. Together they turn a four-minute build into forty.

A stand-in is only useful if it is HONEST about what it replaces. Black is
indistinguishable from a failed render, and a generic "placeholder" card is
indistinguishable from a placeholder for something else. Each one here states
what would have been generated and what it would have cost, so a reviewer can
read a frame and know both that it is deliberate and what the real thing will
contain.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .branding import BRAND

logger = logging.getLogger(__name__)


def _esc(text: str) -> str:
    """Escape for drawtext. Colons and backslashes are its metacharacters."""
    return (str(text).replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "’").replace("%", "\\%")
            .replace("[", "(").replace("]", ")"))


def _wrap(text: str, width: int, limit: int = 4) -> list[str]:
    out, cur = [], ""
    for w in str(text).split():
        trial = f"{cur} {w}".strip()
        if len(trial) <= width or not cur:
            cur = trial
        else:
            out.append(cur)
            cur = w
        if len(out) == limit:
            return out
    if cur:
        out.append(cur)
    return out


def card(out_path: str, *, width: int, height: int, fps: int,
         duration_s: float, label: str, detail: str = "",
         cost: str = "", accent: str = "0x5C9BFF",
         bands: tuple = (0.22, 0.50, 0.78)) -> str:
    """A labelled stand-in of exactly `duration_s`.

    Geometry and duration must match the real thing exactly: everything
    downstream — span layout, captions, the thumbnail frame — is computed from
    this file, so a stand-in that differs produces a timeline that is not the
    one that will ship.

    The label repeats down the frame because a stand-in is frequently cropped
    before it is seen and this code does not know where. A single centred
    label landed outside the presenter panel once and rendered as flat colour,
    which is exactly the black it replaced.
    """
    f = BRAND.font_black
    fr = BRAND.font_semi
    bar_w = int(width * 0.66)
    bar_x = (width - bar_w) // 2
    bar_h = max(4, int(height * 0.005))
    small = int(height * 0.0135)
    filters: list[str] = []

    for frac in bands:
        y = int(height * frac)
        filters += [
            f"drawbox=x={bar_x}:y={y}:w={bar_w}:h={bar_h}:color=0x2A3038@1:t=fill",
            f"drawbox=x={bar_x}:y={y}:w='{bar_w}*t/{duration_s:.3f}':h={bar_h}"
            f":color={accent}@1:t=fill",
            f"drawtext=fontfile={f}:text='{_esc(label)}'"
            f":fontsize={int(height * 0.019)}:fontcolor=0x9AA6B8"
            f":x=(w-text_w)/2:y={y - int(height * 0.044)}",
        ]
        # What the real render would contain, so the frame is reviewable.
        for i, line in enumerate(_wrap(detail, 46, 3)):
            filters.append(
                f"drawtext=fontfile={fr}:text='{_esc(line)}'"
                f":fontsize={small}:fontcolor=0x6B7688"
                f":x=(w-text_w)/2:y={y + int(height * 0.020) + i * int(small * 1.5)}")
        if cost:
            filters.append(
                f"drawtext=fontfile={fr}:text='{_esc(cost)}  "
                f"%{{eif\\:t\\:d}}s/{duration_s:.0f}s'"
                f":fontsize={small}:fontcolor=0x4E5866"
                f":x=(w-text_w)/2:y={y + int(height * 0.020) + 3 * int(small * 1.5)}")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"color=c=0x14171C:s={width}x{height}:r={fps}",
         "-t", f"{duration_s:.3f}", "-vf", ",".join(filters),
         "-c:v", "libx264", "-crf", "28", "-pix_fmt", "yuv420p", out_path],
        capture_output=True, text=True)
    if r.returncode != 0:
        # A stand-in that fails is worse than a plain one: the build stops for
        # a stage that was being skipped to save time.
        logger.warning("placeholder draw failed (%s) — flat panel instead",
                       r.stderr[-160:].replace("\n", " "))
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
             "-i", f"color=c=0x14171C:s={width}x{height}:r={fps}",
             "-t", f"{duration_s:.3f}", "-c:v", "libx264", "-crf", "30",
             "-pix_fmt", "yuv420p", out_path], check=True)
    return out_path
