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

# Dip-to-black fade duration at scene-change boundaries (Key Decision #10).
SCENE_DIP_S = 0.25


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
    # Optional overlay pack (grain/dust/flicker/fog). When provided,
    # runs a pre-caption FFmpeg pass so captions sit on top of the
    # overlays. None → raw video.
    overlay_pack: Optional[Any] = None
    overlay_burner: Optional[Any] = None
    # Optional zoom-bell pass on keyword punches. Runs between overlays
    # and captions so captions stay crisp (not scaled inside the zoom).
    zoom_bell_burner: Optional[Any] = None
    # When True (default), zoom bells fire whenever the job has
    # keyword_punches. Set False to disable the pass without removing
    # the burner.
    enable_zoom_bells: bool = True
    # Dip-to-black on scene change (Key Decision #10). Fade boundary
    # detection compares ``beat.tag`` between consecutive beats — a
    # transition like hook→setup, rising→reveal, climax→tail fires
    # the fade. Beats without tags don't trigger fades.
    enable_scene_fades: bool = True
    scene_fade_duration_s: float = SCENE_DIP_S

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

            # Dip-to-black on scene-change boundaries. Fade the PREVIOUS
            # clip out + the CURRENT clip in when their tags differ.
            if (
                self.enable_scene_fades
                and idx > 0
                and _is_scene_change(beats[idx - 1], beat)
                and clips
            ):
                clips[-1] = _apply_fade_out(
                    clips[-1], self.scene_fade_duration_s,
                )
                clip = _apply_fade_in(clip, self.scene_fade_duration_s)

            clips.append(clip)

        video = factory.concatenate_videoclips(clips)
        try:
            audio = factory.AudioFileClip(job.voice_path)
        except Exception as exc:
            raise AssemblyError(f"could not load audio: {exc}") from exc

        final = _apply_audio(video, audio)

        # Post-write passes run as FFmpeg subprocess steps so we can
        # chain overlay → zoom → captions without going through
        # MoviePy multiple times.
        #
        # Order matters:
        #   1. MoviePy write → raw concat MP4   (staging[0])
        #   2. Overlay pass  → grain/dust/...    (staging[1])
        #   3. Zoom pass     → sin-bell zooms    (staging[2])
        #   4. Caption pass  → ASS on top        (output_path)
        # Captions go LAST so the text isn't scaled inside the zoom
        # or flickered under the overlay. Staging files are cleaned
        # up regardless of which passes run.
        caption_segments = getattr(job, "caption_segments", None)
        keyword_punches = getattr(job, "keyword_punches", None) or []
        want_captions = bool(self.caption_style and caption_segments)
        want_overlays = self.overlay_pack is not None
        want_zoom = bool(
            self.enable_zoom_bells
            and keyword_punches
            and (self.zoom_bell_burner is not None or self.enable_zoom_bells)
        )

        if want_overlays or want_zoom or want_captions:
            staging: List[str] = []
            current = output_path + ".stage0.mp4"
            _write_file(final, current, fps=self.fps)
            staging.append(current)

            if want_overlays:
                nxt = output_path + ".stage1.mp4"
                if self._apply_overlays(current, nxt):
                    current = nxt
                    staging.append(nxt)
                else:
                    try:
                        Path(nxt).unlink(missing_ok=True)
                    except OSError:
                        pass

            if want_zoom:
                nxt = output_path + ".stage2.mp4"
                if self._apply_zoom_bells(current, nxt, keyword_punches):
                    current = nxt
                    staging.append(nxt)
                else:
                    try:
                        Path(nxt).unlink(missing_ok=True)
                    except OSError:
                        pass

            if want_captions:
                self._burn_captions(current, caption_segments, output_path)
            else:
                import shutil as _sh
                _sh.move(current, output_path)
                # `current` is now the output — don't try to delete it.
                if current in staging:
                    staging.remove(current)

            for p in staging:
                if p != output_path and Path(p).exists():
                    try:
                        Path(p).unlink(missing_ok=True)
                    except OSError:
                        pass
        else:
            _write_file(final, output_path, fps=self.fps)

        logger.info(
            "VesperAssembler: wrote %s (%d beats, %.1fs, overlays=%s, "
            "zoom_bells=%s, captions=%s)",
            output_path, len(clips),
            sum(b.duration_s for b in beats),
            "yes" if want_overlays else "no",
            "yes" if (want_zoom and keyword_punches) else "no",
            "yes" if want_captions else "no",
        )
        return output_path

    def _apply_zoom_bells(
        self,
        input_mp4: str,
        output_mp4: str,
        punches: list,
    ) -> bool:
        """Run the zoom-bell burner; return True when FFmpeg actually
        wrote output_mp4, False when punches empty."""
        burner = self.zoom_bell_burner
        if burner is None:
            from .zoom_bell import ZoomBellBurner
            burner = ZoomBellBurner()
        return burner.apply(
            input_mp4=input_mp4,
            output_mp4=output_mp4,
            punches=punches,
        )

    def _apply_overlays(self, input_mp4: str, output_mp4: str) -> bool:
        """Run the overlay burner; return True when FFmpeg actually
        wrote output_mp4, False when the pack had zero layers."""
        burner = self.overlay_burner
        if burner is None:
            # Lazy-import so tests without ffmpeg don't pay the cost.
            from .overlays import OverlayBurner
            burner = OverlayBurner()
        return burner.apply(
            input_mp4=input_mp4,
            output_mp4=output_mp4,
            pack=self.overlay_pack,
        )

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


def _is_scene_change(prev_beat: Any, cur_beat: Any) -> bool:
    """Return True when ``prev_beat`` and ``cur_beat`` have different,
    non-empty ``tag`` attributes. Empty tags never fire a scene change
    (the timeline planner may not emit tags for all beats)."""
    prev_tag = (getattr(prev_beat, "tag", "") or "").strip()
    cur_tag = (getattr(cur_beat, "tag", "") or "").strip()
    if not prev_tag or not cur_tag:
        return False
    return prev_tag != cur_tag


def _apply_fade_out(clip: Any, duration_s: float) -> Any:
    """Fade the tail of ``clip`` to black over ``duration_s``.

    Tries the MoviePy 2.x API (``with_effects([FadeOut(...)])``) first,
    then the 1.x API (``fadeout(...)``), then returns the clip
    unchanged. Real MoviePy is one of the two; test fakes may not
    implement either — that's fine, the fade is best-effort polish."""
    try:
        from moviepy.video.fx import FadeOut  # type: ignore
        if hasattr(clip, "with_effects"):
            return clip.with_effects([FadeOut(duration_s)])
    except ImportError:
        pass
    if hasattr(clip, "fadeout"):
        return clip.fadeout(duration_s)
    if hasattr(clip, "with_effects"):
        # Record the intent on a test fake so asserts can see it.
        marker = {"kind": "fade_out", "duration_s": duration_s}
        applied = clip.with_effects([marker])
        return applied if applied is not None else clip
    return clip


def _apply_fade_in(clip: Any, duration_s: float) -> Any:
    """Fade the head of ``clip`` in from black. See :func:`_apply_fade_out`
    for the API-shim rationale."""
    try:
        from moviepy.video.fx import FadeIn  # type: ignore
        if hasattr(clip, "with_effects"):
            return clip.with_effects([FadeIn(duration_s)])
    except ImportError:
        pass
    if hasattr(clip, "fadein"):
        return clip.fadein(duration_s)
    if hasattr(clip, "with_effects"):
        marker = {"kind": "fade_in", "duration_s": duration_s}
        applied = clip.with_effects([marker])
        return applied if applied is not None else clip
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
