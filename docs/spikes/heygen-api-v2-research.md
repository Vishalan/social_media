# HeyGen API v2 — Avatar IV Research Spike

**Date:** 2026-03-29
**Purpose:** Evaluate HeyGen Avatar IV API for automated short-form content pipeline (@commoncreed)

---

## 1. Avatar IV Video Generation Endpoints

### Primary Endpoint

There are two ways to invoke Avatar IV via API, depending on your source material:

**A. Dedicated Avatar IV endpoint (Photo-to-Video)**
```
POST https://api.heygen.com/v2/video/av4/generate
```
Required parameters:
- `image_key` — returned from the Upload Asset API (upload your photo first)
- `video_title` — string
- `script` — text the avatar will speak
- `voice_id` — from List All Voices V2

Optional parameters:
- `custom_motion_prompt` — natural language to guide gestures/expressions
- `enhance_custom_motion_prompt` — boolean, lets AI refine the motion prompt

**B. General video generate endpoint with Avatar IV flag (Studio/Digital Twin avatars)**
```
POST https://api.heygen.com/v2/video/generate
```
Request body structure:
```json
{
  "title": "Your Video Title",
  "dimension": {
    "width": 1080,
    "height": 1920
  },
  "video_inputs": [
    {
      "character": {
        "type": "avatar",
        "avatar_id": "YOUR_AVATAR_ID",
        "avatar_style": "normal"
      },
      "voice": {
        "type": "audio",
        "audio_url": "https://your-cdn.com/voiceover.mp3"
      }
    }
  ]
}
```
To enable Avatar IV motion on existing avatars, pass `"use_avatar_iv_model": true` when working with Talking Photos/Photo Avatars.

The dedicated `/v2/video/av4/generate` endpoint was added via a changelog update and is the canonical path for the Avatar IV model going forward.

### Status Polling Endpoint

```
GET https://api.heygen.com/v1/video_status.get?video_id={video_id}
```
or
```
GET https://api.heygen.com/v1/video/{video_id}
```

Status values returned:
- `pending` — queued, not yet rendering
- `processing` — rendering in progress
- `completed` — done, `video_url` field populated
- `failed` — error occurred

The `video_url` is regenerated fresh on every poll call (signed URL with new `Expires` param). Download promptly after seeing `completed`.

There is also a dedicated Digital Twin generation status endpoint:
```
GET https://api.heygen.com/v2/video_avatar/check/{avatar_id}
```

### Retrieving the Finished Video URL

The `video_url` field in the status response contains the downloadable MP4. Because it is a signed URL that regenerates on each call, poll until `status == "completed"` then immediately download.

### Typical Generation Time (30–60 second video)

- **Priority queue (Pro/Scale API plans):** First 100 videos/month get priority. A 60-second Avatar IV video typically processes in **5–15 minutes**.
- **Standard queue:** Can range from a few hours up to 36 hours on weekdays; faster on weekends. Average is just under 24 hours in the standard queue.
- HeyGen's documented rule of thumb: every 1 minute of video takes ~10 minutes to generate, often faster on priority queue.
- Avatar IV has a hard cap of **3 minutes (180 seconds)** maximum video length regardless of plan.

### Rate Limits and Concurrency

- **Concurrent video processing:** 3 videos at a time on standard API plans. Additional submissions queue behind these.
- HeyGen does not publicly publish per-minute request rate limits. Their docs state automated safeguards detect and temporarily block "abusive" patterns but exact thresholds are undisclosed.
- For high-volume needs, Enterprise plan required with custom concurrency negotiation.

---

## 2. Custom Avatar Creation via API

HeyGen distinguishes between two avatar types relevant to API use:

### A. Digital Twin (Video Avatar) — Full animated avatar from video footage

**Submission endpoint:**
```
POST https://api.heygen.com/v2/video_avatar
```
or per the API reference:
```
POST https://api.heygen.com/v2/video_avatar/submit
```

Required parameters:
- `training_footage_url` — publicly accessible URL to your training video (S3, GCS, etc.)
- `video_consent_url` — publicly accessible URL to your consent statement video
- `avatar_name` — string

Video requirements:
- Minimum: 30 seconds of footage
- Recommended: 2–5 minutes for best results
- Must record in either 16:9 or 9:16 orientation

**Training status check:**
```
GET https://api.heygen.com/v2/video_avatar/check/{avatar_id}
```

**Training duration:** Not officially documented with a precise time, but community reports indicate 15–60 minutes for a standard Digital Twin. The `avatar_id` returned from submission is used to poll status.

### B. Photo Avatar Group (Instant Avatar from a single photo)

**Create avatar group:**
```
POST https://api.heygen.com/v2/photo_avatar/avatar_group/create
```

**Train the group:**
```
POST https://api.heygen.com/v2/photo_avatar/train
```
Body: `{ "group_id": "YOUR_GROUP_ID" }`

**Check training status:**
```
GET https://api.heygen.com/v2/photo_avatar/train/status/{group_id}
```

Photo avatar training builds a LoRA model enabling consistent generation across different "looks" (scenes, clothing, poses).

### Referencing a Trained Avatar in Video Calls

Once training completes, use the `avatar_id` (Digital Twin) or the avatar ID from the group (Photo Avatar) in the `character.avatar_id` field of `/v2/video/generate`, or as the `avatar_id` in `/v2/video/av4/generate`.

To list all available avatars including custom ones:
```
GET https://api.heygen.com/v2/avatars
```

---

## 3. Video Specifications

### Vertical 9:16 Format Support

**Partially supported, with a known limitation.** The API accepts `9:16` in the `aspect_ratio` field and `{"width": 1080, "height": 1920}` in `dimension`. However, there is a documented bug/limitation in the general `/v2/video/generate` API (as of early 2026): the avatar is rendered in landscape and then padded with black/white bars rather than rendered natively in portrait. This results in a portrait frame with a letterboxed avatar.

The dedicated `/v2/video/av4/generate` endpoint behavior for portrait is less clearly documented. For production use with true 9:16 output, test both endpoints and verify. The HeyGen Studio editor handles portrait natively; the API lags behind.

**Workaround options:**
1. Generate at 1:1 or 16:9 and crop/reframe in post-processing (FFmpeg)
2. Use the Avatar IV endpoint directly and test if portrait padding issue applies
3. Contact HeyGen Enterprise for custom rendering options

### Supported Output Resolutions

- Standard API plans: **1080p maximum** (no 4K via API)
- Enterprise plan: 4K available
- Avatar IV specifically advertises **1280p+ HD** for photo-to-video
- WebM format available for Digital Twin 4K avatars (Enterprise)

### Input Audio Format (for lip-sync to ElevenLabs audio)

HeyGen accepts pre-generated audio via two methods in the voice configuration:

```json
"voice": {
  "type": "audio",
  "audio_url": "https://your-cdn.com/elevenlabs_output.mp3"
}
```
or
```json
"voice": {
  "type": "audio",
  "audio_asset_id": "ASSET_ID_FROM_UPLOAD_API"
}
```

Exactly one of `audio_url` or `audio_asset_id` must be provided — providing both or neither causes an error.

**Supported audio formats:** MP3 confirmed. WAV likely supported (ElevenLabs exports MP3 by default, which works).

### Supplying Your Own Audio for Lip-Sync

Yes — this is fully supported and is the recommended pattern for ElevenLabs integration. Generate audio via ElevenLabs API, upload to S3/GCS or any public CDN, then pass the URL as `audio_url`. The avatar lip-syncs to the supplied audio.

HeyGen does support ElevenLabs voices natively within their platform (including V3 model), but for automated pipeline use, supplying a pre-generated `audio_url` is the cleanest approach since you already have `VoiceGenerator` generating files locally.

---

## 4. Authentication

### API Key Header Format

All requests use:
```
X-Api-Key: YOUR_API_KEY
```

Full headers for every request:
```python
headers = {
    "X-Api-Key": os.environ["HEYGEN_API_KEY"],
    "Content-Type": "application/json",
    "Accept": "application/json"
}
```

### Where to Get the API Key

- Dashboard: **Settings → API** in your HeyGen account
- The key is a single string; no Bearer prefix, no OAuth flow for standard API use
- OAuth 2.0 is available separately for building apps where end-users connect their own HeyGen accounts (not needed for your pipeline)

---

## 5. Python SDK / Integration Pattern

### Official SDK

There is **no official `heygen` pip package** for video generation. HeyGen provides:
- `heygen-streaming-sdk` (pip installable) — for **LiveAvatar/Streaming** use cases only, not video generation
- `StreamingAvatarSDK` on GitHub — JavaScript/TypeScript only

### Recommended Integration Pattern: Direct HTTP with `requests`

HeyGen's own quickstart guides demonstrate plain `requests` calls. This is the recommended approach for video generation:

```python
import os
import time
import requests

HEYGEN_API_KEY = os.environ["HEYGEN_API_KEY"]
BASE_URL = "https://api.heygen.com"

HEADERS = {
    "X-Api-Key": HEYGEN_API_KEY,
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def generate_avatar_iv_video(
    image_key: str,
    script: str,
    voice_id: str,
    title: str = "AI Tech Short",
    motion_prompt: str = "",
) -> str:
    """Submit Avatar IV video generation job. Returns video_id."""
    payload = {
        "image_key": image_key,
        "video_title": title,
        "script": script,
        "voice_id": voice_id,
    }
    if motion_prompt:
        payload["custom_motion_prompt"] = motion_prompt
        payload["enhance_custom_motion_prompt"] = True

    resp = requests.post(
        f"{BASE_URL}/v2/video/av4/generate",
        headers=HEADERS,
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()["data"]["video_id"]


def generate_video_with_audio(
    avatar_id: str,
    audio_url: str,
    title: str = "AI Tech Short",
    width: int = 1080,
    height: int = 1920,
) -> str:
    """Submit video generation with pre-generated audio (ElevenLabs). Returns video_id."""
    payload = {
        "title": title,
        "dimension": {"width": width, "height": height},
        "video_inputs": [
            {
                "character": {
                    "type": "avatar",
                    "avatar_id": avatar_id,
                    "avatar_style": "normal",
                },
                "voice": {
                    "type": "audio",
                    "audio_url": audio_url,
                },
            }
        ],
    }
    resp = requests.post(
        f"{BASE_URL}/v2/video/generate",
        headers=HEADERS,
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()["data"]["video_id"]


def poll_video_status(video_id: str, poll_interval: int = 30, timeout: int = 3600) -> dict:
    """Poll until video is completed or failed. Returns final status dict."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(
            f"{BASE_URL}/v1/video_status.get",
            headers=HEADERS,
            params={"video_id": video_id},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        status = data["status"]
        if status == "completed":
            return data  # data["video_url"] contains the download link
        if status == "failed":
            raise RuntimeError(f"HeyGen video failed: {data.get('error')}")
        time.sleep(poll_interval)
    raise TimeoutError(f"Video {video_id} did not complete within {timeout}s")


def upload_asset(file_path: str) -> str:
    """Upload a local file (photo or audio) to HeyGen. Returns asset key."""
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/v1/asset",
            headers={"X-Api-Key": HEYGEN_API_KEY},  # no Content-Type; multipart
            files={"file": f},
        )
    resp.raise_for_status()
    return resp.json()["data"]["key"]


def create_digital_twin(
    training_footage_url: str,
    consent_video_url: str,
    avatar_name: str,
) -> str:
    """Submit Digital Twin creation. Returns avatar_id."""
    payload = {
        "training_footage_url": training_footage_url,
        "video_consent_url": consent_video_url,
        "avatar_name": avatar_name,
    }
    resp = requests.post(
        f"{BASE_URL}/v2/video_avatar/submit",
        headers=HEADERS,
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()["data"]["avatar_id"]
```

---

## 6. Pricing and Credits at Scale

### Credit System (as of early 2026)

- **Avatar IV consumes 1 credit per second of generated video output**
  - 45-second video = 45 credits
  - 60-second video = 60 credits
- Standard avatar generation (non-Avatar IV): 1 credit per minute (much cheaper)
- No free API credits as of February 2026

### API Plans

| Plan | Price/mo | Credits Included | Avatar IV Minutes | Concurrency | Notes |
|------|----------|-----------------|-------------------|-------------|-------|
| Pay-as-you-go | from $5 | Top-up only | varies | standard | Credits valid 12 months |
| Pro API | $99 | 100 credits | ~1.7 min | 3 concurrent | Priority queue first 100 videos |
| Scale API | $330 | 660 credits | ~11 min | 3 concurrent | Includes Video Translation API |
| Enterprise | Custom | Custom | Custom | Custom | 4K, custom concurrency, custom rates |

Note: API plans are **separate** from HeyGen's consumer subscription plans (Creator $29, Pro $99, Business $149). You need an API plan specifically for programmatic access.

### Cost for 60–90 Videos of 45 Seconds Each (Monthly)

At 1 credit/second:
- 45 seconds × 75 videos (avg) = **3,375 credits/month**

At pay-as-you-go pricing (approximately $0.50–$1.00 per credit based on pack size), this runs **$1,700–$3,375/month** at retail — which is prohibitively expensive for your use case.

**Practical path to cost control:**
1. **Use your own AI avatar (Digital Twin) + ElevenLabs audio** — the credit cost structure may differ for Digital Twin vs. Photo Avatar IV. Verify with HeyGen.
2. **Consider EchoMimic V3 (self-hosted)** as the primary engine for shorts — already validated in your spike doc — and reserve HeyGen only for hero content or when quality delta justifies cost.
3. **Enterprise negotiation:** At 60–90 videos/month HeyGen sales will engage. Custom per-second rates are negotiable at this volume.
4. **Hybrid:** Use HeyGen for 1–2 high-quality pieces/week; use EchoMimic/ComfyUI for the remaining daily shorts.

---

## 7. Limitations and Content Policy

### Content Policy

- **Real individuals without consent are prohibited.** Creating an avatar of any celebrity, public figure, or real person requires documented explicit consent from that person.
- **News impersonation is a gray area.** Faceless AI avatar tech news (your @commoncreed strategy) is generally fine as long as you are not cloning/impersonating a real person's likeness.
- Prohibited content: violence, hate speech, sexually explicit material, content depicting children, spam, IP infringement.
- HeyGen will remove content and potentially ban accounts for violations.

### Key Technical Limitations

1. **Maximum video length:** 3 minutes (180 seconds) for Avatar IV — not an issue for shorts.
2. **Portrait rendering via API:** Known bug/limitation where `/v2/video/generate` pads portrait videos with black bars instead of rendering natively in portrait. The dedicated Avatar IV endpoint may behave differently — test required.
3. **1080p ceiling on API plans:** 4K requires Enterprise.
4. **No official Python SDK** for video generation — must use raw HTTP.
5. **Credit expiration:** Pro plan credits expire in 30 days; pay-as-you-go credits expire in 12 months.
6. **Concurrency cap:** 3 simultaneous renders on standard API plans.
7. **ElevenLabs integration via URL only:** Cannot pass an ElevenLabs voice ID directly to HeyGen's API from outside; must pre-generate audio and supply a public URL.

---

## 8. Pipeline Integration Recommendation

Given your existing `VoiceGenerator` (ElevenLabs) and `ComfyUIClient`, the cleanest integration is:

```
ElevenLabs (VoiceGenerator) → MP3 → Upload to S3/GCS → audio_url
                                                              ↓
                                         POST /v2/video/generate (avatar_id + audio_url)
                                                              ↓
                                         Poll /v1/video_status.get until completed
                                                              ↓
                                         Download video_url → output/video/
                                                              ↓
                                         SocialPoster.post_tiktok / post_instagram_reel
```

This avoids HeyGen's internal TTS entirely, preserves your ElevenLabs voice consistency, and uses the lip-sync capability cleanly.

Add a `HeyGenClient` class to `scripts/video_gen/` following the same pattern as `ComfyUIClient`. Use `audio_url` from an S3 presigned URL or public bucket.

---

## Sources

- [Create Avatar IV Video — HeyGen API Reference](https://docs.heygen.com/reference/create-avatar-iv-video)
- [New Avatar IV Endpoints Changelog](https://docs.heygen.com/changelog/new-avatar-iv-endpoints-create-avatar-iv-video)
- [Avatar IV Support in Create Avatar Video API](https://docs.heygen.com/changelog/avatar-iv-support-now-available-in-create-avatar-video-api)
- [HeyGen Avatar IV Complete Guide](https://help.heygen.com/en/articles/11269603-heygen-avatar-iv-complete-guide)
- [Create Digital Twin — API Reference](https://docs.heygen.com/reference/submit-video-avatar-creation-request)
- [Digital Twin — HeyGen Docs](https://docs.heygen.com/docs/video-avatars-api)
- [v2 Photo Avatar Endpoints](https://docs.heygen.com/docs/v2-photo-avatar-endpoints-generation-training-and-looks)
- [Create and Train Photo Avatar Groups](https://docs.heygen.com/docs/create-and-train-photo-avatar-groups)
- [Using Audio Files as Voice](https://docs.heygen.com/docs/using-audio-source-as-voice)
- [Get Video Status/Details](https://docs.heygen.com/reference/video-status)
- [API Limits and Usage Guidelines](https://docs.heygen.com/reference/limits)
- [API Key / Authentication](https://docs.heygen.com/docs/api-key)
- [Quick Start Guide](https://docs.heygen.com/docs/quick-start)
- [HeyGen API Pricing Page](https://www.heygen.com/api-pricing)
- [HeyGen API Pricing Explained (Help Center)](https://help.heygen.com/en/articles/10060327-heygen-api-pricing-explained)
- [HeyGen Video Processing Times](https://help.heygen.com/en/articles/9655503-heygen-video-processing-times)
- [HeyGen Content Moderation Policy](https://www.heygen.com/moderation-policy)
- [Portrait Video API Limitation Discussion](https://docs.heygen.com/discuss/67b49dc0faf6ad00317a3d28)
- [HeyGen Pricing 2026 — Merlio](https://merlio.app/blog/heygen-pricing-breakdown)
- [Digital Twin FAQ](https://help.heygen.com/en/articles/9380615-digital-twin-video-avatar-faq)
