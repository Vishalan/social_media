"""Zoom-bell pass — brief zoom-in/zoom-out synchronized to keyword punches.

Plan Key Decision #10 calls out zoom as part of the engagement-v2
polish: a 200 ms quadratic bell-curve zoom (~+15% peak) lands on each
keyword-punch timestamp. Over a 60-90 s short with ~6-8 punches this
produces subtle, deliberate emphasis beats rather than constant motion.

Mirrors CommonCreed's ``_build_zoom_expression`` in
``scripts/video_edit/video_editor.py`` — same sin-bell shape, same
intensity-to-delta mapping — but consumes Vesper's ``KeywordPunch``
type (``t_seconds`` + ``reason``, no ``t_start``/``intensity`` fields).

FFmpeg graph shape (N punches):

    [0:v]
      scale=iw*Z(t):ih*Z(t),
      crop=iw/Z(t):ih/Z(t):
           (iw/Z(t)-iw)/-2*(-1):(ih/Z(t)-ih)/-2*(-1)
    [vout]

  Z(t) = 1.0 + Σᵢ deltaᵢ · sin(π·(t-t0ᵢ)/durᵢ)·between(t, t0ᵢ, t0ᵢ+durᵢ)

We combine scale + crop so the zoom stays centered (scale grows the
frame, crop pulls it back to 1080x1920). Audio is stream-copied.

Per-reason intensity (maps the detector's ``reason`` → zoom amplitude):

  * capitalized      → 0.15 (proper-noun hit, medium emphasis)
  * long_word        → 0.10 (subtle on content words)
  * end_of_sentence  → 0.12 (beat-closing lift)

When the punches list is empty, the burner no-ops (returns False) —
the FFmpeg pass would just stream-copy, so we skip it entirely.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

logger = logging.getLogger(__name__)


# Per-reason peak zoom amplitudes (matching the detector's `reason`
# strings). Lower than CommonCreed's defaults because Vesper's
# register is quieter — +15% reads louder on black-background horror
# than on CommonCreed's busier news visuals.
_REASON_AMPLITUDE = {
    "capitalized": 0.15,
    "long_word": 0.10,
    "end_of_sentence": 0.12,
}
# Fallback for forwards-compat if new reasons are added.
_DEFAULT_AMPLITUDE = 0.12

# Bell duration in seconds. 0.2 s is the CommonCreed default — wide
# enough to read as a zoom rather than a frame-step, narrow enough
# not to smear the underlying visual.
_PUNCH_DURATION_S = 0.2


class ZoomBellError(RuntimeError):
    """Raised when the FFmpeg zoom pass exits non-zero AND was
    actually attempted (punches non-empty)."""


def build_zoom_expression(
    punches: Sequence[Any],
    *,
    punch_duration_s: float = _PUNCH_DURATION_S,
) -> str:
    """Build the ``Z(t)`` FFmpeg expression for a list of punches.

    Returns the literal ``"1.0"`` when ``punches`` is empty so callers
    can safely splice the expression into a filter graph without
    checking punch count first.
    """
    if not punches:
        return "1.0"

    parts: List[str] = ["1.0"]
    for p in punches:
        t0 = float(getattr(p, "t_seconds", 0.0))
        reason = getattr(p, "reason", None) or ""
        delta = _REASON_AMPLITUDE.get(reason, _DEFAULT_AMPLITUDE)
        t1 = t0 + punch_duration_s
        # sin bell: nonzero only on [t0, t1], peak at midpoint.
        parts.append(
            f"{delta}*if(between(t\\,{t0:.3f}\\,{t1:.3f})\\,"
            f"sin(PI*(t-{t0:.3f})/{punch_duration_s:.3f})\\,0)"
        )
    return "+".join(parts)


@dataclass
class ZoomBellBurner:
    """Applies sin-bell zooms onto a staging MP4 via FFmpeg.

    Injectable runner — tests substitute a stub that captures the cmd
    without spawning a real process.
    """

    runner: Optional[Callable[..., Any]] = None
    punch_duration_s: float = _PUNCH_DURATION_S

    def apply(
        self,
        *,
        input_mp4: str,
        output_mp4: str,
        punches: Sequence[Any],
    ) -> bool:
        """Apply zoom bells onto ``input_mp4``, writing ``output_mp4``.

        Returns True when a render happened; False when ``punches`` is
        empty (caller treats as a no-op and keeps the input as the
        effective output).
        """
        if not punches:
            return False

        z_expr = build_zoom_expression(
            punches, punch_duration_s=self.punch_duration_s,
        )
        # Scale frame up by Z, then crop back to the original dims.
        # The `crop` centers on the scaled frame so the zoom reads as
        # centered rather than corner-pinned.
        filter_chain = (
            f"scale=iw*({z_expr}):ih*({z_expr}),"
            f"crop=iw/({z_expr}):ih/({z_expr})"
        )
        cmd = [
            "ffmpeg", "-y", "-i", input_mp4,
            "-vf", filter_chain,
            "-c:a", "copy",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            output_mp4,
        ]

        runner = self.runner or subprocess.run
        result = runner(cmd, capture_output=True)

        rc = getattr(result, "returncode", 0)
        if rc != 0:
            stderr = getattr(result, "stderr", b"")
            msg = stderr.decode("utf-8", errors="replace") if isinstance(
                stderr, (bytes, bytearray)
            ) else str(stderr)
            raise ZoomBellError(
                f"FFmpeg zoom pass failed (rc={rc}): {msg[:500]}"
            )

        logger.info(
            "ZoomBellBurner: applied %d zoom bell(s) → %s",
            len(punches), output_mp4,
        )
        return True


__all__ = [
    "ZoomBellBurner",
    "ZoomBellError",
    "build_zoom_expression",
]
