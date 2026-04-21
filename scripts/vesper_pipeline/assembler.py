"""Vesper video assembler — MVP visual-track + audio mix.

Scope note: this is the v1 assembler. It implements the bare-minimum
shape needed to produce a playable 9:16 short:

  1. Walk the Timeline beat-by-beat. For each beat, read the matching
     visual asset from ``job``:
       * STILL_KENBURNS → apply a Ken Burns pan/zoom on the still
       * STILL_PARALLAX → play the pre-animated parallax MP4
       * HERO_I2V       → play the I2V MP4
  2. Concatenate at 1080x1920.
  3. Mix the voice track in; fade-in/out 300 ms each end.
  4. Write the output MP4.

Deferred to follow-up adapters (each is a feature flag on the
config; turned on when the upstream piece lands):
  * Word-level ASS captions — needs faster-whisper wiring from
    engagement-v2 (``scripts/video_edit/whisper_timestamps.py``).
  * SFX mixing — needs ``scripts.audio.sfx.mix_sfx_into_audio`` +
    keyword-punch timestamps from the timeline planner.
  * Overlay pack (grain/dust/flicker/fog) — FFmpeg filter chain;
    single-pass after the main render.
  * C2PA re-sign — one of Unit 9's POC outputs decides if we need
    the re-sign stage here or if stream-copy through ``ffmpeg -c copy``
    preserves credentials through MoviePy.

Dependency injection: the MoviePy clip constructors are imported
lazily so tests can monkey-patch them without installing MoviePy.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Protocol

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from still_gen._types import BeatMode  # noqa: E402

from ._types import VesperJob  # noqa: E402

logger = logging.getLogger(__name__)


OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
FADE_S = 0.3
DEFAULT_FPS = 30
# Ken Burns on a still — simple ~3% push over the beat duration. The
# existing VideoEditor has richer Ken Burns modes (push_in / pull_back /
# slow_pan_*) we'll port across in a follow-up; MVP uses one direction.
KEN_BURNS_ZOOM = 1.03


class AssemblyError(RuntimeError):
    """Raised on assembly failure — missing asset, clip-load error,
    unsupported beat shape. Message includes beat index."""


class _ClipFactory(Protocol):
    """Minimal MoviePy surface we depend on. Production wires the real
    ``moviepy`` module via :func:`_load_real_moviepy`; tests pass a
    fake that returns stubs the assembler composes in order."""

    def ImageClip(self, path: str) -> Any: ...
    def VideoFileClip(self, path: str) -> Any: ...
    def AudioFileClip(self, path: str) -> Any: ...
    def concatenate_videoclips(self, clips: List[Any]) -> Any: ...


def _load_real_moviepy() -> _ClipFactory:
    """Import moviepy lazily + bundle the names the assembler uses."""
    from moviepy import (  # type: ignore
        AudioFileClip,
        ImageClip,
        VideoFileClip,
        concatenate_videoclips,
    )

    class _Bundle:
        ImageClip = staticmethod(ImageClip)
        VideoFileClip = staticmethod(VideoFileClip)
        AudioFileClip = staticmethod(AudioFileClip)
        concatenate_videoclips = staticmethod(concatenate_videoclips)

    return _Bundle()  # type: ignore[return-value]


# ─── Assembler ─────────────────────────────────────────────────────────────


@dataclass
class VesperAssembler:
    """Composes beats + voice into a final MP4.

    ``clip_factory`` is injectable so tests exercise the composition
    logic without MoviePy installed. When ``None``, moviepy is imported
    at call time.
    """

    clip_factory: Optional[_ClipFactory] = None
    fps: int = DEFAULT_FPS
    output_width: int = OUTPUT_WIDTH
    output_height: int = OUTPUT_HEIGHT
    # Optional caption style. When provided + ``job.caption_segments`` is
    # populated, a second FFmpeg pass burns ASS subtitles onto the MP4.
    # When ``None``, the assembler writes a raw video with no captions.
    caption_style: Optional[Any] = None
    # Injectable for tests: defaults to subprocess.run.
    ass_burn_runner: Optional[Any] = None

    def assemble(self, *, job: VesperJob, output_path: str) -> str:
        """Produce a 9:16 MP4 at ``output_path``. Returns the path.

        Raises :class:`AssemblyError` on any missing asset or clip
        failure. On success, leaves ``job.video_path`` for the caller
        to set (the pipeline wrapper does this).
        """
        if job.timeline is None:
            raise AssemblyError(
                "VesperAssembler requires a timeline on the job — "
                "pipeline must run plan_timeline before assembly."
            )
        if not job.voice_path:
            raise AssemblyError(
                "VesperAssembler requires job.voice_path — "
                "pipeline must run voice_generate before assembly."
            )

        factory = self.clip_factory or _load_real_moviepy()

        clips: List[Any] = []
        parallax_idx = 0
        i2v_idx = 0

        beats = list(job.timeline.beats)
        for idx, beat in enumerate(beats):
            try:
                clip = self._clip_for_beat(
                    factory=factory,
                    beat=beat,
                    idx=idx,
                    still_paths=job.still_paths,
                    parallax_paths=job.parallax_paths,
                    i2v_paths=job.i2v_paths,
                    parallax_cursor=parallax_idx,
                    i2v_cursor=i2v_idx,
                )
            except AssemblyError:
                raise
            except Exception as exc:
                raise AssemblyError(
                    f"beat {idx} ({beat.mode.value}): {exc}"
                ) from exc

            # Advance the cursor that the beat consumed.
            if beat.mode == BeatMode.STILL_PARALLAX:
                parallax_idx += 1
            elif beat.mode == BeatMode.HERO_I2V:
                i2v_idx += 1

            clips.append(clip)

        video = factory.concatenate_videoclips(clips)
        try:
            audio = factory.AudioFileClip(job.voice_path)
        except Exception as exc:
            raise AssemblyError(f"could not load audio: {exc}") from exc

        final = _apply_audio(video, audio)

        # If captions are active, write to a staging path first, then
        # burn ASS in a second FFmpeg pass. The direct-to-output shortcut
        # is preserved for tests / caption-disabled runs.
        caption_segments = getattr(job, "caption_segments", None)
        if self.caption_style is not None and caption_segments:
            staging_path = output_path + ".nocap.mp4"
            _write_file(final, staging_path, fps=self.fps)
            self._burn_captions(staging_path, caption_segments, output_path)
            try:
                Path(staging_path).unlink(missing_ok=True)
            except OSError:
                pass
        else:
            _write_file(final, output_path, fps=self.fps)

        logger.info(
            "VesperAssembler: wrote %s (%d beats, %.1fs, captions=%s)",
            output_path, len(clips),
            sum(b.duration_s for b in beats),
            "yes" if (self.caption_style and caption_segments) else "no",
        )
        return output_path

    def _burn_captions(
        self,
        staging_path: str,
        caption_segments: list,
        output_path: str,
    ) -> None:
        """Run ffmpeg with `-vf ass=...` to burn captions onto staging
        MP4 and write the final output. Raises AssemblyError on non-zero
        FFmpeg return."""
        import subprocess
        import tempfile

        from .captions import build_ass_captions

        ass_text = build_ass_captions(
            list(caption_segments),
            self.caption_style,  # type: ignore[arg-type]
            output_width=self.output_width,
            output_height=self.output_height,
        )
        with tempfile.NamedTemporaryFile(
            suffix=".ass", delete=False, mode="w", encoding="utf-8",
        ) as ass_tmp:
            ass_tmp.write(ass_text)
            ass_path = ass_tmp.name

        runner = self.ass_burn_runner or subprocess.run
        cmd = [
            "ffmpeg", "-y", "-i", staging_path,
            "-vf", f"ass={ass_path}",
            "-c:a", "copy", output_path,
        ]
        try:
            result = runner(cmd, capture_output=True)
        finally:
            try:
                Path(ass_path).unlink(missing_ok=True)
            except OSError:
                pass

        rc = getattr(result, "returncode", 0)
        if rc != 0:
            stderr = getattr(result, "stderr", b"")
            msg = stderr.decode("utf-8", errors="replace") if isinstance(
                stderr, (bytes, bytearray)
            ) else str(stderr)
            raise AssemblyError(
                f"FFmpeg ASS burn failed (rc={rc}): {msg[:500]}"
            )

    # ─── Per-beat clip selection ───────────────────────────────────────

    def _clip_for_beat(
        self,
        *,
        factory: _ClipFactory,
        beat: Any,
        idx: int,
        still_paths: List[str],
        parallax_paths: List[str],
        i2v_paths: List[str],
        parallax_cursor: int,
        i2v_cursor: int,
    ) -> Any:
        if beat.mode == BeatMode.STILL_KENBURNS:
            path = still_paths[idx] if idx < len(still_paths) else ""
            if not path:
                raise AssemblyError(
                    f"beat {idx}: missing still path for KEN_BURNS mode"
                )
            clip = factory.ImageClip(path)
            clip = _apply_duration(clip, beat.duration_s)
            clip = _apply_ken_burns(clip, beat.motion_hint)
            return _resize_to_frame(clip, self.output_width, self.output_height)
        if beat.mode == BeatMode.STILL_PARALLAX:
            if parallax_cursor >= len(parallax_paths):
                raise AssemblyError(
                    f"beat {idx}: parallax cursor {parallax_cursor} "
                    f"exceeds available parallax clips ({len(parallax_paths)})"
                )
            path = parallax_paths[parallax_cursor]
            clip = factory.VideoFileClip(path)
            return _resize_to_frame(clip, self.output_width, self.output_height)
        if beat.mode == BeatMode.HERO_I2V:
            if i2v_cursor >= len(i2v_paths):
                raise AssemblyError(
                    f"beat {idx}: i2v cursor {i2v_cursor} "
                    f"exceeds available i2v clips ({len(i2v_paths)})"
                )
            path = i2v_paths[i2v_cursor]
            clip = factory.VideoFileClip(path)
            return _resize_to_frame(clip, self.output_width, self.output_height)
        raise AssemblyError(f"beat {idx}: unknown mode {beat.mode!r}")


# ─── MoviePy helpers ───────────────────────────────────────────────────────
#
# These are standalone functions so tests can verify they're called
# without mocking every method on a fake clip. The real MoviePy clips
# implement all of these; test fakes only need to track *that* they
# were invoked.


def _apply_duration(clip: Any, duration_s: float) -> Any:
    if hasattr(clip, "with_duration"):
        return clip.with_duration(duration_s)
    if hasattr(clip, "set_duration"):
        return clip.set_duration(duration_s)
    return clip


def _apply_ken_burns(clip: Any, motion_hint: str) -> Any:
    """Apply a simple zoom keyed off the motion_hint direction.

    Real MoviePy would use ``ffmpeg -vf zoompan`` for pixel-perfect
    output; MVP relies on a .resize() lerp which looks close enough
    for first-run QA."""
    if not hasattr(clip, "resized"):
        return clip
    start_zoom = 1.0 if motion_hint == "push_in" else KEN_BURNS_ZOOM
    end_zoom = KEN_BURNS_ZOOM if motion_hint == "push_in" else 1.0
    duration = getattr(clip, "duration", 1.0) or 1.0

    def _zoom(t: float) -> float:
        frac = min(1.0, t / duration)
        return start_zoom + (end_zoom - start_zoom) * frac

    return clip.resized(lambda t: _zoom(t))


def _resize_to_frame(clip: Any, w: int, h: int) -> Any:
    """Force a canonical 9:16 frame. Real clips may already be
    1080x1920; this is idempotent."""
    if hasattr(clip, "resized"):
        return clip.resized(new_size=(w, h))
    if hasattr(clip, "resize"):
        return clip.resize(newsize=(w, h))
    return clip


def _apply_audio(video: Any, audio: Any) -> Any:
    if hasattr(video, "with_audio"):
        return video.with_audio(audio)
    if hasattr(video, "set_audio"):
        return video.set_audio(audio)
    return video


def _write_file(clip: Any, path: str, *, fps: int) -> None:
    if hasattr(clip, "write_videofile"):
        clip.write_videofile(
            path,
            fps=fps,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=f"{path}.tmp-audio.m4a",
            remove_temp=True,
        )


__all__ = [
    "AssemblyError",
    "VesperAssembler",
]
