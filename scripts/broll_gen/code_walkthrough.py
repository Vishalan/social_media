"""
B-roll type: code_walkthrough

Claude generates a concise, relevant code snippet for the topic.
Pygments renders it to PNG with syntax highlighting.
FFmpeg animates a typewriter-style line-by-line reveal.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic

from broll_gen.base import BrollBase, BrollError
from video_edit.video_editor import FFMPEG

if TYPE_CHECKING:
    from pipeline import VideoJob

# ---------------------------------------------------------------------------
# Optional Pygments dependency — imported at module level so tests can patch
# the names directly on this module.
# ---------------------------------------------------------------------------
try:
    from pygments import highlight
    from pygments.formatters import ImageFormatter
    from pygments.lexers import PythonLexer
    _PYGMENTS_AVAILABLE = True
except ImportError:
    highlight = None  # type: ignore[assignment]
    ImageFormatter = None  # type: ignore[assignment,misc]
    PythonLexer = None  # type: ignore[assignment,misc]
    _PYGMENTS_AVAILABLE = False

logger = logging.getLogger(__name__)


class CodeWalkthroughGenerator(BrollBase):
    """
    Generate a code walkthrough b-roll clip.

    Steps:
    1. Ask Claude (haiku) to write a short, relevant Python snippet.
    2. Render each progressive reveal state to PNG via Pygments.
    3. Assemble the state PNGs into an MP4 using FFmpeg concat demuxer,
       producing a typewriter-style line-by-line reveal animation.
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
        Generate a code walkthrough MP4 for the given video job.

        Args:
            job: VideoJob with topic dict containing at least ``title``.
            target_duration_s: Desired clip length in seconds.
            output_path: Where to write the resulting MP4.

        Returns:
            output_path on success.

        Raises:
            BrollError: On empty Claude response, missing pygments, or FFmpeg
                        failure.
        """
        if not _PYGMENTS_AVAILABLE:
            raise BrollError("pygments not installed")

        with tempfile.TemporaryDirectory() as _tmp:
            tmp_dir = Path(_tmp)
            try:
                # ----------------------------------------------------------
                # Step 1: Generate code via Claude
                # ----------------------------------------------------------
                title = job.topic["title"]
                summary = job.topic.get("summary", "")[:200]

                logger.info("CodeWalkthroughGenerator: requesting code from Claude for %r", title)
                response = await self._client.messages.create(
                    model="claude-haiku-4-5",
                    max_tokens=300,
                    system=(
                        "You are a concise code snippet generator. "
                        "Output only raw code, no markdown fences, no explanation. "
                        "10-20 lines maximum."
                    ),
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                f"Write a concise, realistic Python code snippet for: {title}\n"
                                f"Context: {summary}"
                            ),
                        }
                    ],
                )

                code_text = response.content[0].text.strip()

                # Strip any accidental markdown fences
                code_text = re.sub(
                    r"^```[^\n]*\n?|```$", "", code_text, flags=re.MULTILINE
                ).strip()

                if not code_text or len(code_text.split("\n")) < 3:
                    raise BrollError("Claude returned empty code")

                # Cap at 20 lines
                lines = code_text.split("\n")[:20]
                logger.debug(
                    "CodeWalkthroughGenerator: got %d lines from Claude", len(lines)
                )

                # ----------------------------------------------------------
                # Step 2: Render each reveal state to PNG with Pygments
                # ----------------------------------------------------------
                formatter = ImageFormatter(
                    style="monokai",
                    font_name="Courier New",
                    font_size=24,
                    line_numbers=False,
                    image_pad=20,
                )
                lexer = PythonLexer()

                state_pngs: list[Path] = []
                for i in range(1, len(lines) + 1):
                    partial_code = "\n".join(lines[:i])
                    png_bytes: bytes = highlight(partial_code, lexer, formatter)
                    state_path = tmp_dir / f"state_{i:02d}.png"
                    state_path.write_bytes(png_bytes)
                    state_pngs.append(state_path)

                # ----------------------------------------------------------
                # Step 3: FFmpeg typewriter animation via concat demuxer
                # ----------------------------------------------------------
                frame_duration = target_duration_s / len(lines)

                concat_file = tmp_dir / "concat.txt"
                with open(concat_file, "w") as f:
                    for png in state_pngs:
                        f.write(f"file '{png}'\nduration {frame_duration:.3f}\n")
                    # Repeat last frame to avoid truncation
                    f.write(f"file '{state_pngs[-1]}'\nduration 0.001\n")

                cmd = [
                    FFMPEG, "-y",
                    "-f", "concat", "-safe", "0", "-i", str(concat_file),
                    "-vf",
                    "scale=1080:960:force_original_aspect_ratio=decrease,"
                    "pad=1080:960:(ow-iw)/2:(oh-ih)/2:black",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-t", str(target_duration_s),
                    output_path,
                ]

                logger.info("CodeWalkthroughGenerator: running ffmpeg")
                try:
                    await asyncio.to_thread(
                        subprocess.run, cmd, check=True, capture_output=True
                    )
                except subprocess.CalledProcessError as e:
                    raise BrollError(
                        f"ffmpeg failed: {e.stderr.decode()[:500]}"
                    ) from e

                logger.info(
                    "CodeWalkthroughGenerator: wrote clip to %s", output_path
                )
                return output_path

            except BrollError:
                raise
            except Exception as exc:
                raise BrollError(f"CodeWalkthroughGenerator unexpected error: {exc}") from exc
