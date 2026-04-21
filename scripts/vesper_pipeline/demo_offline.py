"""Offline demo — produces a real Vesper MP4 with zero server deps.

Smallest possible "first output of Vesper" — runs the shipped
:class:`VesperAssembler` end-to-end against entirely local/synthetic
inputs:

  * **Story** — canned 180-word Archivist-register short. (Real
    Archivist writer needs ANTHROPIC_API_KEY; not required here.)
  * **Voice** — macOS ``say -v Daniel`` as a placeholder narrator.
    On non-Mac or when ``say`` is unavailable, falls back to a
    silent ``AudioFileClip`` sized to match the canned duration.
  * **Stills** — PIL-rendered storyboard frames: Vesper-palette
    solid background, beat index + prompt text centered. Gives
    you a watchable "visual script" without needing Flux.
  * **Captions** — synthesized word-level timings distributing the
    story's words uniformly across the total duration. Burns via
    the real ASS → FFmpeg pipeline.
  * **Overlays, parallax, hero I2V, SFX** — skipped (overlay_pack
    absent, no parallax/i2v backend wired, SFX pack absent).
  * **Approval, publish** — skipped. Demo only writes the MP4.

Output: ``output/vesper/demo/first-output.mp4``.

Run:

    cd scripts && python3 -m vesper_pipeline.demo_offline

Takes ~30 seconds on a MacBook. The MP4 auto-opens via ``open`` on
macOS.

Upgrade path: once chatterbox + Flux + a real story are wired,
``python3 -m vesper_pipeline`` produces the real thing — this demo
proves the pipeline shape works without blocking on those.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Tuple

# Path bootstrap — same as __main__.py.
_SCRIPTS = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SCRIPTS.parent
for p in (str(_SCRIPTS), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from still_gen._types import Beat, BeatMode, Timeline  # noqa: E402

from .assembler import VesperAssembler  # noqa: E402
from .captions import CaptionStyle  # noqa: E402
from ._types import VesperJob  # noqa: E402

logger = logging.getLogger(__name__)


# ─── Canned content ────────────────────────────────────────────────────────


_STORY = (
    "I drove truck for fourteen years on the same stretch of interstate. "
    "You learn the rhythm of it. The same billboards, the same rest "
    "stops, the same faces behind the counter at the all-night diner "
    "outside Amarillo. One Tuesday in November I pulled in at two-"
    "forty-seven in the morning for coffee and a bathroom. The lot "
    "was empty. Just my rig and one blue sedan. I remember thinking "
    "the sedan was odd because its headlights were still on. Inside, "
    "the waitress set my cup down without looking up. She said quietly, "
    "don't turn around. I asked her what. She said the man at the "
    "counter behind you came in an hour ago and he hasn't moved. He "
    "hasn't blinked. She said, I think he's waiting for someone and I "
    "don't know who. I paid for my coffee and I left. The blue sedan "
    "was gone. My rig was exactly where I parked it. I never stopped "
    "at that diner again."
)


_BEATS: Tuple[dict, ...] = (
    # (duration_s, mode, motion_hint, tag, prompt_for_storyboard)
    {"d": 3.2, "tag": "hook",    "prompt": "empty truck stop at 2am, cold fluorescent light"},
    {"d": 3.5, "tag": "hook",    "prompt": "rain on asphalt, red diner sign in distance"},
    {"d": 3.0, "tag": "setup",   "prompt": "interior of a roadside diner, two stools occupied"},
    {"d": 3.8, "tag": "setup",   "prompt": "close on a ceramic coffee cup, steam rising"},
    {"d": 3.3, "tag": "rising",  "prompt": "waitress with her back turned, refusing to look up"},
    {"d": 4.2, "tag": "rising",  "prompt": "a silhouette at the counter, perfectly still"},
    {"d": 3.0, "tag": "reveal",  "prompt": "reflection in a chrome coffee pot — the man behind"},
    {"d": 3.7, "tag": "reveal",  "prompt": "whispered words spreading across the diner"},
    {"d": 3.4, "tag": "climax",  "prompt": "narrator paying at the register, looking forward"},
    {"d": 3.2, "tag": "climax",  "prompt": "door swinging shut, rainy asphalt outside"},
    {"d": 3.0, "tag": "tail",    "prompt": "the blue sedan, now gone, empty parking space"},
    {"d": 3.5, "tag": "tail",    "prompt": "the road stretching into night, taillights fading"},
)


# ─── Helpers ───────────────────────────────────────────────────────────────


def _synthesize_caption_segments(story: str, total_duration_s: float) -> List[dict]:
    """Distribute words uniformly across the total duration. Good
    enough for the demo — real runs use faster-whisper."""
    words = [w for w in story.replace("\n", " ").split() if w]
    if not words or total_duration_s <= 0:
        return []
    per = total_duration_s / len(words)
    segments = []
    for i, w in enumerate(words):
        segments.append({
            "word": w,
            "start": round(i * per, 3),
            "end": round((i + 1) * per, 3),
        })
    return segments


def _build_timeline() -> Timeline:
    motions = ["push_in", "pull_back", "slow_pan_left", "slow_pan_right"]
    beats: List[Beat] = []
    for i, b in enumerate(_BEATS):
        beats.append(Beat(
            mode=BeatMode.STILL_KENBURNS,
            motion_hint=motions[i % 4],  # type: ignore[arg-type]
            duration_s=b["d"],
            shot_class="interior" if i % 2 else "exterior",  # type: ignore[arg-type]
            prompt=b["prompt"],
            tag=b["tag"],
        ))
    return Timeline(beats=beats)


def _render_storyboard_still(
    *,
    out_path: Path,
    beat_index: int,
    total: int,
    prompt: str,
    tag: str,
) -> None:
    """Render a 1080x1920 PNG: Vesper palette background with the
    beat index + tag + prompt text. Serves as a storyboard frame."""
    from PIL import Image, ImageDraw, ImageFont  # local import

    # Vesper palette (from channels/vesper.py).
    NEAR_BLACK = (10, 10, 12)
    BONE = (232, 226, 212)
    OXIDIZED_BLOOD = (139, 26, 26)
    GRAPHITE = (44, 40, 38)

    img = Image.new("RGB", (1080, 1920), NEAR_BLACK)
    draw = ImageDraw.Draw(img)

    # Subtle vignette via two filled rectangles at top + bottom.
    draw.rectangle([(0, 0), (1080, 160)], fill=GRAPHITE)
    draw.rectangle([(0, 1760), (1080, 1920)], fill=GRAPHITE)

    # Try to find a usable font. PIL's default is tiny; Inter or
    # system fonts look fine.
    font_paths = [
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/Library/Fonts/Georgia.ttf",
    ]
    body_font = None
    for p in font_paths:
        if os.path.exists(p):
            try:
                body_font = ImageFont.truetype(p, 42)
                break
            except OSError:
                pass
    if body_font is None:
        body_font = ImageFont.load_default()

    tag_font = None
    for p in font_paths:
        if os.path.exists(p):
            try:
                tag_font = ImageFont.truetype(p, 32)
                break
            except OSError:
                pass
    if tag_font is None:
        tag_font = ImageFont.load_default()

    # Index dot (top right) in oxidized-blood.
    draw.text(
        (940, 80),
        f"{beat_index + 1:02d}/{total:02d}",
        fill=OXIDIZED_BLOOD,
        font=tag_font,
    )

    # Tag (top left) in bone.
    draw.text(
        (60, 80),
        tag.upper(),
        fill=BONE,
        font=tag_font,
    )

    # Prompt centered, word-wrapped. PIL doesn't wrap natively; do it
    # by greedy line packing.
    max_width = 960
    words = prompt.split()
    lines: List[str] = []
    current = ""
    for w in words:
        candidate = (current + " " + w).strip()
        bbox = draw.textbbox((0, 0), candidate, font=body_font)
        width = bbox[2] - bbox[0]
        if width <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)

    # Render wrapped text centered vertically.
    line_h = 64
    total_h = len(lines) * line_h
    y = (1920 - total_h) // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=body_font)
        w = bbox[2] - bbox[0]
        x = (1080 - w) // 2
        draw.text((x, y), line, fill=BONE, font=body_font)
        y += line_h

    img.save(str(out_path), format="PNG")


def _ffmpeg_binary() -> str:
    """Return a usable ffmpeg binary. Prefer the bundled imageio_ffmpeg
    one (stable across brew drift); fall back to system ``ffmpeg``."""
    try:
        import imageio_ffmpeg  # type: ignore
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except ImportError:
        pass
    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        return sys_ffmpeg
    raise RuntimeError(
        "No ffmpeg available. Install imageio-ffmpeg (`pip install "
        "imageio-ffmpeg`) or a working system ffmpeg."
    )


def _synth_voice(
    story: str,
    out_path: Path,
    *,
    target_duration_s: float,
) -> bool:
    """Generate voice via macOS ``say``. Returns True on success;
    on any failure writes a silent track of ``target_duration_s`` to
    ``out_path`` and returns False."""
    ffmpeg = _ffmpeg_binary()
    if shutil.which("say"):
        try:
            aiff_path = out_path.with_suffix(".aiff")
            subprocess.run(
                ["say", "-v", "Daniel", "-o", str(aiff_path), "-r", "145", story],
                check=True,
                timeout=60,
            )
            # Convert AIFF → MP3 via ffmpeg.
            subprocess.run(
                [
                    ffmpeg, "-y",
                    "-i", str(aiff_path),
                    "-codec:a", "libmp3lame",
                    "-qscale:a", "2",
                    str(out_path),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            aiff_path.unlink(missing_ok=True)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
                FileNotFoundError) as exc:
            logger.warning("say/ffmpeg failed: %s — falling back to silent track", exc)

    # Silent track fallback.
    try:
        subprocess.run(
            [
                ffmpeg, "-y",
                "-f", "lavfi",
                "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
                "-t", f"{target_duration_s:.2f}",
                "-codec:a", "libmp3lame",
                "-qscale:a", "2",
                str(out_path),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return False
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise RuntimeError(
            f"Could not synthesize voice OR silent track: {exc}. "
            "Install ffmpeg."
        ) from exc


# ─── Demo runner ───────────────────────────────────────────────────────────


def run_demo(*, output_path: Path | None = None, auto_open: bool = True) -> Path:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    demo_dir = _REPO_ROOT / "output" / "vesper" / "demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_path or (demo_dir / "first-output.mp4")

    logger.info("=== Vesper offline demo ===")
    logger.info("Output: %s", output_path)

    # 1. Build timeline.
    timeline = _build_timeline()
    total_duration = timeline.total_duration_s
    logger.info(
        "Timeline: %d beats, %.1fs total",
        timeline.count, total_duration,
    )

    # 2. Render storyboard stills.
    stills_dir = demo_dir / "stills"
    stills_dir.mkdir(parents=True, exist_ok=True)
    still_paths: List[str] = []
    for idx, beat in enumerate(timeline.beats):
        out = stills_dir / f"beat_{idx:03d}.png"
        _render_storyboard_still(
            out_path=out,
            beat_index=idx,
            total=timeline.count,
            prompt=beat.prompt,
            tag=beat.tag,
        )
        still_paths.append(str(out))
    logger.info("Rendered %d storyboard stills → %s", len(still_paths), stills_dir)

    # 3. Synthesize voice.
    voice_path = demo_dir / "voice.mp3"
    real_voice = _synth_voice(_STORY, voice_path, target_duration_s=total_duration)
    logger.info(
        "Voice: %s (%s)",
        voice_path,
        "macOS say" if real_voice else "silent track",
    )

    # 4. Synthesize captions from word counts.
    caption_segments = _synthesize_caption_segments(_STORY, total_duration)
    logger.info("Caption segments: %d words", len(caption_segments))

    # 5. Build the job.
    job = VesperJob(
        topic_title="The 2:47 diner",
        subreddit="demo",
        job_id="demo-first-output",
        story_script=_STORY,
        story_word_count=len(_STORY.split()),
        voice_path=str(voice_path),
        voice_duration_s=total_duration,
        caption_segments=caption_segments,
        still_paths=still_paths,
        parallax_paths=[],
        i2v_paths=[],
        timeline=timeline,
        beat_count=timeline.count,
    )

    # 6. Build the assembler. Vesper palette captions ON; overlays +
    # zoom bells OFF (no pack sourced, no keyword punches derived).
    caption_style = CaptionStyle(
        primary="#E8E2D4",
        accent="#8B1A1A",
        shadow="#2C2826",
        font_name="Georgia",   # Vesper's CormorantGaramond absent — Georgia is a close stand-in
        fontsize=54,
        active_fontsize=66,
    )
    assembler = VesperAssembler(
        caption_style=caption_style,
        overlay_pack=None,
        enable_zoom_bells=False,
        enable_scene_fades=True,
    )

    # 7. Render.
    logger.info("Assembling MP4 (this is the slow step — ~15-30s)")
    assembler.assemble(job=job, output_path=str(output_path))
    logger.info("Done: %s (%d bytes)",
                output_path, output_path.stat().st_size)

    # 8. Open on macOS.
    if auto_open and shutil.which("open"):
        try:
            subprocess.Popen(["open", str(output_path)])
        except Exception as exc:
            logger.warning("could not auto-open %s: %s", output_path, exc)

    return output_path


def main(argv: list[str] | None = None) -> int:
    try:
        run_demo()
    except Exception as exc:
        logger.exception("demo failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
