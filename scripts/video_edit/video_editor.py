import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoEditor:
    OUTPUT_WIDTH = 1080
    OUTPUT_HEIGHT = 1920
    HOOK_DURATION_S = 3.0   # First N seconds: full-screen avatar (hook)
    CTA_DURATION_S = 3.0    # Last N seconds: full-screen avatar (CTA)

    def __init__(self, output_dir: str = "output/video"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def assemble(
        self,
        avatar_path: str,
        broll_path: str,
        audio_path: str,
        caption_segments: list[dict],
        output_path: str,
    ) -> str:
        """
        Assemble a 9:16 vertical short (1080x1920).

        Layout:
          - [0, HOOK_DURATION_S): full-screen avatar (hook)
          - [HOOK_DURATION_S, total - CTA_DURATION_S): half-screen —
            B-roll top half, avatar bottom half
          - [total - CTA_DURATION_S, total): full-screen avatar (CTA)

        caption_segments: list of {word, start, end} dicts from faster-whisper.
        Returns output_path.
        """
        from moviepy.editor import (
            AudioFileClip,
            ColorClip,
            CompositeVideoClip,
            VideoFileClip,
            concatenate_videoclips,
        )

        avatar = VideoFileClip(avatar_path).resize(
            (self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT)
        )
        broll = VideoFileClip(broll_path).resize(
            (self.OUTPUT_WIDTH, self.OUTPUT_HEIGHT // 2)
        )
        audio = AudioFileClip(audio_path)
        total_duration = audio.duration

        hook_end = self.HOOK_DURATION_S
        cta_start = max(hook_end, total_duration - self.CTA_DURATION_S)

        # Hook segment: full-screen avatar
        hook = avatar.subclip(0, min(hook_end, avatar.duration))

        # Body segment: B-roll top, avatar bottom
        body_duration = cta_start - hook_end
        body_avatar = (
            avatar.subclip(
                min(hook_end, avatar.duration),
                min(cta_start, avatar.duration),
            ).set_position(("center", self.OUTPUT_HEIGHT // 2))
        )
        broll_body_duration = min(body_duration, broll.duration)
        body_broll = (
            broll.subclip(0, broll_body_duration)
            .loop(duration=body_duration)
            .set_position(("center", 0))
        )
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
            cta = avatar.subclip(cta_avatar_start, cta_avatar_end)
        else:
            cta = avatar.subclip(
                max(0, avatar.duration - self.CTA_DURATION_S), avatar.duration
            )

        # Concatenate and attach audio
        final = concatenate_videoclips([hook, body, cta]).set_audio(audio)

        # Write intermediate without captions
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        final.write_videofile(
            tmp_path, codec="libx264", audio_codec="aac", fps=24, logger=None
        )

        # Burn captions via FFmpeg drawtext filter
        caption_filter = self._build_drawtext_filter(caption_segments)
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", tmp_path,
                "-vf", caption_filter,
                "-c:a", "copy", output_path,
            ],
            check=True,
            capture_output=True,
        )
        Path(tmp_path).unlink(missing_ok=True)

        return output_path

    def _build_drawtext_filter(self, segments: list[dict]) -> str:
        """
        Build an FFmpeg drawtext filter chain for word-level animated captions.
        Style: bold white text, black outline, centered at 75% height.
        Each word appears at its start timestamp and disappears at its end.
        Returns 'null' if no segments provided.
        """
        if not segments:
            return "null"

        font_size = 64
        parts = []
        for seg in segments:
            word = (
                seg["word"]
                .replace("\\", "\\\\")
                .replace("'", "\\'")
                .replace(":", "\\:")
            )
            start = seg["start"]
            end = seg["end"]
            parts.append(
                f"drawtext=fontsize={font_size}"
                f":fontcolor=white"
                f":borderw=3:bordercolor=black"
                f":x=(w-text_w)/2:y=h*0.75"
                f":text='{word}'"
                f":enable='between(t,{start:.3f},{end:.3f})'"
                f":fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            )
        return ",".join(parts)

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

        # Merge overlapping spans
        merged = [list(spans[0])]
        for start, end in spans[1:]:
            if start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])

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
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c", "copy", output_path,
            ],
            check=True,
            capture_output=True,
        )
        Path(concat_file).unlink(missing_ok=True)
        return output_path
