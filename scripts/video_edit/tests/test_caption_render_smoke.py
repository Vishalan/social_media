"""Smoke test: ffmpeg can burn an ASS karaoke line onto a blank video.

This is a container/CI assertion for the sidecar image — it proves that the
ffmpeg binary has libass support compiled in so the downstream ASS karaoke
caption renderer (Unit A2) can produce frames without silently falling back
to a no-op filter.

Skipped on macOS dev machines. The sidecar Dockerfile also asserts libass at
build time (``ffmpeg -filters | grep ass``), so this pytest run is a
second-line check once the container is running in CI/production.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


# Minimal valid ASS file with one \k karaoke line. PlayRes and style are
# intentionally tight — we only need libass to accept the file and emit
# rendered frames, not to look good. The font name matches Unit 0.1's
# branding.py ("Inter") so libass + fontconfig exercise the same resolution
# path the production caption renderer will use.
_ASS_CONTENT = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Inter,72,&H00FFFFFF,&H00000000,1,2,0,5,20,20,20,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{\\k50}hello {\\k50}world
"""


def _ffmpeg_bin() -> str:
    """Resolve the ffmpeg binary on PATH.

    Returns:
        Absolute path to the ffmpeg binary.
    """
    found = shutil.which("ffmpeg")
    return found or "ffmpeg"


@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="container/Linux assertion; libass availability on macOS Homebrew ffmpeg is not guaranteed. Runs in sidecar CI.",
)
def test_libass_burns_karaoke_line(tmp_path: Path) -> None:
    """ffmpeg must burn a one-second ASS karaoke line onto a blank video.

    Produces a 1s black 1080x1920 video, then re-encodes it through the
    ``ass`` filter with a minimal karaoke dialogue. Asserts ffmpeg exits 0
    and the output MP4 exists + is non-empty. A broken/libass-less ffmpeg
    will exit non-zero with "No such filter: 'ass'" (or equivalent), so
    exit-code==0 is a sufficient smoke signal.
    """
    ffmpeg = _ffmpeg_bin()

    ass_path = tmp_path / "caption.ass"
    ass_path.write_text(_ASS_CONTENT, encoding="utf-8")

    blank_path = tmp_path / "blank.mp4"
    blank_cmd = [
        ffmpeg,
        "-y",
        "-f", "lavfi",
        "-i", "color=c=black:s=1080x1920:d=1",
        "-c:v", "libx264",
        "-t", "1",
        "-pix_fmt", "yuv420p",
        str(blank_path),
    ]
    blank_result = subprocess.run(
        blank_cmd,
        check=False,
        capture_output=True,
    )
    assert blank_result.returncode == 0, (
        f"ffmpeg failed to produce blank video: "
        f"{blank_result.stderr.decode(errors='replace')[:500]}"
    )
    assert blank_path.exists() and blank_path.stat().st_size > 0, (
        "blank video was not written"
    )

    output_path = tmp_path / "captioned.mp4"
    burn_cmd = [
        ffmpeg,
        "-y",
        "-i", str(blank_path),
        "-vf", f"ass={ass_path}",
        "-c:a", "copy",
        str(output_path),
    ]
    burn_result = subprocess.run(
        burn_cmd,
        check=False,
        capture_output=True,
    )
    assert burn_result.returncode == 0, (
        f"ffmpeg ass filter failed (libass missing?): "
        f"{burn_result.stderr.decode(errors='replace')[:500]}"
    )
    assert output_path.exists() and output_path.stat().st_size > 0, (
        "captioned output MP4 was not written or is empty"
    )
