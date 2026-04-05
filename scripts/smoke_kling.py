"""
Kling/fal.ai avatar generation smoke test.

End-to-end test of the full avatar path:
  1. Generate a short voice clip (ElevenLabs)
  2. Upload audio to Ayrshare → public URL
  3. Submit to Kling v2 Pro via fal.ai queue
  4. Poll until complete (up to 15 min)
  5. Download the resulting 9:16 MP4

Usage:
    cd scripts/
    python smoke_kling.py

Costs:
    - ~5 ElevenLabs free credits
    - ~1 Kling credit (fal.ai subscription)
    - No GPU pod
"""

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
for _noisy in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger("smoke_kling")

_PASS = "✓"
_FAIL = "✗"


def _env(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        print(f"  {_FAIL}  Missing required env var: {key}")
        sys.exit(1)
    return val


def _section(title: str) -> None:
    print(f"\n[{title}]")


# ── Step 1: Generate short voice clip ─────────────────────────────────────────

def step_voice() -> str:
    _section("1. ElevenLabs — generate short voice clip")
    from voiceover.voice_generator import VoiceGenerator

    os.makedirs("output/audio", exist_ok=True)
    output_path = "output/audio/kling_smoke_voice.mp3"

    gen = VoiceGenerator(api_key=_env("ELEVENLABS_API_KEY"))
    text = "AI is moving fast. Here's what you need to know today."
    t0 = time.monotonic()
    path = gen.generate(
        text,
        output_path,
        voice_id=_env("ELEVENLABS_VOICE_ID"),
    )
    elapsed = time.monotonic() - t0
    size_kb = Path(path).stat().st_size // 1024
    print(f"  {_PASS}  Voice generated in {elapsed:.1f}s  ({size_kb} KB → {path})")
    return path


# ── Step 2: Upload to free host → public URL ─────────────────────────────────

def _try_upload_catbox(audio_path: str) -> str:
    """Upload to catbox.moe — returns direct URL."""
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
    """Upload to 0x0.st — returns direct URL."""
    import requests as _req
    with open(audio_path, "rb") as f:
        resp = _req.post("https://0x0.st", files={"file": f}, timeout=60)
    resp.raise_for_status()
    url = resp.text.strip()
    if not url.startswith("http"):
        raise ValueError(f"0x0.st returned unexpected body: {url[:200]}")
    return url


def step_upload(audio_path: str) -> str:
    _section("2. Free file host — upload audio to get public URL")
    t0 = time.monotonic()

    for name, fn in [("catbox.moe", _try_upload_catbox), ("0x0.st", _try_upload_0x0)]:
        try:
            print(f"  ↗  Trying {name}...")
            audio_url = fn(audio_path)
            elapsed = time.monotonic() - t0
            print(f"  {_PASS}  Uploaded to {name} in {elapsed:.1f}s")
            print(f"         URL: {audio_url}")
            return audio_url
        except Exception as exc:
            print(f"  ↷  {name} failed ({exc}), trying next...")

    print(f"  {_FAIL}  All upload hosts failed")
    sys.exit(1)


# ── Step 3–5: Submit to Kling, poll, download ─────────────────────────────────

async def step_kling(audio_url: str) -> str:
    _section("3–5. Kling v2 Pro via fal.ai — submit → poll → download")
    from avatar_gen.kling_client import KlingAvatarClient

    os.makedirs("output/avatar", exist_ok=True)
    output_path = "output/avatar/kling_smoke_avatar.mp4"

    client = KlingAvatarClient(
        fal_api_key=_env("FAL_API_KEY"),
        avatar_image_url=_env("KLING_AVATAR_IMAGE_URL"),
    )

    print(f"         Portrait: {_env('KLING_AVATAR_IMAGE_URL')[:70]}")
    print(f"         Audio:    {audio_url[:70]}")

    t0 = time.monotonic()

    # Step 3: submit
    print("  ↗  Submitting to fal.ai queue...")
    request_id, status_url = await client._submit(audio_url)
    print(f"  {_PASS}  Submitted — request_id: {request_id}")
    print(f"         Status URL: {status_url}")

    # Step 4: poll
    print("  ⏳  Polling for completion (10s interval, up to 15 min)...")
    deadline = time.monotonic() + 15 * 60
    poll_count = 0
    async with __import__("httpx").AsyncClient(timeout=15) as http:
        while time.monotonic() < deadline:
            resp = await http.get(
                status_url,
                headers={"Authorization": f"Key {_env('FAL_API_KEY')}"},
            )
            data = resp.json()
            status = data.get("status", "unknown")
            poll_count += 1
            elapsed_so_far = time.monotonic() - t0
            print(f"         [{elapsed_so_far:5.0f}s]  poll #{poll_count:02d} → status: {status}")

            if status == "COMPLETED":
                video_url = (
                    (data.get("output") or data.get("result") or data)
                    .get("video", {})
                    .get("url")
                )
                if not video_url:
                    print(f"  {_FAIL}  COMPLETED but video.url missing in response:")
                    import json
                    print("         " + json.dumps(data, indent=2)[:500])
                    sys.exit(1)
                print(f"  {_PASS}  Generation complete in {time.monotonic() - t0:.0f}s")
                print(f"         Video URL: {video_url}")
                break

            if status == "FAILED":
                error = data.get("error") or data.get("detail", "unknown error")
                print(f"  {_FAIL}  Kling generation FAILED: {error}")
                import json
                print("         Full response: " + json.dumps(data, indent=2)[:500])
                sys.exit(1)

            await asyncio.sleep(10)
        else:
            print(f"  {_FAIL}  Timed out after 15 minutes (request_id={request_id})")
            sys.exit(1)

    # Step 5: download
    print("  ↙  Downloading video...")
    t_dl = time.monotonic()
    await client._download(video_url, output_path)
    dl_elapsed = time.monotonic() - t_dl
    size_kb = Path(output_path).stat().st_size // 1024
    total_elapsed = time.monotonic() - t0

    print(f"  {_PASS}  Downloaded in {dl_elapsed:.1f}s  ({size_kb} KB)")
    print(f"\n  📹  Output: {output_path}")
    print(f"  ⏱   Total time (submit → download): {total_elapsed:.0f}s")
    return output_path


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    load_dotenv()

    print("=" * 60)
    print("Kling / fal.ai Avatar Smoke Test")
    print("=" * 60)

    # Pre-flight: verify required keys
    required = ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID",
                "FAL_API_KEY", "KLING_AVATAR_IMAGE_URL"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"\n  {_FAIL}  Missing env vars: {', '.join(missing)}")
        sys.exit(1)

    audio_path = step_voice()
    audio_url  = step_upload(audio_path)
    video_path = await step_kling(audio_url)

    print("\n" + "=" * 60)
    print(f"RESULT: {_PASS}  Kling smoke test passed")
    print(f"        Video saved to: {video_path}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
