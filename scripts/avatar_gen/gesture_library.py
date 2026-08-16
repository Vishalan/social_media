"""Gesture-clip provider for the LatentSync avatar backend.

LatentSync lip-syncs over real footage, so every avatar segment needs a driving
clip of EXACTLY the segment's duration. A fixed set of pre-cut 5 s clips cannot
satisfy arbitrary segment lengths, so this module cuts on demand from the
source recording's usable windows.

Usable windows were established by scanning `IMG_1774_3.mp4` every 0.25 s with
InsightFace and keeping only samples that are face-present, near-frontal
(|yaw| < 20 deg), close-framed (face width > 200 px) and confident. Three
windows survived, 61.25 s in total — see
docs/spikes/2026-08-avatar-v3/gesture-clip-library.md.

Budget note: 61.25 s of usable footage is enough for roughly one 60 s short
without visible reuse. Ask for more than that and this module will reuse
material and say so in the log, rather than silently looping.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 480x854 @ 25fps, no audio — LatentSync's required input shape.
_TARGET_W, _TARGET_H, _TARGET_FPS = 480, 854, 25

# 9:16 crop from the 1920x1080 source, centred on the subject.
_CROP = "crop=608:1080:656:0"


@dataclass(frozen=True)
class Window:
    """A continuous stretch of usable frontal footage in the source file."""
    start: float
    end: float
    tag: str          # calm | moderate | animated — dominant gesture energy

    @property
    def duration(self) -> float:
        return self.end - self.start


# Verified 2026-08-16 against IMG_1774_3.mp4 (1920x1080, 30fps, 138.03s).
# Tags come from the measured motion of the 5 s clips cut from each window:
# window 1 averages calm/moderate, windows 2 and 3 are predominantly animated.
DEFAULT_WINDOWS: tuple[Window, ...] = (
    Window(0.00, 14.25, "moderate"),
    Window(72.00, 102.25, "animated"),
    Window(120.25, 137.00, "animated"),
)

DEFAULT_SOURCE = "/opt/commoncreed/assets/input_media/IMG_1774_3.mp4"


class GestureLibraryError(RuntimeError):
    """Raised when no usable footage can satisfy a request."""


class GestureLibrary:
    """Cuts LatentSync-ready driving clips of arbitrary duration."""

    def __init__(
        self,
        source: str = DEFAULT_SOURCE,
        windows: tuple[Window, ...] = DEFAULT_WINDOWS,
        output_dir: str = "output/gesture",
    ) -> None:
        self.source = Path(source)
        self.windows = windows
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Consumed seconds per window, so successive requests in one run walk
        # forward through the footage instead of all starting at the same frame.
        self._cursor: dict[int, float] = {i: 0.0 for i in range(len(windows))}

    @property
    def total_usable_s(self) -> float:
        return sum(w.duration for w in self.windows)

    def cut(
        self,
        duration: float,
        *,
        prefer_tag: Optional[str] = None,
        name: str = "gesture",
    ) -> str:
        """Return a path to a clip of exactly ``duration`` seconds.

        Args:
            duration: Required length. Must match the audio segment exactly —
                LatentSync pairs video and audio frame-for-frame.
            prefer_tag: 'calm' | 'moderate' | 'animated'. Falls back to any
                window long enough if the preference cannot be met.
            name: Basename for the produced file.

        Raises:
            GestureLibraryError: if no window is long enough.
        """
        if duration <= 0:
            raise GestureLibraryError(f"duration must be positive, got {duration}")
        if not self.source.exists():
            raise GestureLibraryError(f"source footage not found: {self.source}")

        idx, start = self._allocate(duration, prefer_tag)
        out = self.output_dir / f"{name}.mp4"

        cmd = [
            "ffmpeg", "-v", "error", "-y",
            "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
            "-i", str(self.source),
            "-vf", f"{_CROP},scale={_TARGET_W}:{_TARGET_H},fps={_TARGET_FPS}",
            "-an",                       # LatentSync supplies its own audio
            "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
            str(out),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise GestureLibraryError(f"ffmpeg failed: {r.stderr[-400:]}")

        logger.info(
            "Gesture clip %s: %.2fs from window %d @ %.2fs (tag=%s)",
            out.name, duration, idx + 1, start, self.windows[idx].tag,
        )
        return str(out)

    def _allocate(self, duration: float, prefer_tag: Optional[str]) -> tuple[int, float]:
        """Choose (window index, start offset) with enough unconsumed footage."""
        order = list(range(len(self.windows)))
        if prefer_tag:
            order.sort(key=lambda i: self.windows[i].tag != prefer_tag)

        # First pass: unconsumed footage only, so segments in one run differ.
        for i in order:
            w = self.windows[i]
            remaining = w.duration - self._cursor[i]
            if remaining >= duration:
                start = w.start + self._cursor[i]
                self._cursor[i] += duration
                return i, start

        # Second pass: reuse. Log it — silent looping is visible to viewers and
        # must never be a surprise.
        for i in order:
            if self.windows[i].duration >= duration:
                logger.warning(
                    "Gesture library exhausted (%.2fs usable); REUSING window %d "
                    "for a %.2fs segment — footage may read as looped",
                    self.total_usable_s, i + 1, duration,
                )
                self._cursor[i] = duration
                return i, self.windows[i].start

        raise GestureLibraryError(
            f"no usable window is {duration:.2f}s long "
            f"(longest is {max(w.duration for w in self.windows):.2f}s). "
            f"Film more footage or split the segment."
        )


def load_windows_from_manifest(path: str) -> tuple[Window, ...]:
    """Rebuild windows from a gesture_clips manifest.json, if one exists.

    Falls back to DEFAULT_WINDOWS when the manifest is missing or unreadable,
    so a deleted manifest degrades rather than breaking the pipeline.
    """
    p = Path(path)
    if not p.exists():
        return DEFAULT_WINDOWS
    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("gesture manifest unreadable (%s) — using defaults", exc)
        return DEFAULT_WINDOWS

    by_window: dict[int, list[dict]] = {}
    for clip in data.get("clips", []):
        by_window.setdefault(clip.get("window", 0), []).append(clip)
    if not by_window:
        return DEFAULT_WINDOWS

    windows = []
    for wid in sorted(by_window):
        clips = sorted(by_window[wid], key=lambda c: c["src_start"])
        tags = [c.get("tag", "moderate") for c in clips]
        dominant = max(set(tags), key=tags.count)
        windows.append(Window(clips[0]["src_start"], clips[-1]["src_end"], dominant))
    return tuple(windows)
