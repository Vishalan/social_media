"""
B-roll type: split_screen (A/B composer)

Composes two existing b-roll generators side-by-side as a vertical 50/50
comparison clip. Each side is rendered at half-width (540 × 1920) via the
existing generators' ``width_override`` constructor param, then joined with
FFmpeg ``hstack`` to produce the final 1080 × 1920 output. A sky-blue
vertical divider (with a soft white outer glow) is drawn down the seam.

This generator is a *composer* — it delegates all rendering to the
sub-generators named in ``job.split_screen_pair``. Allowed sub-generator
types are restricted to the set that supports ``width_override``:
{browser_visit, image_montage, stats_card}.

``job.split_screen_pair`` shape::

    {
        "left":  {"generator_type": "browser_visit", "params": {...}},
        "right": {"generator_type": "stats_card",    "params": {...}},
    }

The ``params`` dict is forwarded to ``make_broll_generator`` as keyword
arguments (e.g. ``anthropic_client`` for the Claude-backed generators).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .base import BrollBase, BrollError
from video_edit.video_editor import FFMPEG

# Dual-import so the module works whether pytest / CLI runs from repo root
# (``python -m scripts.pipeline``) or from ``scripts/`` directly.
try:  # pragma: no cover — import-time branch
    from scripts.branding import SKY_BLUE
except ImportError:  # pragma: no cover — fallback when cwd is scripts/
    from branding import SKY_BLUE  # type: ignore[no-redef]

if TYPE_CHECKING:
    from pipeline import VideoJob

logger = logging.getLogger(__name__)

# Output dimensions (9:16 vertical, matches CommonCreed master output).
_HALF_W = 540
_FULL_W = _HALF_W * 2         # 1080
_FULL_H = 1920

# Divider geometry — centered on the seam between the two halves.
_DIV_W = 6                    # sky-blue line width (px)
_GLOW_W = 12                  # white outer glow width (px)
_GLOW_ALPHA = 0.3             # outer glow opacity

# Allowed sub-generator types for each side. The composer only delegates to
# generators that accept ``width_override`` in their constructor.
_ALLOWED_SIDE_TYPES = frozenset(
    {"browser_visit", "image_montage", "stats_card"}
)


def _hex_to_ffmpeg(hex_color: str) -> str:
    """Return FFmpeg's ``0xRRGGBB`` form of a ``#RRGGBB`` string.

    FFmpeg's ``drawbox=color=`` accepts either named colors (``white``) or
    hex in the form ``0xRRGGBB`` / ``#RRGGBB``. We normalise to ``0x`` form
    so there is zero ambiguity with shell quoting.
    """
    stripped = hex_color.lstrip("#")
    return f"0x{stripped.upper()}"


class SplitScreenGenerator(BrollBase):
    """Compose two existing b-roll generators side-by-side at half-width.

    Reads ``job.split_screen_pair`` (populated upstream by the topic-selection
    Haiku when the topic is a two-entity comparison). Instantiates each named
    sub-generator with ``width_override=540``, runs both concurrently via
    ``asyncio.gather``, and hstack-joins the resulting MP4s into a single
    ``1080 × 1920`` clip with a sky-blue center divider.

    Raises:
        BrollError: If ``job.split_screen_pair`` is missing, either side's
            ``generator_type`` is not in the allowed set, a sub-generator
            fails, or FFmpeg returns a non-zero exit code.
    """

    def __init__(self) -> None:
        # No external clients required at the composer level — every API
        # dependency is carried by the sub-generators via ``params``.
        pass

    async def generate(
        self,
        job: "VideoJob",
        target_duration_s: float,
        output_path: str,
    ) -> str:
        pair = getattr(job, "split_screen_pair", None)
        if not pair:
            raise BrollError("split_screen requires job.split_screen_pair")

        left_spec = pair.get("left")
        right_spec = pair.get("right")
        if not left_spec or not right_spec:
            raise BrollError(
                "split_screen_pair must contain both 'left' and 'right' specs; "
                f"got keys={sorted(pair.keys())}"
            )

        left_type = left_spec.get("generator_type")
        right_type = right_spec.get("generator_type")
        for side, t in (("left", left_type), ("right", right_type)):
            if t not in _ALLOWED_SIDE_TYPES:
                raise BrollError(
                    f"split_screen {side}.generator_type={t!r} not in "
                    f"allowed set {sorted(_ALLOWED_SIDE_TYPES)}"
                )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix="split_screen_"))
        try:
            left_path = tmp_dir / "left.mp4"
            right_path = tmp_dir / "right.mp4"

            logger.info(
                "SplitScreenGenerator: rendering left=%s right=%s (concurrent, "
                "width_override=%d, target=%.1fs)",
                left_type, right_type, _HALF_W, target_duration_s,
            )

            # Concurrent sub-generator invocation — each sub-generator writes
            # a 540×1920 MP4. Any BrollError propagates through gather().
            await asyncio.gather(
                self._render_side(job, left_spec, target_duration_s, str(left_path)),
                self._render_side(job, right_spec, target_duration_s, str(right_path)),
            )

            await self._compose_hstack(
                str(left_path), str(right_path), target_duration_s, output_path,
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        logger.info(
            "SplitScreenGenerator: %s saved (%dx%d, %.1fs)",
            output_path, _FULL_W, _FULL_H, target_duration_s,
        )
        return output_path

    # ── Private helpers ──────────────────────────────────────────────────

    async def _render_side(
        self,
        job: "VideoJob",
        spec: dict,
        target_duration_s: float,
        output_path: str,
    ) -> str:
        """Instantiate the named sub-generator at half-width and render.

        ``spec`` shape: ``{"generator_type": str, "params": dict}`` where
        ``params`` is split into factory kwargs vs job-override fields:

          * ``anthropic_client`` / ``pexels_api_key`` / ``bing_api_key``
            → forwarded to ``make_broll_generator`` as kwargs (plus the
            forced ``width_override=_HALF_W``).
          * ``topic`` / ``script`` → if present, override the outer job's
            fields so each side can narrate its own entity (A vs B).
        """
        # Import inside the method so tests can monkey-patch
        # ``broll_gen.split_screen.make_broll_generator``.
        try:
            from scripts.broll_gen.factory import make_broll_generator
        except ImportError:  # pragma: no cover — fallback for cwd=scripts/
            from broll_gen.factory import make_broll_generator  # type: ignore[no-redef]

        gen_type: str = spec["generator_type"]
        params: dict = dict(spec.get("params") or {})

        # Factory kwargs — only the keys each generator's __init__ accepts,
        # plus the forced width override.
        factory_keys = {
            "anthropic_client",
            "pexels_api_key",
            "bing_api_key",
        }
        factory_kwargs = {k: v for k, v in params.items() if k in factory_keys}
        factory_kwargs["width_override"] = _HALF_W

        # Optional per-side topic/script overrides — let the Haiku planner
        # narrate each side independently. Falls back to the outer job's
        # fields when not provided.
        side_topic = params.get("topic")
        side_script = params.get("script")
        side_job = _SideJobProxy(job, topic=side_topic, script=side_script)

        sub_gen = make_broll_generator(gen_type, **factory_kwargs)
        return await sub_gen.generate(
            job=side_job,
            target_duration_s=target_duration_s,
            output_path=output_path,
        )

    async def _compose_hstack(
        self,
        left_mp4: str,
        right_mp4: str,
        target_duration_s: float,
        output_path: str,
    ) -> None:
        """Join the two half-width clips with hstack and overlay the divider.

        The filter graph scales both inputs defensively (each sub-generator
        already renders at 540×1920, but an errant frame size would break
        hstack silently), then draws a soft white glow followed by the
        sky-blue line. Everything lives in a single ``-filter_complex`` pass
        so we only invoke FFmpeg once.
        """
        divider_color = _hex_to_ffmpeg(SKY_BLUE)  # e.g. 0x5C9BFF
        # Divider centered on the seam x=540. The sky-blue line is 6px wide
        # so x = 540 - 3 = 537. The glow is 12px wide centered at 540 so
        # x = 540 - 6 = 534.
        div_x = _FULL_W // 2 - _DIV_W // 2        # 537
        glow_x = _FULL_W // 2 - _GLOW_W // 2      # 534

        filter_complex = (
            f"[0:v]scale={_HALF_W}:{_FULL_H}[lv];"
            f"[1:v]scale={_HALF_W}:{_FULL_H}[rv];"
            f"[lv][rv]hstack[stacked];"
            # Soft outer glow (white, low alpha) drawn first so the crisp
            # sky-blue line sits on top.
            f"[stacked]drawbox=x={glow_x}:y=0:w={_GLOW_W}:h={_FULL_H}:"
            f"color=white@{_GLOW_ALPHA}:t=fill[glowed];"
            f"[glowed]drawbox=x={div_x}:y=0:w={_DIV_W}:h={_FULL_H}:"
            f"color={divider_color}@1.0:t=fill[vout]"
        )

        cmd = [
            FFMPEG, "-y",
            "-i", left_mp4,
            "-i", right_mp4,
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-t", str(target_duration_s),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-r", "30",
            output_path,
        ]

        logger.debug("SplitScreenGenerator ffmpeg: %s", " ".join(cmd))
        try:
            await asyncio.to_thread(
                subprocess.run, cmd, check=True, capture_output=True
            )
        except subprocess.CalledProcessError as exc:
            stderr_snippet = exc.stderr.decode(errors="replace")[:500]
            raise BrollError(
                f"ffmpeg hstack failed: {stderr_snippet}"
            ) from exc


class _SideJobProxy:
    """Lightweight VideoJob proxy used for split_screen sub-generator calls.

    Shadows ``topic`` / ``script`` with per-side overrides when provided,
    and forwards every other attribute to the outer ``VideoJob`` (so fields
    like ``extracted_article``, ``tweet_quote``, etc. stay accessible).
    """

    __slots__ = ("_outer", "_topic_override", "_script_override")

    def __init__(
        self,
        outer: "VideoJob",
        topic: dict | None = None,
        script: dict | None = None,
    ) -> None:
        self._outer = outer
        self._topic_override = topic
        self._script_override = script

    @property
    def topic(self) -> dict:
        if self._topic_override is not None:
            return self._topic_override
        return getattr(self._outer, "topic", {}) or {}

    @property
    def script(self) -> dict:
        if self._script_override is not None:
            return self._script_override
        return getattr(self._outer, "script", {}) or {}

    def __getattr__(self, name: str):
        # Delegate anything we don't explicitly shadow to the outer job.
        return getattr(self._outer, name)
