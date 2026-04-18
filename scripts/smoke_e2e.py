"""
End-to-end pipeline smoke test — single topic, no posting.

Runs every phase of the CommonCreed pipeline for one topic and prints a
detailed cost breakdown at the end. Telegram approval and social posting
are skipped — the final assembled video is saved locally.

Phases:
  1. Script generation      (Claude Sonnet)
  2. Voiceover              (ElevenLabs)
  3. Audio upload           (catbox.moe — free, no Ayrshare needed)
  4. Avatar generation      (VEED Fabric 1.0 via fal.ai)
  5. B-roll generation      (AI-selected CPU generator)
  6. Transcription          (faster-whisper)
  7. Silence trim + assemble (FFmpeg + MoviePy)

Cost tracked:
  - Claude Sonnet (script gen)  → $3.00/M input, $15.00/M output tokens
  - Claude Haiku  (b-roll selector + generators) → $0.25/M input, $1.25/M output
  - ElevenLabs   (voice)       → $0.50 / 1,000 chars (Starter plan estimate)
  - VEED Fabric  (avatar)      → $0.08 / second at 480p

Usage:
    cd scripts/
    python smoke_e2e.py

Required env vars:
    ANTHROPIC_API_KEY
    ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
    (FAL_API_KEY and VEED_AVATAR_IMAGE_URL only needed when SMOKE_USE_VEED=1)

Optional:
    SMOKE_NEWSLETTER_PDF — path to a Gmail-exported TLDR AI newsletter PDF
                           When set, Claude picks the best article from the PDF.
                           Overrides SMOKE_NEWSLETTER_URL / SMOKE_TOPIC / SMOKE_URL.
    SMOKE_NEWSLETTER_URL — TLDR AI archive URL, e.g. https://tldr.tech/ai/2026-04-01
                           When set, Claude picks the best article from the newsletter.
                           Falls back to SMOKE_NEWSLETTER_PDF if set and web scraping fails.
                           Overrides SMOKE_TOPIC / SMOKE_URL.
    SMOKE_TOPIC      — override the default topic title (ignored if newsletter vars set)
    SMOKE_URL        — override the default article URL  (ignored if newsletter vars set)
    SMOKE_USE_VEED   — set to 1 to enable VEED avatar generation (default: skipped,
                       a "Work in Progress" placeholder is used instead)
    PEXELS_API_KEY, BING_SEARCH_API_KEY
    VEED_RESOLUTION  — "480p" (default) or "720p"
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

try:
    from broll_gen.registry import BROLL_REGISTRY, cpu_types, gpu_types
except ImportError:  # pragma: no cover — tests import via top-level scripts.
    from scripts.broll_gen.registry import BROLL_REGISTRY, cpu_types, gpu_types

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
for _noisy in ("httpx", "httpcore", "urllib3", "moviepy", "imageio"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger("smoke_e2e")

_PASS = "✓"
_FAIL = "✗"

# ── Pricing constants ──────────────────────────────────────────────────────────

_SONNET_IN_PER_M  = 3.00   # $/M input tokens
_SONNET_OUT_PER_M = 15.00  # $/M output tokens
_HAIKU_IN_PER_M   = 0.25   # $/M input tokens
_HAIKU_OUT_PER_M  = 1.25   # $/M output tokens
_EL_PER_1K_CHARS  = 0.50   # $ / 1,000 chars (ElevenLabs Starter estimate)
_VEED_480P_PER_S  = 0.08   # $ / second at 480p
_VEED_720P_PER_S  = 0.15   # $ / second at 720p


# ── Cost tracker ──────────────────────────────────────────────────────────────

@dataclass
class CostTracker:
    sonnet_in:  int   = 0
    sonnet_out: int   = 0
    haiku_in:   int   = 0
    haiku_out:  int   = 0
    el_chars:   int   = 0
    veed_s:     float = 0.0
    veed_res:   str   = "480p"
    _log: list[str] = field(default_factory=list)

    def record_claude(self, model: str, usage) -> None:
        in_tok  = getattr(usage, "input_tokens",  0)
        out_tok = getattr(usage, "output_tokens", 0)
        if "haiku" in model.lower():
            self.haiku_in  += in_tok
            self.haiku_out += out_tok
        else:
            self.sonnet_in  += in_tok
            self.sonnet_out += out_tok
        self._log.append(
            f"    claude/{model}: +{in_tok} in / +{out_tok} out"
        )

    def record_el(self, n_chars: int) -> None:
        self.el_chars += n_chars

    def record_veed(self, seconds: float) -> None:
        self.veed_s += seconds

    @property
    def total_usd(self) -> float:
        return (
            self.sonnet_in  / 1_000_000 * _SONNET_IN_PER_M
            + self.sonnet_out / 1_000_000 * _SONNET_OUT_PER_M
            + self.haiku_in  / 1_000_000 * _HAIKU_IN_PER_M
            + self.haiku_out / 1_000_000 * _HAIKU_OUT_PER_M
            + self.el_chars  / 1_000     * _EL_PER_1K_CHARS
            + self.veed_s * (_VEED_720P_PER_S if self.veed_res == "720p" else _VEED_480P_PER_S)
        )

    def print_report(self) -> None:
        veed_rate = _VEED_720P_PER_S if self.veed_res == "720p" else _VEED_480P_PER_S
        print("\n" + "=" * 60)
        print("COST REPORT")
        print("=" * 60)
        print(f"  Claude Sonnet  {self.sonnet_in:>6} in / {self.sonnet_out:>5} out tokens"
              f"   ${self.sonnet_in/1e6*_SONNET_IN_PER_M + self.sonnet_out/1e6*_SONNET_OUT_PER_M:.4f}")
        print(f"  Claude Haiku   {self.haiku_in:>6} in / {self.haiku_out:>5} out tokens"
              f"   ${self.haiku_in/1e6*_HAIKU_IN_PER_M + self.haiku_out/1e6*_HAIKU_OUT_PER_M:.4f}")
        print(f"  ElevenLabs     {self.el_chars:>6} chars"
              f"                  ${self.el_chars/1000*_EL_PER_1K_CHARS:.4f}")
        print(f"  VEED Fabric    {self.veed_s:>6.1f}s  ({self.veed_res}, ${veed_rate}/s)"
              f"       ${self.veed_s * veed_rate:.4f}")
        print("  " + "-" * 50)
        print(f"  TOTAL                                          ${self.total_usd:.4f}")
        if self.total_usd > 0:
            daily_3 = self.total_usd * 3
            print(f"\n  @ 3 videos/day → ~${daily_3:.2f}/day  ~${daily_3*30:.0f}/month")
        print("=" * 60)


_tracker = CostTracker()


# ── Anthropic usage instrumentation ───────────────────────────────────────────

def _install_claude_hooks() -> None:
    """Monkey-patch Anthropic sync + async Messages classes to capture token usage."""
    try:
        # anthropic>=0.40 layout: messages is a subpackage
        from anthropic.resources.messages.messages import AsyncMessages, Messages
    except ImportError:
        # anthropic<=0.39 layout: messages is a flat module
        from anthropic.resources.messages import AsyncMessages, Messages

    # ---- Async client ----
    _orig_async = AsyncMessages.create

    async def _async_tracked(self, *args, **kwargs):
        resp = await _orig_async(self, *args, **kwargs)
        if hasattr(resp, "usage") and hasattr(resp, "model"):
            _tracker.record_claude(resp.model, resp.usage)
        return resp

    AsyncMessages.create = _async_tracked

    # ---- Sync client ----
    _orig_sync = Messages.create

    def _sync_tracked(self, *args, **kwargs):
        resp = _orig_sync(self, *args, **kwargs)
        if hasattr(resp, "usage") and hasattr(resp, "model"):
            _tracker.record_claude(resp.model, resp.usage)
        return resp

    Messages.create = _sync_tracked


# ── Helpers ───────────────────────────────────────────────────────────────────

def _env(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        print(f"  {_FAIL}  Missing env var: {key}")
        sys.exit(1)
    return val


def _section(title: str) -> None:
    print(f"\n[{title}]")


def _video_duration(path: str) -> float:
    """Return video duration in seconds using ffprobe."""
    # Prefer ffprobe co-located with ffmpeg-full (has full codec support)
    ffprobe = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"
    if not Path(ffprobe).exists():
        import shutil as _shutil
        ffprobe = _shutil.which("ffprobe") or "ffprobe"
    result = subprocess.run(
        [
            ffprobe, "-v", "quiet",
            "-print_format", "json",
            "-show_streams", path,
        ],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return 0.0
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video" and "duration" in stream:
            return float(stream["duration"])
    return 0.0


def _try_upload_fal(audio_path: str) -> str:
    """Upload via fal.ai storage — always reachable from fal.ai queue workers."""
    import fal_client
    os.environ.setdefault("FAL_KEY", os.environ.get("FAL_API_KEY", ""))
    url = fal_client.upload_file(audio_path)
    if not url.startswith("http"):
        raise ValueError(f"fal storage returned unexpected URL: {url[:200]}")
    return url


def _try_upload_catbox(audio_path: str) -> str:
    import requests as _req
    with open(audio_path, "rb") as f:
        resp = _req.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": ("audio.mp3", f, "audio/mpeg")},
            timeout=60,
        )
    resp.raise_for_status()
    url = resp.text.strip()
    if not url.startswith("http"):
        raise ValueError(f"catbox returned unexpected body: {url[:200]}")
    return url


def _try_upload_0x0(audio_path: str) -> str:
    import requests as _req
    with open(audio_path, "rb") as f:
        resp = _req.post("https://0x0.st", files={"file": f}, timeout=60)
    resp.raise_for_status()
    url = resp.text.strip()
    if not url.startswith("http"):
        raise ValueError(f"0x0.st returned unexpected body: {url[:200]}")
    return url


# ── Pipeline steps ────────────────────────────────────────────────────────────

def step_script(topic: dict) -> dict:
    _section("1. Script generation (Claude Sonnet)")
    from content_gen.script_generator import ScriptGenerator

    t0 = time.monotonic()
    gen = ScriptGenerator(
        api_provider="anthropic",
        api_key=_env("ANTHROPIC_API_KEY"),
        output_dir="output/scripts",
    )
    script = gen.generate_short_form(topic["title"], niche="AI & Technology")
    elapsed = time.monotonic() - t0
    script_text = script.get("script", "")
    print(f"  {_PASS}  Script generated in {elapsed:.1f}s  ({len(script_text.split())} words)")
    return script


def step_voice(topic: dict, script_text: str) -> str:
    provider = os.environ.get("VOICE_PROVIDER", "elevenlabs").lower()
    _section(f"2. Voiceover ({provider})")
    from voiceover import make_voice_generator

    safe = re.sub(r"[^a-z0-9_]", "_", topic["title"].lower())[:40]
    # Chatterbox returns WAV; keep the extension flexible.
    ext = "wav" if provider == "chatterbox" else "mp3"
    output_path = f"output/audio/{safe}_voice.{ext}"
    os.makedirs("output/audio", exist_ok=True)

    gen_config = {
        "voice_provider": provider,
        "elevenlabs_api_key": os.environ.get("ELEVENLABS_API_KEY", ""),
        "chatterbox_reference_audio": os.environ.get("CHATTERBOX_REFERENCE_AUDIO", ""),
        "chatterbox_endpoint": os.environ.get("CHATTERBOX_ENDPOINT", ""),
        "chatterbox_device": os.environ.get("CHATTERBOX_DEVICE", "cuda"),
    }
    gen = make_voice_generator(gen_config)
    t0 = time.monotonic()
    # voice_id only matters for ElevenLabs; chatterbox ignores it.
    path = gen.generate(script_text, output_path, voice_id=os.environ.get("ELEVENLABS_VOICE_ID", ""))
    elapsed = time.monotonic() - t0

    n_chars = len(script_text)
    if provider == "elevenlabs":
        _tracker.record_el(n_chars)
    size_kb = Path(path).stat().st_size // 1024
    print(f"  {_PASS}  Voice generated in {elapsed:.1f}s  ({n_chars} chars → {size_kb} KB → {path})")
    return path


def step_upload(audio_path: str) -> str:
    _section("3. Audio upload (fal.ai storage)")
    t0 = time.monotonic()
    for name, fn in [("fal.ai storage", _try_upload_fal), ("catbox.moe", _try_upload_catbox), ("0x0.st", _try_upload_0x0)]:
        try:
            print(f"  ↗  Trying {name}...")
            url = fn(audio_path)
            print(f"  {_PASS}  Uploaded in {time.monotonic()-t0:.1f}s")
            print(f"         URL: {url}")
            return url
        except Exception as exc:
            print(f"  ↷  {name} failed ({exc}), trying next...")
    print(f"  {_FAIL}  All upload hosts failed")
    sys.exit(1)


def _make_wip_avatar(output_path: str, duration: float) -> str:
    """Generate a black 'Work In Progress' placeholder avatar using FFmpeg."""
    from video_edit.video_editor import FFMPEG, VideoEditor

    os.makedirs(Path(output_path).parent, exist_ok=True)
    w, h = VideoEditor.OUTPUT_WIDTH, VideoEditor.OUTPUT_HEIGHT
    label = "AVATAR  /  Work In Progress"
    subprocess.run(
        [
            FFMPEG, "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r=24:d={duration:.3f}",
            "-vf", (
                f"drawtext=text='{label}':fontsize=48:fontcolor=white"
                f":x=(w-text_w)/2:y=(h-text_h)/2"
            ),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            output_path,
        ],
        check=True,
        capture_output=True,
    )
    return output_path


def _compute_avatar_windows(audio_duration: float) -> list[tuple[float, float]]:
    """Compute the exact audio timestamps where the avatar is visible.

    Matches the layout logic in VideoEditor._assemble_broll_body():
      - Hook: first HOOK_DURATION_S seconds
      - Mid-body: ~55% through the body for FULL_AVATAR_DURATION seconds
      - CTA: last CTA_DURATION_S seconds

    Returns list of (start, end) tuples in audio-time coordinates.
    """
    from video_edit.video_editor import VideoEditor as VE

    hook_end = VE.HOOK_DURATION_S
    cta_start = max(hook_end, audio_duration - VE.CTA_DURATION_S)
    body_duration = cta_start - hook_end
    _BUFFER = 0.5   # transition animation buffer

    windows = [
        (0.0, hook_end),                                       # hook
    ]
    if body_duration >= 12.0:
        mid_avatar_dur = min(VE._FULL_AVATAR_DURATION, body_duration * 0.12)
        half1_dur = min(VE._HALF_SCREEN_DURATION, body_duration * 0.12)
        fb = (body_duration - half1_dur - mid_avatar_dur) / 3.0

        # Body layout: fb → half1 → fb → MID_AVATAR → fb
        t1 = fb                         # start half1
        t2 = t1 + half1_dur             # end half1
        t3 = t2 + fb                    # start mid-avatar
        t4 = t3 + mid_avatar_dur        # end mid-avatar

        # Each segment is generated as a separate VEED call — no lead-in needed.
        h1_start = max(0, hook_end + t1 - _BUFFER)
        h1_end = min(audio_duration, hook_end + t2 + _BUFFER)
        windows.append((h1_start, h1_end))

        mid_start = max(0, hook_end + t3 - _BUFFER)
        mid_end = min(audio_duration, hook_end + t4 + _BUFFER)
        windows.append((mid_start, mid_end))

    # CTA — extend backwards to capture enough speech for VEED.
    # ElevenLabs often has trailing silence; extend back far enough to get
    # actual speech content so VEED doesn't auto-trim.
    cta_window_start = max(hook_end, cta_start - 2.0)
    windows.append((cta_window_start, audio_duration))         # CTA

    return windows


def _extract_avatar_segments(
    audio_path: str,
    windows: list[tuple[float, float]],
) -> list[str]:
    """Extract each avatar audio segment as a separate MP3 file.

    Each segment is generated independently by VEED for perfect lip sync —
    no audio jumps between non-contiguous segments.

    Returns list of temp MP3 paths; caller is responsible for cleanup.
    """
    import tempfile
    from video_edit.video_editor import FFMPEG

    seg_paths: list[str] = []
    for i, (start, end) in enumerate(windows):
        seg_path = tempfile.mktemp(suffix=f"_avatar_seg{i}.mp3")
        dur = end - start
        subprocess.run(
            [FFMPEG, "-y", "-ss", str(start), "-t", str(dur),
             "-i", audio_path, "-c:a", "libmp3lame", "-b:a", "192k", seg_path],
            check=True, capture_output=True,
        )
        seg_paths.append(seg_path)
    return seg_paths


async def step_avatar(topic: dict, audio_path: str, audio_duration: float) -> list[str]:
    """Generate avatar clips — one per visible segment for perfect lip sync.

    Returns a list of MP4 paths: [hook, pip1, pip2, cta].
    Each is independently generated by VEED from its own audio segment.
    """
    safe = re.sub(r"[^a-z0-9_]", "_", topic["title"].lower())[:40]
    os.makedirs("output/avatar", exist_ok=True)

    windows = _compute_avatar_windows(audio_duration)
    seg_names = ["hook", "pip1", "pip2", "cta"][:len(windows)]

    # Skip VEED unless explicitly opted in
    if not os.environ.get("SMOKE_USE_VEED"):
        _section("4. Avatar generation (skipped — WIP placeholder)")
        paths = []
        for i, (start, end) in enumerate(windows):
            p = f"output/avatar/{safe}_avatar_{seg_names[i]}.mp4"
            _make_wip_avatar(p, end - start)
            paths.append(p)
        total_s = sum(end - start for start, end in windows)
        print(f"  {_PASS}  WIP placeholders created ({total_s:.1f}s across {len(windows)} segments)")
        print(f"         Set SMOKE_USE_VEED=1 to enable real VEED avatar generation")
        return paths

    _section("4. Avatar generation (VEED Fabric via fal.ai)")
    from avatar_gen import make_avatar_client

    # Reuse existing clips if all are present
    expected_paths = [f"output/avatar/{safe}_avatar_{n}.mp4" for n in seg_names]
    if os.environ.get("SMOKE_REUSE_AVATAR") and all(Path(p).exists() for p in expected_paths):
        total_dur = sum(_video_duration(p) for p in expected_paths)
        _tracker.record_veed(total_dur)
        print(f"  {_PASS}  Reusing {len(expected_paths)} existing avatar clips ({total_dur:.1f}s total)")
        return expected_paths

    veed_res = os.environ.get("VEED_RESOLUTION", "480p")
    _tracker.veed_res = veed_res
    config = {
        "avatar_provider": "veed",
        "fal_api_key": _env("FAL_API_KEY"),
        "veed_avatar_image_url": _env("VEED_AVATAR_IMAGE_URL"),
        "veed_resolution": veed_res,
        "output_dir": "output/avatar",
    }

    # Extract each audio segment as a separate file
    seg_audio_paths = _extract_avatar_segments(audio_path, windows)

    # Save debug copies of extracted audio segments
    debug_dir = Path("output/debug_avatar")
    debug_dir.mkdir(parents=True, exist_ok=True)
    for i, seg_path in enumerate(seg_audio_paths):
        import shutil as _sh
        debug_audio = debug_dir / f"{seg_names[i]}_sent_to_veed.mp3"
        _sh.copy2(seg_path, debug_audio)
        print(f"  📎  Debug: {debug_audio} (audio [{windows[i][0]:.1f}→{windows[i][1]:.1f}])")

    # Upload all segments
    seg_audio_urls = []
    for i, seg_path in enumerate(seg_audio_paths):
        url = step_upload(seg_path)
        seg_audio_urls.append(url)

    # Generate all avatar clips in parallel
    print(f"  ↗  Generating {len(windows)} avatar clips in parallel (VEED Fabric, {veed_res})...")
    t0 = time.monotonic()

    async def _gen_one(idx, audio_url):
        client = make_avatar_client(config)
        out = f"output/avatar/{safe}_avatar_{seg_names[idx]}.mp4"
        return await client.generate(audio_url, out)

    tasks = [_gen_one(i, url) for i, url in enumerate(seg_audio_urls)]
    paths = await asyncio.gather(*tasks)
    elapsed = time.monotonic() - t0

    total_dur = sum(_video_duration(p) for p in paths)
    _tracker.record_veed(total_dur)
    print(f"  {_PASS}  {len(paths)} avatar clips generated in {elapsed:.0f}s ({total_dur:.1f}s total)")

    # Save debug: merge each avatar clip with its corresponding original audio
    try:
        from moviepy import VideoFileClip as _VFC, AudioFileClip as _AFC
        full_audio = _AFC(audio_path)
        for i, (av_path, (ws, we)) in enumerate(zip(paths, windows)):
            dbg_path = debug_dir / f"{seg_names[i]}_avatar_with_original_audio.mp4"
            v = _VFC(av_path)
            a = full_audio.subclipped(ws, min(we, full_audio.duration))
            dur = min(v.duration, a.duration)
            merged = v.subclipped(0, dur).with_audio(a.subclipped(0, dur))
            merged.write_videofile(str(dbg_path), codec="libx264", audio_codec="aac", fps=24, logger=None)
            print(f"  📎  Debug: {dbg_path}")
            v.close()
        full_audio.close()
    except Exception as exc:
        print(f"  ⚠  Debug merge failed (non-fatal): {exc}")

    # Cleanup segment audio files
    for p in seg_audio_paths:
        try: os.unlink(p)
        except OSError: pass

    return list(paths)


async def step_broll(topic: dict, script: dict, audio_duration: float) -> tuple[str, str]:
    _section("5. B-roll generation (AI-selected CPU generator)")
    from anthropic import AsyncAnthropic
    from broll_gen import BrollError, make_broll_generator
    from broll_gen.selector import BrollSelector
    import types

    safe = re.sub(r"[^a-z0-9_]", "_", topic["title"].lower())[:40]
    output_path = f"output/video/{safe}_broll.mp4"
    os.makedirs("output/video", exist_ok=True)

    anthropic_client = AsyncAnthropic(api_key=_env("ANTHROPIC_API_KEY"))
    selector = BrollSelector(anthropic_client)

    script_text = script.get("script", "")
    t0 = time.monotonic()
    types_ranked = await selector.select(topic["title"], topic.get("url", ""), script_text)
    print(f"  {_PASS}  Selector chose: primary={types_ranked[0]!r}, fallback={types_ranked[1]!r}")

    target_duration_s = max(6.0, audio_duration - 6.0)
    job_stub = types.SimpleNamespace(topic=topic, script=script)
    gen_kwargs = {
        "anthropic_client": anthropic_client,
        "pexels_api_key": os.environ.get("PEXELS_API_KEY", ""),
        "bing_api_key": os.environ.get("BING_SEARCH_API_KEY", ""),
    }

    winning_type = None
    _gpu_types = gpu_types()
    for type_name in [t for t in types_ranked if t not in _gpu_types]:
        try:
            print(f"  ↗  Trying {type_name}...")
            gen = make_broll_generator(type_name, **gen_kwargs)
            path = await gen.generate(job_stub, target_duration_s, output_path)
            winning_type = type_name
            elapsed = time.monotonic() - t0
            size_kb = Path(path).stat().st_size // 1024
            print(f"  {_PASS}  B-roll ({type_name}) generated in {elapsed:.1f}s  ({size_kb} KB → {path})")
            return path, winning_type
        except BrollError as exc:
            print(f"  ↷  {type_name} failed ({exc}), trying next...")

    print(f"  {_FAIL}  All CPU b-roll types failed — cannot continue without GPU (Phase 2)")
    sys.exit(1)


async def step_assemble(
    topic: dict,
    avatar_paths: list[str],
    broll_path: str,
    audio_path: str,
    script_text: str = "",
) -> str:
    _section("6–7. Transcribe + trim silence + assemble final video")
    from faster_whisper import WhisperModel
    from video_edit.video_editor import VideoEditor
    from avatar_gen.layout import AvatarLayout

    safe = re.sub(r"[^a-z0-9_]", "_", topic["title"].lower())[:40]

    # Transcribe for word-level timing, using the script as vocabulary hint.
    # Whisper gets the script as initial_prompt so it recognises domain terms
    # (e.g. "Veo" instead of "VO", "GPT-4o" instead of "GPT for").
    print("  ↗  Transcribing audio (faster-whisper base)...")
    t0 = time.monotonic()
    model = WhisperModel("base", device="cpu", compute_type="int8")
    prompt_hint = script_text[:500] if script_text else topic.get("title", "")
    segments, _ = model.transcribe(
        audio_path, word_timestamps=True, initial_prompt=prompt_hint,
    )
    whisper_words = []
    for seg in segments:
        for w in (seg.words or []):
            whisper_words.append({"word": w.word.strip(), "start": w.start, "end": w.end})

    # Use Whisper's own words — initial_prompt handles domain term spelling.
    # Script-word replacement doesn't work because Whisper may detect a
    # different number of words than the script contains.
    caption_segments = whisper_words

    print(f"  {_PASS}  Transcribed in {time.monotonic()-t0:.1f}s  ({len(caption_segments)} words)")

    # ── Unit A3: keyword-punch extraction (failure-isolated). ──
    # Mirrors the commoncreed_pipeline step between transcribe and assemble.
    keyword_punches: list = []
    try:
        from anthropic import AsyncAnthropic
        from content_gen.keyword_extractor import extract_keyword_punches
        anthropic_client = AsyncAnthropic(api_key=_env("ANTHROPIC_API_KEY"))
        punches = await extract_keyword_punches(
            script_text=script_text or topic.get("title", ""),
            caption_segments=caption_segments,
            anthropic_client=anthropic_client,
        )
        keyword_punches = list(punches)
        print(f"  {_PASS}  [A3] extracted {len(keyword_punches)} keyword punches")
    except Exception as _e:
        print(f"  ⚠  [A3] keyword extraction crashed (non-fatal): {_e}")
        keyword_punches = []

    # ── SFX event derivation (best-effort). ──
    sfx_events: list = []
    try:
        from audio.sfx import SfxEvent
        for p in keyword_punches:
            intensity = "heavy" if p.intensity == "heavy" else "light"
            sfx_events.append(SfxEvent(
                t_seconds=float(p.t_start),
                category="punch",
                intensity=intensity,
            ))
        print(f"  {_PASS}  [A3] derived {len(sfx_events)} sfx events")
    except Exception as _e:
        print(f"  ⚠  [A3] sfx derivation failed (non-fatal): {_e}")
        sfx_events = []

    # Use raw audio (no trim_silence) — avatar windows were computed from
    # this duration, so the assembler must use the same timeline.
    editor = VideoEditor(output_dir="output/video")

    # Assemble
    output_path = f"output/video/{safe}_final.mp4"
    print("  ↗  Assembling final 9:16 video (MoviePy + FFmpeg)...")
    t0 = time.monotonic()
    try:
        final = editor.assemble(
            avatar_path=avatar_paths,
            broll_path=broll_path,
            audio_path=audio_path,
            caption_segments=caption_segments,
            output_path=output_path,
            crop_to_portrait=False,
            layout=AvatarLayout.BROLL_BODY,
            thumbnail_path=topic.get("thumbnail_path"),
            keyword_punches=keyword_punches,
            sfx_events=sfx_events,
        )
    except subprocess.CalledProcessError as e:
        print(f"  {_FAIL}  FFmpeg failed (exit {e.returncode}):")
        print(e.stderr.decode(errors="replace")[-2000:])
        sys.exit(1)
    elapsed = time.monotonic() - t0
    size_mb = Path(final).stat().st_size / 1_048_576
    print(f"  {_PASS}  Assembled in {elapsed:.1f}s  ({size_mb:.1f} MB → {final})")
    return final


# ── Main ──────────────────────────────────────────────────────────────────────

async def _topic_from_newsletter_pdf(pdf_path: str) -> dict:
    """Parse a TLDR AI newsletter PDF and let Claude pick the best topic."""
    from anthropic import AsyncAnthropic
    from newsletter.pdf_parser import parse_tldr_pdf
    from newsletter.topic_selector import select_topic

    print(f"  ↗  Parsing newsletter PDF: {pdf_path}")
    articles = await parse_tldr_pdf(pdf_path)
    if not articles:
        print(f"  {_FAIL}  No articles found in PDF — check that pymupdf is installed")
        sys.exit(1)
    print(f"  ✓  Found {len(articles)} articles in PDF")

    client = AsyncAnthropic(api_key=_env("ANTHROPIC_API_KEY"))
    topic = await select_topic(articles, client)
    print(f"  ✓  Claude selected: {topic['title']!r}")
    print(f"       Reason : {topic.get('selection_reason', '')}")
    print(f"       Hook   : {topic.get('hook', '')}")
    return topic


async def _topic_from_newsletter(newsletter_url: str) -> dict:
    """Scrape the TLDR AI newsletter page and let Claude pick the best topic.

    Falls back to SMOKE_NEWSLETTER_PDF if web scraping returns no articles
    (e.g. blocked by Vercel bot protection).
    """
    from anthropic import AsyncAnthropic
    from newsletter.tldr_scraper import scrape_tldr_ai
    from newsletter.topic_selector import select_topic

    print(f"  ↗  Scraping newsletter: {newsletter_url}")
    articles = await scrape_tldr_ai(newsletter_url)

    if not articles:
        pdf_fallback = os.environ.get("SMOKE_NEWSLETTER_PDF", "")
        if pdf_fallback:
            print(f"  ↷  Web scraping returned 0 articles — falling back to PDF: {pdf_fallback}")
            return await _topic_from_newsletter_pdf(pdf_fallback)
        print(f"  {_FAIL}  No articles found — check that Playwright is installed and the URL is valid")
        print(f"         Tip: set SMOKE_NEWSLETTER_PDF=/path/to/newsletter.pdf as a fallback")
        sys.exit(1)

    print(f"  ✓  Found {len(articles)} articles in newsletter")
    client = AsyncAnthropic(api_key=_env("ANTHROPIC_API_KEY"))
    topic = await select_topic(articles, client)
    print(f"  ✓  Claude selected: {topic['title']!r}")
    print(f"       Reason : {topic.get('selection_reason', '')}")
    print(f"       Hook   : {topic.get('hook', '')}")
    return topic


async def main() -> None:
    load_dotenv()
    _install_claude_hooks()

    # Priority: SMOKE_NEWSLETTER_PDF > SMOKE_NEWSLETTER_URL > SMOKE_TOPIC/SMOKE_URL > default
    newsletter_pdf = os.environ.get("SMOKE_NEWSLETTER_PDF", "")
    newsletter_url = os.environ.get("SMOKE_NEWSLETTER_URL", "")
    if newsletter_pdf:
        print("=" * 60)
        print("CommonCreed E2E Smoke Test  [newsletter PDF mode]")
        print("=" * 60)
        topic = await _topic_from_newsletter_pdf(newsletter_pdf)
    elif newsletter_url:
        print("=" * 60)
        print("CommonCreed E2E Smoke Test  [newsletter mode]")
        print("=" * 60)
        topic = await _topic_from_newsletter(newsletter_url)
    else:
        topic = {
            "title": os.environ.get("SMOKE_TOPIC", "OpenAI releases GPT-4o mini for faster AI"),
            "url":   os.environ.get("SMOKE_URL",   "https://openai.com/index/gpt-4o-mini-advancing-cost-efficient-intelligence"),
        }
        print("=" * 60)
        print("CommonCreed E2E Smoke Test")
        print("=" * 60)

    print(f"  Topic:  {topic['title']}")
    print(f"  URL:    {topic['url']}")

    # Article body extraction (fully isolated — never raises).
    # Unit 0.4: stash the clean extract on the topic dict so downstream b-roll
    # generators (phone-highlight, tweet quote) can use real article text.
    try:
        try:
            from topic_intel.article_extractor import extract_article_text
        except ImportError:
            from scripts.topic_intel.article_extractor import extract_article_text
        topic_url = topic.get("url", "")
        if topic_url:
            article = extract_article_text(topic_url)
            if article is None:
                logger.warning(
                    "WARN: no article body — phone_highlight unavailable (url=%s)",
                    topic_url,
                )
            else:
                topic["extracted_article"] = article.to_dict()
                print(
                    f"  {_PASS}  extracted_article: {len(article.body_paragraphs)} paragraphs, "
                    f"lead {len(article.lead_paragraph)} chars"
                )
    except Exception as _ae_exc:
        logger.warning(
            "WARN: article extraction crashed: %s — phone_highlight unavailable",
            _ae_exc,
        )

    t_total = time.monotonic()

    # SMOKE_REUSE_AVATAR=1: skip the expensive API steps (script/voice/upload/VEED).
    # B-roll is always regenerated (it's fast/CPU-only and needs to reflect code changes).
    reuse_avatar = os.environ.get("SMOKE_REUSE_AVATAR", "")
    if reuse_avatar:
        safe = re.sub(r"[^a-z0-9_]", "_", topic["title"].lower())[:40]
        audio_path = f"output/audio/{safe}_voice.mp3"
        if not Path(audio_path).exists():
            print(f"  {_FAIL}  SMOKE_REUSE_AVATAR set but file missing: {audio_path}")
            sys.exit(1)
        from moviepy import AudioFileClip as _AFC
        audio_duration = _AFC(audio_path).duration
        # Check for per-segment avatar clips (new format) or single clip (legacy)
        seg_names = ["hook", "pip1", "pip2", "cta"]
        per_seg_paths = [f"output/avatar/{safe}_avatar_{n}.mp4" for n in seg_names]
        legacy_path = f"output/avatar/{safe}_avatar.mp4"
        if all(Path(p).exists() for p in per_seg_paths):
            avatar_paths = per_seg_paths
            total_dur = sum(_video_duration(p) for p in avatar_paths)
        elif Path(legacy_path).exists():
            # Legacy single-clip fallback — generate WIP per-segment clips
            avatar_paths = await step_avatar(topic, audio_path, audio_duration)
            total_dur = sum(_video_duration(p) for p in avatar_paths)
        else:
            # No avatar files — generate WIP placeholders
            avatar_paths = await step_avatar(topic, audio_path, audio_duration)
            total_dur = sum(_video_duration(p) for p in avatar_paths)
        _tracker.veed_res = os.environ.get("VEED_RESOLUTION", "480p")
        _tracker.record_veed(total_dur)
        print(f"  ↷  Reusing avatar + audio (steps 1-4 skipped); regenerating b-roll + thumbnail")
        stub_script = {"script": topic["title"], "title": topic["title"]}
        # Thumbnail step also runs in reuse mode — fully isolated, never raises.
        try:
            try:
                from thumbnail_gen.step import step_thumbnail
            except ImportError:
                from scripts.thumbnail_gen.step import step_thumbnail
            _thumb_run_dir = Path("output/thumbnails") / safe
            thumbnail_path = step_thumbnail(
                script_text=topic["title"],
                run_dir=_thumb_run_dir,
            )
            topic["thumbnail_path"] = str(thumbnail_path)
            print(f"  {_PASS}  thumbnail: {thumbnail_path}")
        except Exception as _e:
            print(f"  {_FAIL}  thumbnail step crashed (should be impossible): {_e}")
        broll_path, broll_type = await step_broll(topic, stub_script, audio_duration)
    else:
        script     = step_script(topic)
        # Thumbnail generation — fully isolated; never raises.
        try:
            try:
                from thumbnail_gen.step import step_thumbnail
            except ImportError:
                from scripts.thumbnail_gen.step import step_thumbnail
            safe = re.sub(r"[^a-z0-9_]", "_", topic["title"].lower())[:40]
            _thumb_run_dir = Path("output/thumbnails") / safe
            thumbnail_path = step_thumbnail(
                script_text=script.get("script", ""),
                run_dir=_thumb_run_dir,
            )
            topic["thumbnail_path"] = str(thumbnail_path)
            print(f"  {_PASS}  thumbnail: {thumbnail_path}")
        except Exception as _e:
            print(f"  {_FAIL}  thumbnail step crashed (should be impossible): {_e}")
        audio_path = step_voice(topic, script.get("script", ""))
        from moviepy import AudioFileClip as _AFC
        audio_duration = _AFC(audio_path).duration
        # step_avatar now handles segment extraction, upload, and parallel VEED calls.
        # It returns a list of avatar clip paths (one per visible segment).
        avatar_paths = await step_avatar(topic, audio_path, audio_duration)
        broll_path, broll_type = await step_broll(topic, script, audio_duration)

    # Pass script text for accurate captions (Whisper timing + script words)
    _script_text = ""
    if not reuse_avatar:
        _script_text = script.get("script", "")
    elif "script" in topic:
        _script_text = topic.get("script", "")
    final_path = await step_assemble(topic, avatar_paths, broll_path, audio_path, script_text=_script_text)

    total_elapsed = time.monotonic() - t_total

    print("\n" + "=" * 60)
    print(f"RESULT: {_PASS}  E2E smoke test passed")
    print(f"        Final video: {final_path}")
    print(f"        B-roll type: {broll_type}")
    print(f"        Total time:  {total_elapsed:.0f}s")
    print("=" * 60)

    _tracker.print_report()


if __name__ == "__main__":
    asyncio.run(main())
