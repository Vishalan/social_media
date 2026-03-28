"""
B-roll type: stats_card

Claude extracts 3-5 measurable stats from the script.
PIL renders animated text cards showing each stat sequentially.
FFmpeg assembles the frames into a video.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic
from PIL import Image, ImageDraw, ImageFont

from .base import BrollBase, BrollError

if TYPE_CHECKING:
    from pipeline import VideoJob

logger = logging.getLogger(__name__)

# Card dimensions
_CARD_WIDTH = 1080
_CARD_HEIGHT = 540

# Brand colours (dark navy theme)
_BG_COLOR = (18, 18, 25)
_ACCENT_COLOR = (99, 102, 241)  # Indigo
_VALUE_COLOR = (255, 255, 255)
_LABEL_COLOR = (160, 160, 180)

# Typography
_VALUE_FONT_SIZE = 72
_LABEL_FONT_SIZE = 28

_STATS_SCHEMA = {
    "type": "object",
    "properties": {
        "stats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "value": {"type": "string"},
                    "label": {"type": "string"},
                },
                "required": ["value", "label"],
            },
            "minItems": 2,
            "maxItems": 5,
        }
    },
    "required": ["stats"],
    "additionalProperties": False,
}


def _load_fonts() -> tuple[ImageFont.ImageFont, ImageFont.ImageFont]:
    """Try to load DejaVuSans fonts; fall back to PIL default."""
    try:
        value_font: ImageFont.ImageFont = ImageFont.truetype(
            "DejaVuSans-Bold.ttf", _VALUE_FONT_SIZE
        )
        label_font: ImageFont.ImageFont = ImageFont.truetype(
            "DejaVuSans.ttf", _LABEL_FONT_SIZE
        )
        return value_font, label_font
    except OSError:
        default = ImageFont.load_default()
        return default, default


def _render_frame(
    stats_to_show: list[dict],
    total_stats: int,
) -> Image.Image:
    """Render a single card frame showing the given stats.

    Args:
        stats_to_show: Subset of stats revealed so far.
        total_stats: Total number of stats in the sequence (used for layout).

    Returns:
        A PIL Image of size (CARD_WIDTH × CARD_HEIGHT).
    """
    img = Image.new("RGB", (_CARD_WIDTH, _CARD_HEIGHT), color=_BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Top accent line
    draw.rectangle([0, 0, _CARD_WIDTH, 4], fill=_ACCENT_COLOR)

    value_font, label_font = _load_fonts()

    slot_height = 500 // total_stats
    for i, stat in enumerate(stats_to_show):
        y_center = 30 + i * slot_height + slot_height // 2
        # Value (large, white)
        draw.text(
            (_CARD_WIDTH // 2, y_center - 20),
            stat["value"],
            fill=_VALUE_COLOR,
            font=value_font,
            anchor="mm",
        )
        # Label (smaller, muted)
        draw.text(
            (_CARD_WIDTH // 2, y_center + 40),
            stat["label"],
            fill=_LABEL_COLOR,
            font=label_font,
            anchor="mm",
        )

    return img


class StatsCardGenerator(BrollBase):
    """
    B-roll generator that extracts measurable stats from the script via
    Claude and renders an animated sequential-reveal text card using PIL
    and FFmpeg.

    Each stat is revealed one-by-one over the target duration.  The card
    uses a dark navy background with an indigo accent stripe, consistent
    with the @commoncreed brand palette.

    Raises:
        BrollError: If Claude returns fewer than 2 stats, or if FFmpeg
                    fails to encode the output clip.
    """

    def __init__(self, anthropic_client: AsyncAnthropic) -> None:
        self._client = anthropic_client

    async def generate(
        self,
        job: "VideoJob",
        target_duration_s: float,
        output_path: str,
    ) -> str:
        """
        Generate a stats-card b-roll clip.

        Args:
            job: VideoJob containing the generated script.
            target_duration_s: Desired clip length in seconds.
            output_path: Local file path where the MP4 will be saved.

        Returns:
            output_path on success.

        Raises:
            BrollError: On insufficient stats or FFmpeg encoding failure.
        """
        # --- Step 1: Extract stats via Claude ---------------------------------
        script_text: str = job.script.get("script", job.script.get("body", ""))

        logger.debug("StatsCardGenerator: calling Claude to extract stats")
        response = await self._client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=400,
            system=(
                "You are a data extractor. Extract the most compelling measurable "
                "stats or comparisons from the text."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Extract 3-5 key stats from this script for an AI & Technology video:\n\n"
                        f"{script_text[:800]}"
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
                f"insufficient stats in script: Claude returned {len(stats)}, need ≥ 2"
            )

        logger.info(
            "StatsCardGenerator: extracted %d stats from script", len(stats)
        )

        # --- Step 2: Render frames with PIL -----------------------------------
        frames: list[Image.Image] = []
        for i in range(1, len(stats) + 1):
            img = _render_frame(stats[:i], len(stats))
            frames.append(img)

        # --- Step 3: Assemble with FFmpeg -------------------------------------
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            frame_paths: list[Path] = []
            for i, img in enumerate(frames):
                p = tmp_dir / f"frame_{i:02d}.png"
                img.save(p)
                frame_paths.append(p)

            frame_duration = target_duration_s / len(frames)
            concat_file = tmp_dir / "concat.txt"
            with open(concat_file, "w") as f:
                for p in frame_paths:
                    f.write(f"file '{p}'\nduration {frame_duration:.3f}\n")
                # FFmpeg concat demuxer requires a final entry with a tiny
                # non-zero duration to flush the last frame correctly.
                f.write(f"file '{frame_paths[-1]}'\nduration 0.001\n")

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-t", str(target_duration_s),
                output_path,
            ]
            logger.debug("StatsCardGenerator: ffmpeg cmd: %s", " ".join(cmd))

            try:
                await asyncio.to_thread(
                    subprocess.run, cmd, check=True, capture_output=True
                )
            except subprocess.CalledProcessError as e:
                raise BrollError(
                    f"ffmpeg failed: {e.stderr.decode(errors='replace')}"
                ) from e
        finally:
            # Best-effort cleanup of temp directory
            shutil.rmtree(tmp_dir, ignore_errors=True)

        logger.info(
            "StatsCardGenerator: clip saved to %s (stats=%d, duration=%.1fs)",
            output_path,
            len(stats),
            target_duration_s,
        )
        return output_path
