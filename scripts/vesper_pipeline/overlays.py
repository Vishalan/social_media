"""Overlay pack — FFmpeg filter chain layering grain/dust/flicker/fog
onto the assembled MP4.

Plan Key Decision #10 calls the overlay pack non-optional for every
short — it's the aged-film-stock texture that separates Vesper
visuals from the template-AI look. The four layers map onto:

  * **grain** — fine film-stock noise. Constant across the frame.
    Opacity ~0.12 baseline.
  * **dust** — occasional dust particles / scratches. Opacity ~0.30;
    the higher alpha is fine because dust is sparse on screen.
  * **flicker** — projector-style brightness pulse. Runs at low opacity
    (~0.08) so the pulse reads as subconscious atmosphere rather than
    a hard flash.
  * **fog** — low ground-level fog on establishing shots. Opacity ~0.18.

Missing pack assets are a pre-launch sourcing task (see
``docs/runbooks/vesper/vesper-launch-runbook.md`` — T-3 days). If a
specific layer's .mp4 isn't present, the adapter skips that layer
with a WARNING and continues. If all four are missing the adapter
no-ops (returns False) and the assembler ships the raw video.

FFmpeg graph shape (all layers present):

    [0:v]                                             [base]
    [1:v] format=yuv420p, colorchannelmixer=aa=0.12   [g]
    [2:v] format=yuv420p, colorchannelmixer=aa=0.30   [d]
    [3:v] format=yuv420p, colorchannelmixer=aa=0.08   [f]
    [4:v] format=yuv420p, colorchannelmixer=aa=0.18   [fog]

    [base][g]   overlay=shortest=1:format=auto [v1]
    [v1][d]     overlay=shortest=1             [v2]
    [v2][f]     overlay=shortest=1             [v3]
    [v3][fog]   overlay=shortest=1             [v]

Audio is stream-copied (`-c:a copy`).
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# Canonical pack layer order — FFmpeg chain assembled in this sequence.
# Order matters: grain is the most frequent background texture and goes
# first; fog is the most opaque and goes last so it reads above grain.
_LAYER_ORDER = ("grain", "dust", "flicker", "fog")


# Default opacities per plan K.D. #10 — tuned to be visible on close
# inspection without stomping on the underlying visual. Callers can
# override via :class:`OverlayPack.opacity_overrides`.
_DEFAULT_OPACITY: Dict[str, float] = {
    "grain": 0.12,
    "dust": 0.30,
    "flicker": 0.08,
    "fog": 0.18,
}


@dataclass(frozen=True)
class OverlayPack:
    """Pack of overlay .mp4 paths + per-layer opacity.

    Callers point ``base_dir`` at ``assets/vesper/overlays/`` (or the
    equivalent per-channel path) and the adapter resolves each layer
    name to ``<base_dir>/<name>.mp4``. Missing files are skipped at
    render time with a WARNING — the pre-launch runbook catches the
    gap rather than the pipeline crashing in production.
    """

    base_dir: Path
    opacity_overrides: Dict[str, float] = field(default_factory=dict)

    def opacity(self, layer: str) -> float:
        return self.opacity_overrides.get(layer, _DEFAULT_OPACITY[layer])

    def layer_path(self, layer: str) -> Path:
        return self.base_dir / f"{layer}.mp4"

    def available_layers(self) -> List[str]:
        """Return layers whose .mp4 is present on disk, in canonical
        render order. Missing layers are dropped silently here; the
        caller logs the WARNING once per render."""
        return [
            name for name in _LAYER_ORDER
            if self.layer_path(name).exists()
        ]


class OverlayError(RuntimeError):
    """Raised when the FFmpeg overlay pass exits non-zero AND the pass
    was actually attempted (≥1 layer available). All-layers-missing is
    a silent no-op, not an error."""


@dataclass
class OverlayBurner:
    """Applies an :class:`OverlayPack` to a staging MP4 via FFmpeg.

    Callable contract for the assembler: :meth:`apply` takes an input
    MP4 + output MP4 + pack, returns True if a burn happened (output
    MP4 written), False if the pack had zero available layers (input
    left as-is — assembler copies or keeps staging).

    Injectable ``runner`` defaults to :func:`subprocess.run` so tests
    substitute a stub that asserts the FFmpeg command shape without
    spawning a real process.
    """

    runner: Optional[Callable[..., Any]] = None

    def apply(
        self,
        *,
        input_mp4: str,
        output_mp4: str,
        pack: OverlayPack,
    ) -> bool:
        """Apply overlays onto ``input_mp4``, writing ``output_mp4``.

        Returns True when a render happened; False when the pack had
        no available layers (caller treats as a no-op and keeps the
        input as the effective output).
        """
        layers = pack.available_layers()
        if not layers:
            logger.warning(
                "OverlayBurner: pack at %s has no available .mp4 layers "
                "(%s). Skipping overlay pass. See "
                "docs/runbooks/vesper/vesper-launch-runbook.md T-3.",
                pack.base_dir, ", ".join(_LAYER_ORDER),
            )
            return False

        missing = [name for name in _LAYER_ORDER if name not in layers]
        if missing:
            logger.warning(
                "OverlayBurner: %d of 4 overlay layer(s) missing (%s); "
                "applying available %s. See launch runbook T-3.",
                len(missing), ", ".join(missing), ", ".join(layers),
            )

        cmd = self._build_ffmpeg_cmd(
            input_mp4=input_mp4, output_mp4=output_mp4,
            layers=layers, pack=pack,
        )

        runner = self.runner or subprocess.run
        result = runner(cmd, capture_output=True)

        rc = getattr(result, "returncode", 0)
        if rc != 0:
            stderr = getattr(result, "stderr", b"")
            msg = stderr.decode("utf-8", errors="replace") if isinstance(
                stderr, (bytes, bytearray)
            ) else str(stderr)
            raise OverlayError(
                f"FFmpeg overlay pass failed (rc={rc}): {msg[:500]}"
            )

        logger.info(
            "OverlayBurner: applied %d layer(s) [%s] → %s",
            len(layers), ", ".join(layers), output_mp4,
        )
        return True

    # ─── Internal: FFmpeg graph construction ───────────────────────────

    def _build_ffmpeg_cmd(
        self,
        *,
        input_mp4: str,
        output_mp4: str,
        layers: List[str],
        pack: OverlayPack,
    ) -> List[str]:
        """Compose the FFmpeg command. Pulled out as a method so tests
        can assert the graph without running FFmpeg."""
        cmd: List[str] = ["ffmpeg", "-y", "-i", input_mp4]
        for name in layers:
            cmd.extend(["-i", str(pack.layer_path(name))])

        # filter_complex graph:
        #   1. Set alpha on each overlay input via
        #      format=yuva420p,colorchannelmixer=aa=<opacity>.
        #   2. Chain overlay nodes so each layer sits on top of the
        #      previous composite.
        filter_parts: List[str] = []
        # Pre-process each overlay input (input index 1..N).
        for i, name in enumerate(layers, start=1):
            opa = pack.opacity(name)
            filter_parts.append(
                f"[{i}:v]format=yuva420p,colorchannelmixer=aa={opa:.3f}[ov{i}]"
            )
        # Chain overlays onto the base.
        prev_label = "0:v"
        for i, _name in enumerate(layers, start=1):
            out_label = f"v{i}" if i < len(layers) else "vout"
            filter_parts.append(
                f"[{prev_label}][ov{i}]overlay=shortest=1:format=auto[{out_label}]"
            )
            prev_label = out_label

        cmd.extend([
            "-filter_complex", ";".join(filter_parts),
            "-map", "[vout]",
            "-map", "0:a?",   # audio from base input, if present
            "-c:a", "copy",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "18",
            output_mp4,
        ])
        return cmd


def build_overlay_pack(channel_id: str, *, repo_root: Optional[Path] = None) -> OverlayPack:
    """Convenience: return an :class:`OverlayPack` rooted at
    ``<repo_root>/assets/<channel_id>/overlays/``. Used by ``__main__``
    wiring and the launch runbook's verification commands."""
    root = repo_root or Path(__file__).resolve().parent.parent.parent
    return OverlayPack(
        base_dir=root / "assets" / channel_id / "overlays",
    )


__all__ = [
    "OverlayBurner",
    "OverlayError",
    "OverlayPack",
    "build_overlay_pack",
]
