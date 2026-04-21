"""Server-side demo — real chatterbox voice + storyboard visuals.

Upgrade from :mod:`vesper_pipeline.demo_offline`: runs the same
pipeline shape but swaps the macOS ``say`` placeholder voice for
actual chatterbox TTS on the server's RTX 3090. The storyboard
stills stay as Vesper-palette placeholders (Flux upgrade lands
once ComfyUI is configured per the server-bringup runbook).

Wiring assumptions (don't-break-CommonCreed):
  * The chatterbox container (``commoncreed_chatterbox``) is already
    running on the ``commoncreed`` Docker bridge network. We reach
    it by its container IP on that network, not through a host
    port publish — the existing CommonCreed compose doesn't
    publish 7777 to the host and we're not modifying it.
  * The reference clip is whatever sits at
    ``/app/refs/<ref-name>.wav`` inside the chatterbox container.
    Defaults to ``vishalan_voice_ref.wav`` (CommonCreed's existing
    ref) as a Vesper placeholder. Swap to
    ``vesper/archivist.wav`` once that's mounted per
    server-bringup S1.
  * TTS output lands on the ``commoncreed_output`` named volume
    at ``/app/output/<filename>``. We ``docker cp`` it out to
    the demo's local output dir — avoids needing sudo on the
    volume host path.

Usage:

    ssh 192.168.29.237
    cd /opt/commoncreed/scripts
    /opt/commoncreed/.venv-vesper/bin/python3 -m vesper_pipeline.demo_server

Flags:
    --chatterbox-ref   Container path to the reference WAV.
                       Defaults to /app/refs/vishalan_voice_ref.wav.
    --chatterbox-name  Container name (default commoncreed_chatterbox).
    --exaggeration     Chatterbox expressiveness 0.0-1.0 (default 0.3).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Path bootstrap.
_SCRIPTS = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SCRIPTS.parent
for p in (str(_SCRIPTS), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from .demo_offline import (  # noqa: E402
    _STORY,
    _build_timeline,
    _render_storyboard_still,
    _synthesize_caption_segments,
    _ffmpeg_binary,
)
from still_gen._types import BeatMode  # noqa: E402
from .assembler import VesperAssembler  # noqa: E402
from .captions import CaptionStyle  # noqa: E402
from ._types import VesperJob  # noqa: E402

logger = logging.getLogger(__name__)


DEFAULT_CHATTERBOX_REF = "/app/refs/vishalan_voice_ref.wav"
DEFAULT_CHATTERBOX_NAME = "commoncreed_chatterbox"


def _chatterbox_ip(container: str) -> str:
    """Resolve the chatterbox container's IP on its Docker bridge
    network. One `docker inspect` call."""
    result = subprocess.run(
        [
            "docker", "inspect",
            "--format", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            container,
        ],
        capture_output=True, text=True, check=True,
    )
    ip = result.stdout.strip()
    if not ip:
        raise RuntimeError(
            f"could not resolve IP for container {container!r}. "
            "Is it running on the commoncreed Docker network?"
        )
    return ip


def _chatterbox_tts(
    *,
    text: str,
    ref_path: str,
    container: str,
    exaggeration: float,
    output_filename: str,
    local_output_dir: Path,
) -> Path:
    """POST to chatterbox; docker-cp the generated WAV out; return
    the local WAV path."""
    import httpx  # local import so the module loads without it

    ip = _chatterbox_ip(container)
    url = f"http://{ip}:7777/tts"
    logger.info("chatterbox TTS @ %s (ref=%s, exag=%.2f)",
                url, ref_path, exaggeration)
    t0 = time.monotonic()
    resp = httpx.post(
        url,
        json={
            "text": text,
            "reference_audio_path": ref_path,
            "exaggeration": exaggeration,
            "output_filename": output_filename,
        },
        timeout=600,  # 10-min ceiling — generous for a 180-word script
    )
    resp.raise_for_status()
    data = resp.json()
    dur_ms = (time.monotonic() - t0) * 1000
    logger.info(
        "chatterbox: %d ms wall, %s ms audio, sr=%d",
        dur_ms, data.get("duration_ms"), data.get("sample_rate"),
    )

    container_output = data.get("output_path")
    if not container_output:
        raise RuntimeError(f"chatterbox returned no output_path: {data}")

    local_output_dir.mkdir(parents=True, exist_ok=True)
    local_wav = local_output_dir / output_filename
    subprocess.run(
        ["docker", "cp", f"{container}:{container_output}", str(local_wav)],
        check=True,
    )
    return local_wav


def _wav_to_mp3(wav_path: Path, mp3_path: Path) -> None:
    """Convert WAV to MP3 via ffmpeg (bundled or system)."""
    ffmpeg = _ffmpeg_binary()
    subprocess.run(
        [
            ffmpeg, "-y", "-i", str(wav_path),
            "-codec:a", "libmp3lame", "-qscale:a", "2",
            str(mp3_path),
        ],
        check=True, capture_output=True,
    )


def _probe_wav_duration(wav_path: Path) -> float:
    """ffprobe via the bundled ffmpeg. Returns seconds as float."""
    ffmpeg = _ffmpeg_binary()
    # Run ffmpeg -i and parse the Duration from stderr — avoids
    # needing a separate ffprobe binary.
    result = subprocess.run(
        [ffmpeg, "-i", str(wav_path)],
        capture_output=True, text=True,
    )
    for line in result.stderr.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            # "Duration: 00:00:42.15, start: ..."
            time_str = line.split()[1].rstrip(",")
            h, m, s = time_str.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    raise RuntimeError(f"could not parse duration from ffmpeg output")


def run_demo(
    *,
    chatterbox_ref: str = DEFAULT_CHATTERBOX_REF,
    chatterbox_name: str = DEFAULT_CHATTERBOX_NAME,
    exaggeration: float = 0.3,
    output_path: Path | None = None,
) -> Path:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    demo_dir = _REPO_ROOT / "output" / "vesper" / "demo_server"
    demo_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_path or (demo_dir / "server-output.mp4")

    logger.info("=== Vesper server demo ===")
    logger.info("Output: %s", output_path)

    # 1. Generate real voice via chatterbox.
    wav_path = _chatterbox_tts(
        text=_STORY,
        ref_path=chatterbox_ref,
        container=chatterbox_name,
        exaggeration=exaggeration,
        output_filename="vesper_demo_server.wav",
        local_output_dir=demo_dir,
    )
    mp3_path = demo_dir / "voice.mp3"
    _wav_to_mp3(wav_path, mp3_path)
    voice_duration = _probe_wav_duration(wav_path)
    logger.info("voice: %s (%.1fs) → %s", wav_path, voice_duration, mp3_path)

    # 2. Build a timeline sized to the actual voice duration.
    # The canned 12-beat timeline totals ~40.8 s; real chatterbox
    # output for this 180-word script lands 40-60 s. We scale each
    # beat's duration proportionally so the visual track matches the
    # audio length.
    base_timeline = _build_timeline()
    base_total = base_timeline.total_duration_s
    scale = voice_duration / base_total if base_total > 0 else 1.0
    from still_gen._types import Beat, Timeline
    scaled_beats = []
    for b in base_timeline.beats:
        scaled_beats.append(Beat(
            mode=b.mode,
            motion_hint=b.motion_hint,
            duration_s=round(b.duration_s * scale, 2),
            shot_class=b.shot_class,
            prompt=b.prompt,
            tag=b.tag,
        ))
    timeline = Timeline(beats=scaled_beats)
    logger.info(
        "Timeline scaled x%.3f: %d beats, %.1fs total (was %.1fs)",
        scale, timeline.count, timeline.total_duration_s, base_total,
    )

    # 3. Storyboard stills.
    stills_dir = demo_dir / "stills"
    stills_dir.mkdir(parents=True, exist_ok=True)
    still_paths = []
    for idx, beat in enumerate(timeline.beats):
        out = stills_dir / f"beat_{idx:03d}.png"
        _render_storyboard_still(
            out_path=out,
            beat_index=idx, total=timeline.count,
            prompt=beat.prompt, tag=beat.tag,
        )
        still_paths.append(str(out))
    logger.info("Rendered %d storyboard stills", len(still_paths))

    # 4. Synthesize caption timings from word counts.
    caption_segments = _synthesize_caption_segments(_STORY, voice_duration)

    # 5. Build the job + run the real assembler.
    job = VesperJob(
        topic_title="The 2:47 diner (server demo)",
        subreddit="demo",
        job_id="demo-server-first",
        story_script=_STORY,
        story_word_count=len(_STORY.split()),
        voice_path=str(mp3_path),
        voice_duration_s=voice_duration,
        caption_segments=caption_segments,
        still_paths=still_paths,
        parallax_paths=[],
        i2v_paths=[],
        timeline=timeline,
        beat_count=timeline.count,
    )

    caption_style = CaptionStyle(
        primary="#E8E2D4",
        accent="#8B1A1A",
        shadow="#2C2826",
        font_name="Georgia",
        fontsize=54,
        active_fontsize=66,
    )
    assembler = VesperAssembler(
        caption_style=caption_style,
        overlay_pack=None,
        enable_zoom_bells=False,
        enable_scene_fades=True,
    )
    logger.info("Assembling MP4 (~20-40s)")
    assembler.assemble(job=job, output_path=str(output_path))
    logger.info("Done: %s (%d bytes)",
                output_path, output_path.stat().st_size)
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vesper server-side demo")
    parser.add_argument("--chatterbox-ref", default=DEFAULT_CHATTERBOX_REF)
    parser.add_argument("--chatterbox-name", default=DEFAULT_CHATTERBOX_NAME)
    parser.add_argument("--exaggeration", type=float, default=0.3)
    args = parser.parse_args(argv)
    try:
        run_demo(
            chatterbox_ref=args.chatterbox_ref,
            chatterbox_name=args.chatterbox_name,
            exaggeration=args.exaggeration,
        )
    except Exception as exc:
        logger.exception("demo failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
