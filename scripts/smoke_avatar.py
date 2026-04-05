"""
Avatar generation smoke test — provider-agnostic.

End-to-end test of the full avatar path:
  1. Generate a short voice clip (ElevenLabs)
  2. Upload audio to a free host → public URL
  3. Submit to the configured avatar provider via fal.ai queue
  4. Poll until complete (up to 15 min)
  5. Download the resulting 9:16 MP4

Usage:
    cd scripts/
    AVATAR_PROVIDER=veed python smoke_avatar.py      # VEED Fabric (default)
    AVATAR_PROVIDER=kling python smoke_avatar.py     # Kling v2 Pro (fallback)

Required env vars:
    ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
    FAL_API_KEY

    When AVATAR_PROVIDER=veed (default):
        VEED_AVATAR_IMAGE_URL

    When AVATAR_PROVIDER=kling:
        KLING_AVATAR_IMAGE_URL

Costs:
    - ~5 ElevenLabs free credits
    - ~$0.08/s (VEED 480p) or ~$0.115/s (Kling) × clip duration
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

logger = logging.getLogger("smoke_avatar")

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
    output_path = "output/audio/avatar_smoke_voice.mp3"

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


# ── Steps 3–5: Submit → poll → download via make_avatar_client ────────────────

async def step_avatar(provider: str, audio_url: str) -> str:
    _section(f"3–5. {provider.upper()} via fal.ai — submit → poll → download")
    from avatar_gen import make_avatar_client

    os.makedirs("output/avatar", exist_ok=True)
    output_path = f"output/avatar/{provider}_smoke_avatar.mp4"

    # Build config for the requested provider
    config: dict = {
        "avatar_provider": provider,
        "fal_api_key": _env("FAL_API_KEY"),
        "output_dir": "output/avatar",
    }
    if provider == "veed":
        config["veed_avatar_image_url"] = _env("VEED_AVATAR_IMAGE_URL")
        config["veed_resolution"] = os.environ.get("VEED_RESOLUTION", "480p")
    elif provider == "kling":
        config["kling_avatar_image_url"] = _env("KLING_AVATAR_IMAGE_URL")
    else:
        print(f"  {_FAIL}  Unknown AVATAR_PROVIDER: {provider!r}")
        sys.exit(1)

    client = make_avatar_client(config)

    portrait_key = "VEED_AVATAR_IMAGE_URL" if provider == "veed" else "KLING_AVATAR_IMAGE_URL"
    print(f"         Provider:  {provider}")
    print(f"         Portrait:  {os.environ.get(portrait_key, '')[:70]}")
    print(f"         Audio:     {audio_url[:70]}")

    t0 = time.monotonic()

    # Step 3: submit
    print("  ↗  Submitting to fal.ai queue...")
    request_id, status_url = await client._submit(audio_url)
    print(f"  {_PASS}  Submitted — request_id: {request_id}")
    print(f"         Status URL: {status_url}")

    # Step 4: poll (verbose — show each tick)
    print("  ⏳  Polling for completion (10s interval, up to 15 min)...")
    deadline = time.monotonic() + 15 * 60
    poll_count = 0
    video_url = None
    import httpx
    async with httpx.AsyncClient(timeout=15) as http:
        while time.monotonic() < deadline:
            resp = await http.get(
                status_url,
                headers={"Authorization": f"Key {_env('FAL_API_KEY')}"},
            )
            data = resp.json()
            status = data.get("status", "unknown")
            poll_count += 1
            elapsed_so_far = time.monotonic() - t0
            print(f"         [{elapsed_so_far:5.0f}s]  poll #{poll_count:02d} → {status}")

            if status == "COMPLETED":
                video_url = client._extract_video_url(data)
                if not video_url:
                    import json
                    print(f"  {_FAIL}  COMPLETED but video URL missing:")
                    print("         " + json.dumps(data, indent=2)[:500])
                    sys.exit(1)
                print(f"  {_PASS}  Generation complete in {time.monotonic() - t0:.0f}s")
                print(f"         Video URL: {video_url}")
                break

            if status == "FAILED":
                import json
                error = data.get("error") or data.get("detail", "unknown error")
                print(f"  {_FAIL}  Generation FAILED: {error}")
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

    provider = os.environ.get("AVATAR_PROVIDER", "veed").lower()

    print("=" * 60)
    print(f"Avatar Smoke Test  [{provider.upper()}]")
    print("=" * 60)

    # Pre-flight: verify required keys
    required = ["ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "FAL_API_KEY"]
    if provider == "veed":
        required.append("VEED_AVATAR_IMAGE_URL")
    elif provider == "kling":
        required.append("KLING_AVATAR_IMAGE_URL")

    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"\n  {_FAIL}  Missing env vars: {', '.join(missing)}")
        sys.exit(1)

    audio_path = step_voice()
    audio_url  = step_upload(audio_path)
    video_path = await step_avatar(provider, audio_url)

    print("\n" + "=" * 60)
    print(f"RESULT: {_PASS}  Avatar smoke test passed  [{provider.upper()}]")
    print(f"        Video saved to: {video_path}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
