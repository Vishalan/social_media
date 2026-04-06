import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _detect_face_center_y(frame) -> Optional[int]:
    """Detect the primary face in a video frame and return its center Y coordinate.

    Uses OpenCV Haar cascade (fast, no GPU needed). Returns None if no face found.
    Only needs to run once per video — cache the result.
    """
    try:
        import cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        if len(faces) == 0:
            return None
        # Pick the largest face
        largest = max(faces, key=lambda f: f[2] * f[3])
        x, y, w, h = largest
        center_y = y + h // 2
        logger.debug("Face detected at y=%d (center_y=%d) in %dx%d frame", y, center_y, frame.shape[1], frame.shape[0])
        return center_y
    except Exception as exc:
        logger.debug("Face detection failed: %s", exc)
        return None


def _find_ffmpeg() -> str:
    """Return an ffmpeg binary that supports the drawtext filter (requires libfreetype).

    Checks ffmpeg-full first (Homebrew keg-only), then falls back to whatever
    'ffmpeg' is on PATH.  Raises RuntimeError if neither binary exists.
    """
    candidates = [
        "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",  # macOS Homebrew ffmpeg-full
        shutil.which("ffmpeg") or "",
    ]
    for path in candidates:
        if path and Path(path).exists():
            return path
    raise RuntimeError(
        "ffmpeg not found.  Install with: brew install ffmpeg-full"
    )


FFMPEG = _find_ffmpeg()

# Duration (seconds) of the held thumbnail frame prepended to the final video.
# This hold is applied ONLY when constructing the final make_frame and audio
# in _assemble_broll_body — the avatar lip-sync timeline (computed by
# smoke_e2e._compute_avatar_windows) MUST remain on the speech-only timeline.
_THUMBNAIL_HOLD_S = 0.5


def _wrap_with_thumbnail_hold(make_frame_fn, thumbnail_array, hold_s: float):
    """Wrap a video make_frame function so that for ``t < hold_s`` it returns
    ``thumbnail_array``, and for ``t >= hold_s`` it delegates to
    ``make_frame_fn(t - hold_s)``.

    This keeps the underlying timeline (used for avatar lip-sync) untouched —
    the inner make_frame still operates on the speech-only clock.
    """
    def wrapped(t):
        if t < hold_s:
            return thumbnail_array
        return make_frame_fn(t - hold_s)
    return wrapped

# Locate a bold font available on the current OS for FFmpeg drawtext.
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",       # Debian/Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",                 # Fedora/RHEL
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",           # macOS
    "/System/Library/Fonts/Helvetica.ttc",                         # macOS fallback
    "C:/Windows/Fonts/arialbd.ttf",                                # Windows
]
_CAPTION_FONT = next(
    (p for p in _FONT_CANDIDATES if Path(p).exists()), ""
)
# For the FFmpeg drawtext filter we avoid specifying fontfile entirely on macOS
# because the system font paths contain spaces that break filter-graph parsing.
# ffmpeg-full is built with --enable-libfontconfig, so omitting fontfile lets
# FontConfig resolve "Arial Bold" (or any available bold sans) automatically.
_CAPTION_FONT_FFMPEG = ""  # intentionally empty; font resolved via FontConfig


def _fill_to_duration(clip, target_duration: float):
    """
    Extend or trim a clip to exactly target_duration without looping.

    - If clip is longer: trim to target_duration.
    - If clip is shorter: freeze the last frame for the remaining time,
      then concatenate — producing unique content followed by a hold,
      which is far less jarring than a loop restart.
    """
    from moviepy import ImageClip, concatenate_videoclips

    if clip.duration >= target_duration:
        return clip.subclipped(0, target_duration)

    # Freeze last frame for the remaining duration
    freeze_duration = target_duration - clip.duration
    last_t = max(0.0, clip.duration - 1 / 30)
    freeze = ImageClip(clip.get_frame(last_t)).with_duration(freeze_duration)
    return concatenate_videoclips([clip, freeze])


class VideoEditor:
    OUTPUT_WIDTH = 1080
    OUTPUT_HEIGHT = 1920
    HOOK_DURATION_S = 3.0   # First N seconds: full-screen avatar (hook)
    CTA_DURATION_S = 3.0    # Last N seconds: full-screen avatar (CTA)
    # Lip-sync offset for avatar provider. Set > 0 if lips lag audio.
    AVATAR_SYNC_OFFSET_S = 0.0

    def __init__(self, output_dir: str = "output/video"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def assemble(
        self,
        avatar_path,  # str (single clip) or list[str] (per-segment clips)
        broll_path: str,
        audio_path: str,
        caption_segments: list[dict],
        output_path: str,
        crop_to_portrait: bool = False,
        layout=None,  # AvatarLayout | None — import kept lazy to avoid circular deps
        thumbnail_path: "Path | str | None" = None,
    ) -> str:
        """
        Assemble a 9:16 vertical short (1080x1920).

        layout controls the compositing mode:
          HALF_SCREEN (default) — hook/CTA full-screen avatar, body = b-roll top + avatar bottom.
          SKIPPED               — b-roll fills entire frame, no avatar overlay.
          FULL_SCREEN           — avatar fills entire frame (b-roll ignored). Functional stub.
          STITCHED              — pre-stitched avatar clips; assembled as HALF_SCREEN.

        caption_segments: list of {word, start, end} dicts from faster-whisper.
        crop_to_portrait: set True when avatar is 16:9 landscape (HeyGen output) —
            center-crops to 9:16 before compositing. Native 9:16 providers leave this False.
        Returns output_path.
        """
        # Import here to avoid requiring avatar_gen as a hard dep for video_edit tests
        from avatar_gen.layout import AvatarLayout

        # Normalise layout — default to HALF_SCREEN; treat STITCHED as HALF_SCREEN
        if layout is None:
            layout = AvatarLayout.HALF_SCREEN
        if layout == AvatarLayout.STITCHED:
            layout = AvatarLayout.HALF_SCREEN

        if layout == AvatarLayout.SKIPPED:
            return self._assemble_broll_only(
                broll_path, audio_path, caption_segments, output_path
            )
        if layout == AvatarLayout.FULL_SCREEN:
            return self._assemble_full_screen(
                avatar_path, audio_path, caption_segments, output_path, crop_to_portrait
            )
        if layout == AvatarLayout.BROLL_BODY:
            return self._assemble_broll_body(
                avatar_path, broll_path, audio_path, caption_segments, output_path, crop_to_portrait,
                thumbnail_path=thumbnail_path,
            )
        # HALF_SCREEN (default)
        return self._assemble_half_screen(
            avatar_path, broll_path, audio_path, caption_segments, output_path, crop_to_portrait
        )
    def _assemble_half_screen(
        self,
        avatar_path: str,
        broll_path: str,
        audio_path: str,
        caption_segments: list[dict],
        output_path: str,
        crop_to_portrait: bool = False,
    ) -> str:
        """Half-screen layout: hook/CTA full-screen avatar, body = b-roll top + avatar bottom."""
        from moviepy import (
            AudioFileClip,
            ColorClip,
            CompositeVideoClip,
            ImageClip,
            VideoFileClip,
            concatenate_videoclips,
        )

        raw_avatar = VideoFileClip(avatar_path)
        if crop_to_portrait:
            # HeyGen produces 1920x1080 (16:9). Crop a centered 9:16 strip then resize.
            src_w, src_h = raw_avatar.w, raw_avatar.h
            crop_w = int(src_h * 9 / 16)
            x1 = (src_w - crop_w) // 2
            raw_avatar = raw_avatar.crop(x1=x1, y1=0, x2=x1 + crop_w, y2=src_h)
        avatar = raw_avatar.resized((self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT))
        _broll_raw = VideoFileClip(broll_path)
        target_w = self.OUTPUT_WIDTH      # 1080
        target_h = self.OUTPUT_HEIGHT // 2  # 960
        scale = min(target_w / _broll_raw.w, target_h / _broll_raw.h)
        _broll_scaled = _broll_raw.resized(
            (round(_broll_raw.w * scale), round(_broll_raw.h * scale))
        )
        if _broll_scaled.w == target_w and _broll_scaled.h == target_h:
            broll = _broll_scaled
        else:
            # Pad with black to fill the target half-screen area
            _bg = ColorClip(size=(target_w, target_h), color=(0, 0, 0), duration=_broll_scaled.duration)
            broll = CompositeVideoClip(
                [_bg, _broll_scaled.with_position("center")],
                size=(target_w, target_h),
            )
        audio = AudioFileClip(audio_path)
        total_duration = audio.duration

        hook_end = self.HOOK_DURATION_S
        cta_start = max(hook_end, total_duration - self.CTA_DURATION_S)

        # Hook segment: full-screen avatar
        hook = avatar.subclipped(0, min(hook_end, avatar.duration))

        # Body segment: B-roll top, avatar bottom
        body_duration = cta_start - hook_end
        body_avatar = (
            avatar.subclipped(
                min(hook_end, avatar.duration),
                min(cta_start, avatar.duration),
            ).with_position(("center", self.OUTPUT_HEIGHT // 2))
        )
        body_broll = _fill_to_duration(broll, body_duration).with_position(("center", 0))
        body_bg = ColorClip(
            size=(self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT),
            color=(0, 0, 0),
            duration=body_duration,
        )
        body = CompositeVideoClip([body_bg, body_broll, body_avatar])

        # CTA segment: full-screen avatar
        cta_avatar_start = min(cta_start, avatar.duration)
        cta_avatar_end = min(total_duration, avatar.duration)
        if cta_avatar_end > cta_avatar_start:
            cta = avatar.subclipped(cta_avatar_start, cta_avatar_end)
        else:
            cta = avatar.subclipped(
                max(0, avatar.duration - self.CTA_DURATION_S), avatar.duration
            )

        # Concatenate and attach audio
        final = concatenate_videoclips([hook, body, cta]).with_audio(audio)
        return self._write_with_captions(final, caption_segments, output_path)

    # ── Body layout segments ────────────────────────────────────────────
    _HALF_SCREEN_DURATION = 5.0   # seconds for circle PiP #1 (bottom-right)
    _FULL_AVATAR_DURATION = 5.0   # seconds for circle PiP #2 (bottom-left)

    def _assemble_broll_body(
        self,
        avatar_path,  # str (single clip) or list[str] (per-segment clips)
        broll_path: str,
        audio_path: str,
        caption_segments: list[dict],
        output_path: str,
        crop_to_portrait: bool = False,
        thumbnail_path: "Path | str | None" = None,
    ) -> str:
        """BROLL_BODY layout: mixed body with full-screen b-roll, half-and-half,
        and one full-avatar moment mid-body for visual variety.

        Body layout pattern:
          hook (3s avatar) → full b-roll → half-half → full b-roll →
          full avatar (4s) → full b-roll → half-half → full b-roll → CTA (3s avatar)
        """
        from moviepy import (
            AudioFileClip,
            ColorClip,
            CompositeVideoClip,
            ImageClip,
            VideoClip,
            VideoFileClip,
            concatenate_videoclips,
        )

        # ── Load avatar clips ────────────────────────────────────────────
        def _load_avatar(path):
            """Load and scale avatar clip to output dimensions (no stretch)."""
            raw = VideoFileClip(path)
            sc = max(self.OUTPUT_WIDTH / raw.w, self.OUTPUT_HEIGHT / raw.h)
            av = raw.resized((round(raw.w * sc), round(raw.h * sc)))
            if av.w != self.OUTPUT_WIDTH or av.h != self.OUTPUT_HEIGHT:
                ax = max(0, (av.w - self.OUTPUT_WIDTH) // 2)
                ay = max(0, (av.h - self.OUTPUT_HEIGHT) // 2)
                av = av.cropped(x1=ax, y1=ay,
                                x2=ax + self.OUTPUT_WIDTH,
                                y2=min(ay + self.OUTPUT_HEIGHT, av.h))
            return av

        if isinstance(avatar_path, list) and len(avatar_path) >= 4:
            # Per-segment clips: [hook, pip1, pip2, cta] — perfect lip sync
            av_hook = _load_avatar(avatar_path[0])
            av_pip1 = _load_avatar(avatar_path[1])
            av_pip2 = _load_avatar(avatar_path[2])
            av_cta  = _load_avatar(avatar_path[3])
        elif isinstance(avatar_path, list):
            av = _load_avatar(avatar_path[0])
            av_hook = av_pip1 = av_pip2 = av_cta = av
        else:
            av = _load_avatar(avatar_path)
            av_hook = av_pip1 = av_pip2 = av_cta = av

        audio = AudioFileClip(audio_path)
        total_duration = audio.duration

        hook_end = self.HOOK_DURATION_S
        cta_start = max(hook_end, total_duration - self.CTA_DURATION_S)
        body_duration = cta_start - hook_end

        _TRANS = 0.5  # transition animation duration

        # Detect face position once for circle PiP cropping
        _face_y = _detect_face_center_y(av_hook.get_frame(0))
        if _face_y is None:
            _face_y = av_hook.h // 3

        # ── Hook (full-screen avatar) ────────────────────────────────────
        hook = av_hook.subclipped(0, min(hook_end, av_hook.duration)).resized(
            (self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT)
        )

        # ── Load b-roll ──────────────────────────────────────────────────
        broll_raw = VideoFileClip(broll_path)
        broll_full = broll_raw.resized((self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT))
        broll_looped = _fill_to_duration(broll_full, body_duration)

        # ── Pre-read PiP avatar frames into memory for seek-free rendering ──
        # Avoids per-frame FFmpeg seeks which can introduce timing drift.
        _pip1_fps = av_pip1.fps if av_pip1 else 25
        _pip2_fps = av_pip2.fps if av_pip2 else 25
        _pip1_frames = [av_pip1.get_frame(i / _pip1_fps)
                        for i in range(int(av_pip1.duration * _pip1_fps))] if av_pip1 else []
        _pip2_frames = [av_pip2.get_frame(i / _pip2_fps)
                        for i in range(int(av_pip2.duration * _pip2_fps))] if av_pip2 else []
        logger.debug("Pre-read %d pip1 frames, %d pip2 frames", len(_pip1_frames), len(_pip2_frames))

        def _get_pip_frame(frames, fps, t):
            """Get pre-read frame by time — no file seek."""
            idx = min(int(t * fps), len(frames) - 1)
            idx = max(0, idx)
            return frames[idx]

        # ── Build body as one composite with smooth layout transitions ──
        # The b-roll plays continuously. At certain points the avatar
        # smoothly splits into view (b-roll shrinks to top half, avatar
        # grows into bottom half) then smoothly merges back to full b-roll.
        import numpy as np
        from PIL import Image as PILImage

        W = self.OUTPUT_WIDTH
        H = self.OUTPUT_HEIGHT
        half_h = H // 2

        mid_avatar_dur = min(self._FULL_AVATAR_DURATION, body_duration * 0.12)
        half1_dur = min(self._HALF_SCREEN_DURATION, body_duration * 0.12)

        if body_duration < 12.0:
            body = _fill_to_duration(broll_full, body_duration)
        else:
            # Body layout: broll → PiP#1(right) → broll → PiP#2(left) → broll
            fb = (body_duration - half1_dur - mid_avatar_dur) / 3.0

            t1 = fb; t2 = t1 + half1_dur
            t3 = t2 + fb; t4 = t3 + mid_avatar_dur

            def _ease(p):
                return 3 * p * p - 2 * p * p * p

            def _render_circle_pip(frame, af, scale, position_right):
                """Render a circular PiP overlay on the frame."""
                _CIRCLE_D = 360; _BORDER = 5; _PAD_X = 50; _PAD_B = 250
                diam = max(4, int(_CIRCLE_D * min(scale, 1.0)))
                radius = diam // 2
                # Face-centered square crop
                sq = min(af.shape[0], af.shape[1])
                face_cy = _face_y
                crop_top = max(0, face_cy - sq // 3)
                crop_top = min(crop_top, max(0, af.shape[0] - sq))
                crop_left = max(0, (af.shape[1] - sq) // 2)
                side = min(sq, af.shape[0] - crop_top, af.shape[1] - crop_left)
                avatar_sq = af[crop_top:crop_top+side, crop_left:crop_left+side]
                avatar_resized = np.array(
                    PILImage.fromarray(avatar_sq).resize((diam, diam), PILImage.LANCZOS))
                yy, xx = np.ogrid[:diam, :diam]
                cmask = ((xx - radius)**2 + (yy - radius)**2) <= radius**2
                cx = (W - _PAD_X - radius) if position_right else (_PAD_X + radius)
                cy = H - _PAD_B - radius
                y1 = max(0, cy - radius); x1 = max(0, cx - radius)
                y2 = min(H, y1 + diam); x2 = min(W, x1 + diam)
                my2 = y2 - y1; mx2 = x2 - x1
                # White border
                bd = diam + _BORDER * 2; br = bd // 2
                by1 = max(0, cy-br); bx1 = max(0, cx-br)
                by2 = min(H, by1+bd); bx2 = min(W, bx1+bd)
                byy, bxx = np.ogrid[:bd, :bd]
                bmask = ((bxx-br)**2 + (byy-br)**2) <= br**2
                frame[by1:by2, bx1:bx2][bmask[:by2-by1, :bx2-bx1]] = [255, 255, 255]
                # Avatar
                frame[y1:y2, x1:x2][cmask[:my2, :mx2]] = avatar_resized[:my2, :mx2][cmask[:my2, :mx2]]

            def body_make_frame(t):
                frame = np.zeros((H, W, 3), dtype=np.uint8)
                bf = broll_looped.get_frame(min(t, broll_looped.duration - 1/30))
                if bf.shape != (H, W, 3):
                    bf = np.array(PILImage.fromarray(bf).resize((W, H), PILImage.LANCZOS))
                frame[:] = bf

                # PiP #1 (bottom-right): t1→t2 with transitions
                if t1 - _TRANS < t < t2 + _TRANS:
                    if t < t1 + _TRANS:
                        scale = _ease(min(max((t - (t1-_TRANS)) / (2*_TRANS), 0), 1))
                    elif t > t2 - _TRANS:
                        scale = _ease(min(max(((t2+_TRANS) - t) / (2*_TRANS), 0), 1))
                    else:
                        scale = 1.0
                    av_t = max(0, t - (t1 - _TRANS))
                    af = _get_pip_frame(_pip1_frames, _pip1_fps, av_t)
                    _render_circle_pip(frame, af, scale, position_right=True)

                # PiP #2 (bottom-left): t3→t4 with transitions
                elif t3 - _TRANS < t < t4 + _TRANS:
                    if t < t3 + _TRANS:
                        scale = _ease(min(max((t - (t3-_TRANS)) / (2*_TRANS), 0), 1))
                    elif t > t4 - _TRANS:
                        scale = _ease(min(max(((t4+_TRANS) - t) / (2*_TRANS), 0), 1))
                    else:
                        scale = 1.0
                    av_t = max(0, t - (t3 - _TRANS))
                    af = _get_pip_frame(_pip2_frames, _pip2_fps, av_t)
                    _render_circle_pip(frame, af, scale, position_right=False)

                return frame

        # ── CTA prefix skip ──────────────────────────────────────────────
        _CTA_PREFIX = 2.0
        _cta_clip_offset = min(_CTA_PREFIX, max(0, av_cta.duration - self.CTA_DURATION_S))

        # Pre-read hook and CTA frames (same seek-free approach as PiPs)
        _hook_fps = av_hook.fps or 25
        _hook_frames = [av_hook.get_frame(i / _hook_fps)
                        for i in range(int(min(hook_end, av_hook.duration) * _hook_fps))]
        _cta_fps = av_cta.fps or 25
        _cta_clip_end = min(_cta_clip_offset + self.CTA_DURATION_S, av_cta.duration)
        _cta_frames = [av_cta.get_frame(_cta_clip_offset + i / _cta_fps)
                       for i in range(int((_cta_clip_end - _cta_clip_offset) * _cta_fps))]

        # ── Store half-and-half windows for caption positioning ────────
        if body_duration >= 12.0:
            self._split_windows = [
                (hook_end + t1, hook_end + t2),
            ]
        else:
            self._split_windows = []

        # ── Single unified make_frame for the ENTIRE video ───────────────
        # No concatenate_videoclips — eliminates timing drift at joins.
        def final_make_frame(t):
            if t < hook_end:
                # Hook: full-screen avatar
                f = _get_pip_frame(_hook_frames, _hook_fps, t)
                if f.shape != (H, W, 3):
                    f = np.array(PILImage.fromarray(f).resize((W, H), PILImage.LANCZOS))
                return f
            elif t < cta_start:
                # Body: b-roll + circle PiPs
                return body_make_frame(t - hook_end)
            else:
                # CTA: full-screen avatar
                cta_t = t - cta_start
                f = _get_pip_frame(_cta_frames, _cta_fps, cta_t)
                if f.shape != (H, W, 3):
                    f = np.array(PILImage.fromarray(f).resize((W, H), PILImage.LANCZOS))
                return f

        # ── Optional held thumbnail frame prepended to the final video ──
        # This is applied ONLY at the final composition layer. The avatar
        # lip-sync timeline above (hook_end, cta_start, body t1..t4, PiP
        # frame indices) is NEVER shifted — it still operates on the
        # speech-only clock. We just wrap the final make_frame and prepend
        # silence to the audio. See _wrap_with_thumbnail_hold and
        # docs/solutions/integration-issues/avatar-lip-sync-desync-across-segments-2026-04-05.md
        thumb_path_obj = Path(thumbnail_path) if thumbnail_path else None
        if thumb_path_obj is not None and thumb_path_obj.exists():
            from PIL import Image as _PILImg
            from moviepy import AudioClip as _AudioClip, concatenate_audioclips

            _img = _PILImg.open(str(thumb_path_obj)).convert("RGB")
            if _img.size != (W, H):
                logger.warning(
                    "Thumbnail %s has size %s, expected (%d, %d); resizing.",
                    thumb_path_obj, _img.size, W, H,
                )
                _img = _img.resize((W, H), _PILImg.LANCZOS)
            _thumb_arr = np.array(_img, dtype=np.uint8)

            wrapped_make_frame = _wrap_with_thumbnail_hold(
                final_make_frame, _thumb_arr, _THUMBNAIL_HOLD_S,
            )
            final_total_duration = total_duration + _THUMBNAIL_HOLD_S

            # Build silent prefix; preserve the existing audio's channel layout.
            n_channels = getattr(audio, "nchannels", 2) or 2
            if n_channels == 1:
                _silent_make = lambda t: 0.0  # noqa: E731
            else:
                import numpy as _np
                _silent_make = lambda t: _np.zeros((len(t), n_channels)) if hasattr(t, "__len__") else _np.zeros(n_channels)  # noqa: E731
            silent = _AudioClip(_silent_make, duration=_THUMBNAIL_HOLD_S, fps=getattr(audio, "fps", 44100))
            full_audio = concatenate_audioclips([silent, audio])

            # Shift caption timestamps so they remain aligned with speech.
            shifted_captions = [
                {**seg, "start": seg["start"] + _THUMBNAIL_HOLD_S,
                 "end": seg["end"] + _THUMBNAIL_HOLD_S}
                for seg in caption_segments
            ]
            # Shift split windows used by the caption renderer too.
            self._split_windows = [
                (s + _THUMBNAIL_HOLD_S, e + _THUMBNAIL_HOLD_S)
                for (s, e) in getattr(self, "_split_windows", [])
            ]

            final_clip = VideoClip(wrapped_make_frame, duration=final_total_duration).with_fps(24)
            final = final_clip.with_audio(full_audio)
            return self._write_with_captions(final, shifted_captions, output_path)

        final_clip = VideoClip(final_make_frame, duration=total_duration).with_fps(24)
        final = final_clip.with_audio(audio)
        return self._write_with_captions(final, caption_segments, output_path)

    def _assemble_broll_only(
        self,
        broll_path: str,
        audio_path: str,
        caption_segments: list[dict],
        output_path: str,
    ) -> str:
        """SKIPPED layout: b-roll fills the full 9:16 frame."""
        from moviepy import AudioFileClip, VideoFileClip

        audio = AudioFileClip(audio_path)
        raw = VideoFileClip(broll_path).resized((self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT))
        broll = _fill_to_duration(raw, audio.duration)
        final = broll.with_audio(audio)
        return self._write_with_captions(final, caption_segments, output_path)

    def _assemble_full_screen(
        self,
        avatar_path: str,
        audio_path: str,
        caption_segments: list[dict],
        output_path: str,
        crop_to_portrait: bool = False,
    ) -> str:
        """FULL_SCREEN layout: avatar fills entire 9:16 frame, no b-roll overlay."""
        from moviepy import AudioFileClip, VideoFileClip

        raw_avatar = VideoFileClip(avatar_path)
        if crop_to_portrait:
            src_w, src_h = raw_avatar.w, raw_avatar.h
            crop_w = int(src_h * 9 / 16)
            x1 = (src_w - crop_w) // 2
            raw_avatar = raw_avatar.crop(x1=x1, y1=0, x2=x1 + crop_w, y2=src_h)
        audio = AudioFileClip(audio_path)
        avatar = _fill_to_duration(
            raw_avatar.resized((self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT)),
            audio.duration,
        )
        final = avatar.with_audio(audio)
        return self._write_with_captions(final, caption_segments, output_path)

    def _write_with_captions(
        self,
        clip,
        caption_segments: list[dict],
        output_path: str,
    ) -> str:
        """Write clip to a temp file, burn captions via FFmpeg ASS subtitles."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        clip.write_videofile(
            tmp_path, codec="libx264", audio_codec="aac", fps=24, logger=None
        )
        if not caption_segments:
            import shutil as _sh
            _sh.move(tmp_path, output_path)
            return output_path

        with tempfile.NamedTemporaryFile(
            suffix=".ass", delete=False, mode="w", encoding="utf-8"
        ) as ass_tmp:
            ass_path = ass_tmp.name
            ass_tmp.write(self._build_ass_captions(caption_segments))

        result = subprocess.run(
            [
                FFMPEG, "-y", "-i", tmp_path,
                "-vf", f"ass={ass_path}",
                "-c:a", "copy", output_path,
            ],
            capture_output=True,
        )
        Path(tmp_path).unlink(missing_ok=True)
        Path(ass_path).unlink(missing_ok=True)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, result.args,
                output=result.stdout,
                stderr=result.stderr,
            )
        return output_path

    def _build_ass_captions(self, segments: list[dict]) -> str:
        """
        Build an ASS subtitle file for word-level animated captions.
        Style: bold white text, translucent pill background.
        Captions move to the center during half-and-half layout sections.
        """
        # ASS timestamp format: H:MM:SS.cc (centiseconds)
        def _ts(seconds: float) -> str:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = seconds % 60
            return f"{h}:{m:02d}:{s:05.2f}"

        cx = self.OUTPUT_WIDTH // 2       # 540
        cy_default = int(self.OUTPUT_HEIGHT * 0.75)  # 1440 — normal position
        cy_center = self.OUTPUT_HEIGHT // 2           # 960 — during half-half

        # Check if a timestamp falls within a half-and-half window
        split_windows = getattr(self, "_split_windows", [])

        def _caption_y(t: float) -> int:
            for win_start, win_end in split_windows:
                if win_start <= t <= win_end:
                    return cy_center
            return cy_default

        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {self.OUTPUT_WIDTH}\n"
            f"PlayResY: {self.OUTPUT_HEIGHT}\n"
            "WrapStyle: 0\n"
            "\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            # PrimaryColour &H00FFFFFF = white; OutlineColour &H96000000 = translucent black
            # BorderStyle=1 with thick Outline=20 creates a rounded pill effect
            # (the outline follows text contours with natural rounding)
            "Style: Caption,Arial,64,&H00FFFFFF,&H000000FF,&H96000000,&H00000000,"
            "1,0,0,0,100,100,0,0,1,20,0,5,10,10,10,1\n"
            "\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        # Group words into natural reading phrases — break at punctuation,
        # conjunctions, and clause boundaries rather than fixed counts.
        _MAX_WORDS = 7
        _MIN_WORDS = 2
        _BREAK_AFTER = {'.', ',', '?', '!', ';', ':', '—', '–', '-'}
        _BREAK_BEFORE = {
            'and', 'but', 'or', 'so', 'because', 'while', 'when', 'where',
            'that', 'which', 'who', 'if', 'then', 'than', 'as', 'for',
            'with', 'from', 'into', 'through', 'during', 'before', 'after',
            'without', 'between', 'however', 'meanwhile', 'instead',
        }

        chunks: list[list[dict]] = []
        current: list[dict] = []
        for seg in segments:
            word = seg["word"]
            current.append(seg)

            # Check if we should break after this word
            should_break = False
            if len(current) >= _MAX_WORDS:
                should_break = True
            elif len(current) >= _MIN_WORDS:
                # Break after punctuation at end of word
                if any(word.rstrip().endswith(p) for p in _BREAK_AFTER):
                    should_break = True

            if should_break:
                chunks.append(current)
                current = []
                continue

            # Check if the NEXT word is a natural break point (conjunction, preposition)
            # — we'll break before it when we see it next iteration

        if current:
            # Merge tiny trailing chunk into the previous one
            if len(current) < _MIN_WORDS and chunks:
                chunks[-1].extend(current)
            else:
                chunks.append(current)

        # Second pass: break before conjunctions if chunk is long enough
        refined: list[list[dict]] = []
        for chunk in chunks:
            if len(chunk) <= _MAX_WORDS:
                refined.append(chunk)
                continue
            # Try to split at a conjunction/preposition
            sub: list[dict] = []
            for seg in chunk:
                w_lower = seg["word"].strip().lower().rstrip('.,!?;:')
                if w_lower in _BREAK_BEFORE and len(sub) >= _MIN_WORDS:
                    refined.append(sub)
                    sub = [seg]
                else:
                    sub.append(seg)
            if sub:
                if len(sub) < _MIN_WORDS and refined:
                    refined[-1].extend(sub)
                else:
                    refined.append(sub)
        chunks = refined

        lines = [header]
        for chunk in chunks:
            if not chunk:
                continue
            start_ts = _ts(chunk[0]["start"])
            end_ts = _ts(chunk[-1]["end"])
            # Join words into a phrase
            phrase = " ".join(
                seg["word"].replace("{", r"\{").replace("}", r"\}")
                for seg in chunk
            )
            # Position at center during half-half, otherwise at 75% height
            cy = _caption_y(chunk[0]["start"])
            override = f"{{\\an5\\pos({cx},{cy})}}"
            lines.append(
                f"Dialogue: 0,{start_ts},{end_ts},Caption,,0,0,0,,{override}{phrase}\n"
            )

        return "".join(lines)

    def trim_silence(
        self, audio_path: str, segments: list[dict], output_path: str
    ) -> str:
        """
        Remove silence using faster-whisper word-level timestamps.
        Copies only speech spans (with 50ms padding) via FFmpeg concat demuxer.
        Returns output_path. If no segments, copies audio unchanged.
        """
        import shutil

        if not segments:
            shutil.copy2(audio_path, output_path)
            return output_path

        PADDING = 0.05  # seconds
        spans = [
            (max(0.0, s["start"] - PADDING), s["end"] + PADDING)
            for s in segments
        ]

        # Merge overlapping spans and small gaps (< 400ms) to avoid jerky cuts
        MIN_GAP_TO_CUT = 0.4  # only remove silences longer than 400ms

        merged = [list(spans[0])]
        for start, end in spans[1:]:
            gap = start - merged[-1][1]
            if gap <= MIN_GAP_TO_CUT:  # small gap — keep it (merge spans)
                merged[-1][1] = max(merged[-1][1], end)
            else:  # large gap (>400ms) — cut it
                merged.append([start, end])

        # Check if trimming actually saves anything meaningful
        total_audio = sum(e - s for s, e in merged)
        try:
            from mutagen.mp3 import MP3
            original_duration = MP3(audio_path).info.length
        except Exception:
            original_duration = total_audio + 1
        if total_audio >= 0.9 * original_duration:
            import shutil as _sh
            _sh.copy2(audio_path, output_path)
            return output_path

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as f:
            audio_abs = str(Path(audio_path).resolve())
            for start, end in merged:
                f.write(f"file '{audio_abs}'\n")
                f.write(f"inpoint {start:.3f}\n")
                f.write(f"outpoint {end:.3f}\n")
            concat_file = f.name

        subprocess.run(
            [
                FFMPEG, "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c", "copy", output_path,
            ],
            check=True,
            capture_output=True,
        )
        Path(concat_file).unlink(missing_ok=True)
        return output_path
