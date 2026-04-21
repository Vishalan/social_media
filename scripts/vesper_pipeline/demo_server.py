"""Server-side demo — real chatterbox voice with proper chunking +
real caption timings via faster-whisper.

Fixes three production issues from the first cut of this script:

  * **Voice trimmed at 40 s.** Chatterbox silently truncates any
    single ``/tts`` call at ~40 s of generated audio (auto-memory
    note on the ~40s truncation bug). The shipped
    :class:`ChatterboxVoiceGenerator` chunks text at sentence
    boundaries ≤380 chars and stitches the output wavs — this demo
    now uses it instead of a raw single POST.
  * **Captions out of sync.** Word timings were synthesized by
    distributing words uniformly across the TRUNCATED duration.
    Now we run ``faster-whisper`` on the stitched audio to recover
    actual word timings, matching how the production pipeline's
    ``transcribe_voice`` stage works.
  * **Personal voice.** Default ref is now
    ``/app/refs/vesper/archivist.wav`` — a Ralph-voice macOS-say
    sample with mild EQ (highpass 80 / lowpass 8 kHz + gain) that
    reads as a deeper, older, mysterious narrator. The previous
    default (``vishalan_voice_ref.wav``, CommonCreed's personal
    ref) is still selectable via ``--chatterbox-ref``.

Other behavior-preserving changes:
  * Exaggeration bumped to 0.5 (from 0.3) for more dramatic read.
  * Timeline rescales to the ACTUAL stitched-voice duration, not a
    single-call estimate.

Usage:

    ssh 192.168.29.237
    cd /opt/commoncreed/scripts
    /opt/commoncreed/.venv-vesper/bin/python3 -m vesper_pipeline.demo_server
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List

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
)
from still_gen._types import Beat, Timeline  # noqa: E402
from .assembler import VesperAssembler  # noqa: E402
from .captions import CaptionStyle, transcribe_voice  # noqa: E402
from ._ffmpeg import ffmpeg_bin  # noqa: E402
from ._types import VesperJob  # noqa: E402

logger = logging.getLogger(__name__)


DEFAULT_CHATTERBOX_REF = "/app/refs/vesper/archivist.wav"
DEFAULT_CHATTERBOX_NAME = "commoncreed_chatterbox"
DEFAULT_EXAGGERATION = 0.5
# Post-TTS tempo adjustment. Chatterbox reads fast (~230 wpm) from
# macOS-say-generated refs — Archivist target is ~140-160 wpm. 0.72
# stretches 40 s → 55 s which lands ~160 wpm on a 180-word script.
DEFAULT_TEMPO = 0.72

# Match the shipped ChatterboxVoiceGenerator's chunking rule: sentence
# boundaries, ≤380 chars per chunk (beats the ~40 s silent-truncation
# bug). See scripts/voiceover/chatterbox_generator.py._MAX_CHARS_PER_CHUNK.
_MAX_CHARS_PER_CHUNK = 380


# ─── Chunking + TTS ────────────────────────────────────────────────────────


def _chunk_text(text: str, max_chars: int = _MAX_CHARS_PER_CHUNK) -> List[str]:
    """Sentence-boundary split into chunks ≤ ``max_chars`` chars."""
    text = " ".join(text.split())
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: List[str] = []
    current = ""
    for sent in sentences:
        if not sent:
            continue
        if len(sent) > max_chars:
            # Sentence alone exceeds the cap → split on commas.
            pieces = re.split(r"(?<=,)\s+", sent)
            for piece in pieces:
                while len(piece) > max_chars:
                    cut = piece.rfind(" ", 0, max_chars)
                    if cut <= 0:
                        cut = max_chars
                    chunks.append(piece[:cut].strip())
                    piece = piece[cut:].strip()
                if piece:
                    if len(current) + 1 + len(piece) <= max_chars:
                        current = (current + " " + piece).strip()
                    else:
                        if current:
                            chunks.append(current)
                        current = piece
            continue
        if len(current) + 1 + len(sent) <= max_chars:
            current = (current + " " + sent).strip()
        else:
            if current:
                chunks.append(current)
            current = sent
    if current:
        chunks.append(current)
    return chunks


def _chatterbox_ip(container: str) -> str:
    result = subprocess.run(
        [
            "docker", "inspect",
            "--format",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            container,
        ],
        capture_output=True, text=True, check=True,
    )
    ip = result.stdout.strip()
    if not ip:
        raise RuntimeError(f"no IP for container {container!r}")
    return ip


def _tts_one_chunk(
    *,
    text: str,
    chunk_index: int,
    ref_path: str,
    exaggeration: float,
    container_name: str,
    chatterbox_url: str,
    local_dir: Path,
) -> Path:
    """POST one chunk; docker-cp the output WAV to ``local_dir``."""
    import httpx
    filename = f"vesper_chunk_{chunk_index:02d}.wav"
    resp = httpx.post(
        chatterbox_url,
        json={
            "text": text,
            "reference_audio_path": ref_path,
            "exaggeration": exaggeration,
            "output_filename": filename,
        },
        timeout=600,
    )
    resp.raise_for_status()
    data = resp.json()
    container_output = data["output_path"]
    local_wav = local_dir / filename
    subprocess.run(
        ["docker", "cp", f"{container_name}:{container_output}", str(local_wav)],
        check=True, capture_output=True,
    )
    return local_wav


def _concat_wavs(wavs: List[Path], out_wav: Path) -> None:
    """Concat WAVs via ffmpeg concat demuxer — no re-encode, sample-
    accurate boundaries."""
    ffmpeg = ffmpeg_bin()
    list_txt = out_wav.with_suffix(".list.txt")
    list_txt.write_text(
        "\n".join(f"file '{str(p.resolve())}'" for p in wavs) + "\n"
    )
    subprocess.run(
        [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(list_txt),
            "-c", "copy",
            str(out_wav),
        ],
        check=True, capture_output=True,
    )
    list_txt.unlink(missing_ok=True)


def _atempo_slow(in_wav: Path, out_wav: Path, factor: float) -> None:
    """Apply `atempo=factor` to slow (factor<1) or speed up. Preserves
    pitch via PSOLA. ffmpeg's atempo accepts 0.5-2.0; chain two filters
    if we need outside that range (not needed for our 0.65-0.85 target)."""
    if factor <= 0:
        raise ValueError("factor must be > 0")
    ffmpeg = ffmpeg_bin()
    subprocess.run(
        [
            ffmpeg, "-y", "-i", str(in_wav),
            "-af", f"atempo={factor:.3f}",
            "-c:a", "pcm_s16le",
            str(out_wav),
        ],
        check=True, capture_output=True,
    )


def _wav_to_mp3(wav_path: Path, mp3_path: Path) -> None:
    ffmpeg = ffmpeg_bin()
    subprocess.run(
        [
            ffmpeg, "-y", "-i", str(wav_path),
            "-codec:a", "libmp3lame", "-qscale:a", "2",
            str(mp3_path),
        ],
        check=True, capture_output=True,
    )


def _probe_duration_s(media: Path) -> float:
    ffmpeg = ffmpeg_bin()
    result = subprocess.run(
        [ffmpeg, "-i", str(media)],
        capture_output=True, text=True,
    )
    for line in result.stderr.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            ts = line.split()[1].rstrip(",")
            h, m, s = ts.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    raise RuntimeError("could not parse duration")


# ─── Demo runner ───────────────────────────────────────────────────────────


def run_demo(
    *,
    chatterbox_ref: str = DEFAULT_CHATTERBOX_REF,
    chatterbox_name: str = DEFAULT_CHATTERBOX_NAME,
    exaggeration: float = DEFAULT_EXAGGERATION,
    tempo: float = DEFAULT_TEMPO,
    output_path: Path | None = None,
) -> Path:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    demo_dir = _REPO_ROOT / "output" / "vesper" / "demo_server"
    demo_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_path or (demo_dir / "server-output.mp4")
    logger.info("=== Vesper server demo (chunked + whisper-synced) ===")
    logger.info("Output: %s", output_path)
    logger.info("Ref: %s (exag=%.2f)", chatterbox_ref, exaggeration)

    # 1. Chunk + TTS each chunk.
    chunks = _chunk_text(_STORY)
    logger.info("Story split into %d chunk(s)", len(chunks))
    ip = _chatterbox_ip(chatterbox_name)
    chatterbox_url = f"http://{ip}:7777/tts"

    chunk_wavs: List[Path] = []
    t0 = time.monotonic()
    for idx, text in enumerate(chunks):
        logger.info(
            "TTS chunk %d/%d (%d chars)",
            idx + 1, len(chunks), len(text),
        )
        wav = _tts_one_chunk(
            text=text,
            chunk_index=idx,
            ref_path=chatterbox_ref,
            exaggeration=exaggeration,
            container_name=chatterbox_name,
            chatterbox_url=chatterbox_url,
            local_dir=demo_dir,
        )
        chunk_wavs.append(wav)
    tts_wall = time.monotonic() - t0
    logger.info("TTS done: %d chunks in %.1f s", len(chunks), tts_wall)

    # 2. Stitch.
    stitched = demo_dir / "voice_stitched.wav"
    _concat_wavs(chunk_wavs, stitched)
    stitched_duration = _probe_duration_s(stitched)
    logger.info("Stitched voice (raw): %.2f s", stitched_duration)

    # 2a. Slow down to Archivist pace. Chatterbox cloned from a
    # macOS-say ref reads ~230 wpm; target is ~150 wpm. Pitch is
    # preserved by atempo's PSOLA.
    slowed = demo_dir / "voice_stitched_slow.wav"
    if tempo != 1.0:
        _atempo_slow(stitched, slowed, tempo)
        voice_source = slowed
        voice_duration = _probe_duration_s(slowed)
        logger.info(
            "Slowed x%.2f: %.2f s (archivist pace)",
            tempo, voice_duration,
        )
    else:
        voice_source = stitched
        voice_duration = stitched_duration

    # 3. Convert to MP3 for the assembler.
    mp3_path = demo_dir / "voice.mp3"
    _wav_to_mp3(voice_source, mp3_path)

    # 4. faster-whisper for REAL caption timings (on the SLOWED
    # audio so timings match what the viewer hears).
    logger.info("Transcribing voice via faster-whisper for real timings…")
    whisper_t0 = time.monotonic()
    caption_segments = transcribe_voice(str(voice_source))
    logger.info(
        "Whisper: %d word timings in %.1f s",
        len(caption_segments), time.monotonic() - whisper_t0,
    )
    if not caption_segments:
        logger.warning(
            "faster-whisper returned 0 segments — falling back to "
            "uniform word timing. Install faster-whisper for real timings."
        )
        words = [w for w in _STORY.split() if w]
        per = voice_duration / max(len(words), 1)
        caption_segments = [
            {"word": w, "start": round(i * per, 3),
             "end": round((i + 1) * per, 3)}
            for i, w in enumerate(words)
        ]

    # 5. Rescale the canned timeline to match the real voice duration.
    base_timeline = _build_timeline()
    base_total = base_timeline.total_duration_s
    scale = voice_duration / base_total if base_total > 0 else 1.0
    scaled_beats = [
        Beat(
            mode=b.mode,
            motion_hint=b.motion_hint,
            duration_s=round(b.duration_s * scale, 2),
            shot_class=b.shot_class,
            prompt=b.prompt,
            tag=b.tag,
        )
        for b in base_timeline.beats
    ]
    timeline = Timeline(beats=scaled_beats)
    logger.info(
        "Timeline scaled x%.3f: %d beats, %.1f s total",
        scale, timeline.count, timeline.total_duration_s,
    )

    # 6. Storyboard stills.
    stills_dir = demo_dir / "stills"
    stills_dir.mkdir(parents=True, exist_ok=True)
    still_paths: List[str] = []
    for idx, beat in enumerate(timeline.beats):
        out = stills_dir / f"beat_{idx:03d}.png"
        _render_storyboard_still(
            out_path=out,
            beat_index=idx, total=timeline.count,
            prompt=beat.prompt, tag=beat.tag,
        )
        still_paths.append(str(out))

    # 7. Build the job + assemble.
    job = VesperJob(
        topic_title="The 2:47 diner (server demo)",
        subreddit="demo",
        job_id="demo-server-v2",
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
    logger.info("Assembling MP4…")
    assembler.assemble(job=job, output_path=str(output_path))
    logger.info("Done: %s (%d bytes)",
                output_path, output_path.stat().st_size)
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vesper server demo")
    parser.add_argument("--chatterbox-ref", default=DEFAULT_CHATTERBOX_REF)
    parser.add_argument("--chatterbox-name", default=DEFAULT_CHATTERBOX_NAME)
    parser.add_argument(
        "--exaggeration", type=float, default=DEFAULT_EXAGGERATION,
    )
    parser.add_argument(
        "--tempo", type=float, default=DEFAULT_TEMPO,
        help="Post-TTS tempo multiplier (default 0.72 slows for Archivist pace)",
    )
    args = parser.parse_args(argv)
    try:
        run_demo(
            chatterbox_ref=args.chatterbox_ref,
            chatterbox_name=args.chatterbox_name,
            exaggeration=args.exaggeration,
            tempo=args.tempo,
        )
    except Exception as exc:
        logger.exception("demo failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
