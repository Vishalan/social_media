# CommonCreed Pipeline — Complete Documentation

> **Goal:** Produce 2–3 vertical AI news shorts per day, post automatically to Instagram Reels,
> TikTok, and YouTube Shorts, with owner review via Telegram before every post.

---

## Table of Contents

1. [How It Works — Plain English](#1-how-it-works--plain-english)
2. [Architecture Overview](#2-architecture-overview)
3. [Phase-by-Phase Walkthrough](#3-phase-by-phase-walkthrough)
4. [Module Reference](#4-module-reference)
5. [Data Flow & VideoJob](#5-data-flow--videojob)
6. [B-Roll System Deep Dive](#6-b-roll-system-deep-dive)
7. [Avatar Generation](#7-avatar-generation)
8. [Video Assembly](#8-video-assembly)
9. [Approval & Posting](#9-approval--posting)
10. [GPU Cost Optimization](#10-gpu-cost-optimization)
11. [Configuration Reference](#11-configuration-reference)
12. [Running the Pipeline](#12-running-the-pipeline)
13. [Failure Modes & Recovery](#13-failure-modes--recovery)

---

## 1. How It Works — Plain English

Every day at 8am the pipeline:

1. **Reads the news** — pulls the top 3 AI & Technology headlines from Google News RSS and Hacker News
2. **Writes a script** — sends each headline to Claude, gets back a hook, 30–60s narration, description, and hashtags
3. **Records the voiceover** — sends the script text to ElevenLabs, gets back an MP3 in your chosen voice
4. **Generates the avatar** — uploads the audio to Ayrshare (gives it a public URL), sends that URL to Kling AI, which lip-syncs your portrait photo to the narration and returns a 9:16 video of "you" talking
5. **Generates b-roll** — Claude picks the best b-roll type for each topic (browser scroll, image slideshow, code walkthrough, stats card), generates it without spending any GPU; only falls back to GPU AI video if everything else fails
6. **Assembles the final video** — stitches avatar + b-roll into a 9:16 short: first 3s full-screen avatar (hook), middle section split with b-roll on top and avatar on bottom, last 3s full-screen avatar (CTA); burns word-level captions
7. **Sends it to your Telegram** — you receive the video with Approve / Reject buttons; auto-rejects if you don't respond within 4 hours
8. **Posts on approval** — instantly uploads to Instagram Reels, TikTok, and YouTube Shorts via Ayrshare

---

## 2. Architecture Overview

```
scripts/
├── commoncreed_pipeline.py     ← Master orchestrator (run this)
│
├── news_sourcing/              ← Where topics come from
├── content_gen/                ← Script writing (Claude / GPT)
├── voiceover/                  ← Audio generation (ElevenLabs)
│
├── broll_gen/                  ← B-roll system (5 types)
│   ├── selector.py             ←   Claude picks the right type
│   ├── browser_visit.py        ←   Live website scroll
│   ├── image_montage.py        ←   Photo slideshow (Ken Burns)
│   ├── code_walkthrough.py     ←   Syntax-highlighted code reveal
│   ├── stats_card.py           ←   Data/numbers card
│   ├── ai_video.py             ←   GPU AI video (last resort)
│   └── factory.py              ←   Instantiates the right generator
│
├── avatar_gen/                 ← Your face talking (Kling / HeyGen)
├── video_edit/                 ← Final assembly (MoviePy + FFmpeg)
├── approval/                   ← Telegram bot (approve/reject)
├── posting/                    ← Ayrshare multi-platform posting
├── analytics/                  ← SQLite metrics & revenue estimates
└── gpu/                        ← RunPod pod lifecycle
```

### Technology Stack

| Layer | Technology |
|---|---|
| Orchestration | Python asyncio |
| Script writing | Anthropic Claude Sonnet 4.5 |
| B-roll intelligence | Claude Haiku 4.5 (cheap, fast) |
| Voice | ElevenLabs (`eleven_multilingual_v2`) |
| Avatar / lip-sync | Kling AI v2 Pro via fal.ai |
| B-roll (CPU) | Playwright, Pexels API, Pygments, PIL, FFmpeg |
| B-roll (GPU fallback) | ComfyUI + Wan2.1 on RunPod |
| Video assembly | MoviePy 2.x + FFmpeg |
| Captions | faster-whisper (word-level timestamps) |
| Approval | python-telegram-bot |
| Posting | Ayrshare API |
| Analytics | SQLite |
| Scheduling | macOS LaunchAgent (daily 08:00) |

---

## 3. Phase-by-Phase Walkthrough

The pipeline runs in three sequential phases. Phases 1 and 3 are CPU-only (no GPU cost). Phase 2 only starts a GPU pod if Phase 1 couldn't generate b-roll.

```
┌─────────────────────────────────────────────────────────┐
│  PHASE 1  — CPU + Cloud APIs  (pod is OFF)              │
│                                                          │
│  For each topic (runs sequentially):                    │
│    1. Fetch script  ──► Claude Sonnet                   │
│    2. Generate voice ──► ElevenLabs                     │
│    3. Upload audio  ──► Ayrshare (public URL)           │
│    4. Generate avatar ──► Kling/fal.ai                  │
│    5. Select b-roll type ──► Claude Haiku               │
│    6. Generate b-roll ──► CPU generators                │
│       (browser_visit → image_montage → code_walkthrough │
│        → stats_card; stops at first success)            │
│                                                          │
│  Output: list of VideoJob objects                        │
└─────────────────────────┬───────────────────────────────┘
                           │
         ┌─────────────────▼──────────────────┐
         │  Any job needs GPU b-roll?          │
         │  (all CPU types failed)             │
         └──────┬────────────────┬────────────┘
               YES               NO
                │                 │
  ┌─────────────▼──────┐    ┌────▼────────────────────┐
  │  PHASE 2  — GPU    │    │  Phase 2 SKIPPED         │
  │                    │    │  GPU pod never starts    │
  │  Start RunPod pod  │    │  $0 GPU cost today       │
  │  Run ai_video for  │    └────────────┬────────────┘
  │  flagged jobs only │                  │
  │  Stop pod          │                  │
  └─────────┬──────────┘                  │
            └──────────────┬──────────────┘
                            │
┌───────────────────────────▼─────────────────────────────┐
│  PHASE 3  — CPU  (pod is OFF)                            │
│                                                          │
│  For each job with b-roll:                              │
│    1. Transcribe audio ──► faster-whisper               │
│    2. Trim silence ──► FFmpeg concat                    │
│    3. Assemble video ──► MoviePy + FFmpeg drawtext      │
│    4. Send to Telegram ──► Approve / Reject             │
│    5. On approval: post ──► Instagram, TikTok, YouTube  │
│    6. Log to SQLite                                      │
└─────────────────────────────────────────────────────────┘
```

---

## 4. Module Reference

### `CommonCreedPipeline` — `commoncreed_pipeline.py`

The top-level class. Instantiate it with config and call `run_daily()`.

```python
pipeline = CommonCreedPipeline(config)
await pipeline.run_daily()
```

**Internal methods:**

| Method | Phase | What it does |
|---|---|---|
| `run_daily()` | — | Fetches topics, runs all 3 phases |
| `_phase1_generate(topics)` | 1 | Script → voice → avatar → b-roll for each topic |
| `_generate_script_voice_avatar(topic)` | 1 | Script, voice, upload audio, generate avatar |
| `_run_cpu_broll(job, duration)` | 1 | Try CPU b-roll types until one succeeds |
| `_phase2_broll(jobs)` | 2 | Start pod if needed, generate GPU b-roll |
| `_phase2_with_pod(jobs)` | 2 | RunPod context manager wrapper |
| `_phase2_broll_jobs(jobs)` | 2 | AiVideoGenerator per flagged job (C4 guard) |
| `_phase3_finalize(jobs)` | 3 | Transcribe → assemble → approve → post |
| `_finalize_job(job)` | 3 | Single job: trim → assemble → Telegram → post |
| `_assemble(job, avatar_path, filename)` | 3 | VideoEditor wrapper |
| `_transcribe(audio_path)` | 3 | faster-whisper word timestamps |
| `_generate_avatar(audio_url, topic)` | 1 | Avatar client call with one auto-retry |
| `_select_affiliates()` | 1 | Load 3 affiliate links from settings.py |

---

### `NewsSourcer` — `news_sourcing/news_sourcer.py`

Fetches tech news headlines and deduplicates against the last 7 days.

```python
sourcer = NewsSourcer(tracker=tracker, telegram_bot=bot, max_topics=3)
topics = sourcer.fetch()
# topics = [{"title": "...", "url": "...", "summary": "...", "source": "google_news"}, ...]
```

**Sources (in priority order):**
1. Google News Tech RSS — `news.google.com/rss/topics/CAAq...`
2. Hacker News top stories API — `hacker-news.firebaseio.com/v0/topstories.json`

**Deduplication:** Checks `analytics.news_items` table; skips any URL or normalized title seen in the last 7 days.

**Raises:** `InsufficientTopicsError` if fewer than 2 unique topics are found.

---

### `ScriptGenerator` — `content_gen/script_generator.py`

Writes video scripts using Claude or GPT.

```python
gen = ScriptGenerator(api_provider="anthropic", api_key=key, output_dir="output/scripts")
script = gen.generate_short_form(topic["title"], niche="AI & Technology")
```

**Returns:**
```json
{
  "title": "...",
  "hook": "So Claude just crashed my entire system...",
  "script": "Full narration text...",
  "description": "Instagram/YouTube caption...",
  "tags": ["ai", "tech", "coding"],
  "visual_cues": "code, terminal, error messages",
  "generated_at": "2026-04-01T00:37:43",
  "api_provider": "anthropic"
}
```

**Models:** `claude-sonnet-4-5` (Anthropic) or `gpt-4o-mini` (OpenAI)

---

### `VoiceGenerator` — `voiceover/voice_generator.py`

Converts script text to MP3 via ElevenLabs.

```python
gen = VoiceGenerator(api_key=key)
path = gen.generate(text, "output/audio/clip.mp3", voice_id="onwK4e9ZLuTAKqWW03F9")
```

**Key behaviours:**
- Splits long scripts into ≤5000-character chunks at sentence boundaries
- Retries on `HTTP 429` (rate limit) with exponential backoff — **does not retry on 4xx client errors**
- Concatenates audio chunks into a single MP3
- Model: `eleven_multilingual_v2` (works on free plan with premade voices)

**Free plan constraint:** Only premade voices work (category = `premade`). Community/professional voices require a paid plan.

---

### `AnalyticsTracker` — `analytics/tracker.py`

SQLite-backed metrics store.

```python
tracker = AnalyticsTracker(db_path="output/analytics.db")
tracker.log_post(platform="instagram", post_id="...", title="...", description="...")
tracker.get_report(period="week")  # dict with per-platform aggregates
```

**Tables:** `posts`, `metrics`, `revenue`, `news_items`

Used by `NewsSourcer` for topic deduplication and by `CommonCreedPipeline` to log every post.

---

## 5. Data Flow & VideoJob

Every topic that enters the pipeline becomes a `VideoJob`. All downstream modules read from and write to this object.

```python
@dataclass
class VideoJob:
    topic: dict              # {title, url, summary, source}
    script: dict             # {hook, script, description, tags, visual_cues}
    trimmed_audio_path: str  # local MP3 path
    avatar_path: str         # local MP4 path (9:16 avatar video)
    audio_url: str           # Ayrshare-hosted public URL (for Kling)
    broll_path: str          # local MP4 path (b-roll clip)
    caption_segments: list   # [{word, start, end}, ...] from faster-whisper
    affiliate_links: list    # up to 3 URLs from config/settings.py
    broll_only: bool         # True if avatar generation failed completely
    broll_type: str          # which generator won: "browser_visit", "image_montage", etc.
    needs_gpu_broll: bool    # True if all CPU b-roll generators failed
```

**State transitions:**

```
topic dict
    │  ScriptGenerator
    ▼
script dict
    │  VoiceGenerator
    ▼
trimmed_audio_path (MP3)
    │  SocialPoster.upload_media
    ▼
audio_url (public URL)
    │  KlingAvatarClient / HeyGenAvatarClient
    ▼
avatar_path (MP4, 9:16)
    │  BrollSelector + CPU generators
    ▼
broll_path (MP4, 1080×540)
    │  VideoEditor.trim_silence + faster-whisper
    ▼
caption_segments + trimmed audio
    │  VideoEditor.assemble
    ▼
final_video (MP4, 1080×1920)
    │  TelegramApprovalBot
    ▼
"approve" or "reject"
    │  SocialPoster.post_all_short_form
    ▼
posted to Instagram + TikTok + YouTube
```

---

## 6. B-Roll System Deep Dive

The b-roll system is the most complex part of the pipeline. It uses a two-phase CPU-first architecture to minimize GPU spend.

### Type Selection (BrollSelector)

Before generating anything, Claude Haiku reads the topic title, article URL, and script narration and selects the best visual treatment. It returns `[primary_type, fallback_type]`.

Selection logic:
- **`browser_visit`** — topic has an accessible article URL (not YouTube/Twitter/paywalled)
- **`code_walkthrough`** — topic involves an API, SDK, model release, or code example
- **`stats_card`** — topic has numbers, benchmarks, speeds, or costs to show
- **`image_montage`** — general tech news, product releases, announcements
- **`ai_video`** — abstract/speculative content with no concrete visual hook

The response is constrained via JSON schema (`output_config.format`) so Claude can only return valid enum values — no parsing errors possible.

If the selector fails (API error, etc.), it falls back to `["image_montage", "ai_video"]` which works for any topic.

### Generator Waterfall (CPU → GPU)

```
BrollSelector picks [primary, fallback]
        │
        ▼ try primary (e.g. browser_visit)
     success? ──YES──► done, broll_path set
        │ NO
        ▼ try fallback (e.g. image_montage)
     success? ──YES──► done, broll_path set
        │ NO
        ▼ needs_gpu_broll = True
        (Phase 2 will handle with ComfyUI)
```

### The Five Generator Types

#### 1. `browser_visit` — Live Website Scroll

Playwright opens the article URL in a headless browser, takes a full-page screenshot, then FFmpeg animates a smooth downward scroll.

```
Playwright headless → full-page PNG
    → paywall check (< 200 words = skip)
    → crop to 3× viewport height
    → FFmpeg: scale=1080:-1, crop=1080:540:0:'(ih-540)*t/duration'
```

Best for: news articles, blog posts, documentation pages.

#### 2. `image_montage` — Ken Burns Photo Slideshow

Fetches up to 6 landscape images from three sources in priority order, downloads them, and assembles an animated slideshow.

```
Pexels API (PEXELS_API_KEY) → up to 6 landscape photos
    │ if < 6 images
    ▼
Bing Image Search (BING_SEARCH_API_KEY) → up to 6 wide images
    │ if still < needed
    ▼
OG image from article HTML (og:image, twitter:image meta tags)
    │
    ▼ FFmpeg Ken Burns:
    zoompan=z='zoom+0.001':d={fps×per_clip}:s=1920x1080
    + setpts=PTS-STARTPTS  ← CRITICAL: resets timestamps before xfade
    + xfade=transition=fade:duration=0.5
```

Critical detail: `setpts=PTS-STARTPTS` must appear after `zoompan`. Without it, cross-fades produce black frames.

#### 3. `code_walkthrough` — Syntax-Highlighted Code Reveal

Claude Haiku generates a relevant 10–20 line Python snippet, Pygments renders each progressive "reveal" (lines 1..n) as PNG frames, and FFmpeg assembles them with the concat demuxer.

```
Claude Haiku → Python snippet (10-20 lines)
    │
    ▼ Pygments renders N frames:
    frame_0 = first line only
    frame_1 = first 2 lines
    ...
    frame_N = all lines (full code)
    │
    ▼ FFmpeg concat demuxer:
    file 'frame_00.png'
    duration 0.800
    ...
    file 'frame_NN.png'   ← last frame repeated with duration 0.001
    duration 0.001        ← prevents FFmpeg dropping the final frame
```

Best for: API releases, model announcements, "how to" topics.

#### 4. `stats_card` — Data Card Reveal

Claude Haiku extracts 2–5 key statistics from the script (via JSON schema), PIL renders each stat being added one-by-one to a branded dark card, FFmpeg assembles the frames.

```
Claude Haiku + json_schema → [{value: "400×", label: "faster than parallel"}, ...]
    │
    ▼ PIL renders N frames (dark navy bg, indigo accent):
    frame_0 = card with 1 stat
    frame_1 = card with 2 stats
    ...
    │
    ▼ FFmpeg concat → final clip
```

Brand colours: background `(18, 18, 25)`, accent `(99, 102, 241)`, value text 72pt bold white, label 28pt grey.

Best for: benchmark results, cost comparisons, speed improvements.

#### 5. `ai_video` — ComfyUI GPU Video (Phase 2 only)

Uses the existing ComfyUI/Wan2.1 workflow on a RunPod GPU pod. Only runs when all CPU generators fail for a given topic. The visual prompt is taken from `script["visual_cues"]` or the topic title.

---

## 7. Avatar Generation

The pipeline supports two avatar providers. Switch with `AVATAR_PROVIDER` in `.env`.

### Kling AI v2 Pro via fal.ai (default, recommended)

**Cost:** ~$388/month subscription at fal.ai
**Quality:** 8/10 — native 9:16 output, no crop needed
**Latency:** ~3–5 minutes per video

```
POST https://queue.fal.run/fal-ai/kling-video/v2/pro/ai-avatar
Body: { image_url, audio_url, aspect_ratio: "9:16" }
    │
    ▼ returns request_id + status_url
    │
    ▼ poll status_url every 10s (15 min timeout)
    │
    ▼ status == "COMPLETED"
    │ extract response.output.video.url
    ▼
stream download → local MP4
```

The `audio_url` must be a publicly accessible URL — this is why the pipeline uploads the MP3 to Ayrshare first before calling Kling.

**Auto-retry:** The pipeline automatically retries once on `AvatarQualityError` (uses a different output filename for the retry).

### HeyGen Avatar IV (alternative, premium)

**Cost:** ~$775+/month (Pro plan required for priority queue; standard queue = 24–36h wait)
**Quality:** 9/10 — outputs 1920×1080 landscape, VideoEditor crops to 9:16
**Latency:** ~5–10 minutes (Pro), 24–36h (standard)

Set `AVATAR_PROVIDER=heygen` and provide `HEYGEN_API_KEY` + `HEYGEN_AVATAR_ID` in `.env`. Run `scripts/avatar_gen/setup_heygen_avatar.py` once to create the Instant Avatar.

---

## 8. Video Assembly

`VideoEditor.assemble()` produces the final 1080×1920 (9:16) short.

### Layout

```
 ┌──────────────────┐
 │                  │  0s to 3s:
 │    FULL-SCREEN   │  Hook — full avatar, captures attention
 │      AVATAR      │
 │                  │
 │                  │
 └──────────────────┘

 ┌──────────────────┐
 │                  │  3s to (total - 3s):
 │     B-ROLL       │  Body — b-roll top half keeps viewer engaged
 │                  │         while avatar continues narrating
 ├──────────────────┤
 │                  │
 │     AVATAR       │
 │                  │
 └──────────────────┘

 ┌──────────────────┐
 │                  │  Last 3s:
 │    FULL-SCREEN   │  CTA — full avatar back for call-to-action
 │      AVATAR      │
 │                  │
 │                  │
 └──────────────────┘
```

### Caption Burning

After MoviePy assembles the video, captions are burned in via FFmpeg `drawtext` filter. Each word from `faster-whisper`'s word-level transcript appears and disappears at its exact timestamp.

```
drawtext=fontsize=64:fontcolor=white:borderw=3:bordercolor=black
        :x=(w-text_w)/2:y=h*0.75
        :text='AI':enable='between(t,1.200,1.450)'
```

If `faster-whisper` is not installed, captions are silently skipped and the video is still assembled.

### HeyGen Crop

HeyGen outputs 1920×1080 (landscape). `VideoEditor` detects this with `crop_to_portrait=True` and center-crops a 9:16 strip before compositing:

```python
crop_w = int(src_h * 9 / 16)   # = 607px
x1 = (src_w - crop_w) // 2     # centered
```

Kling outputs native 9:16, so no crop is needed.

---

## 9. Approval & Posting

### Telegram Approval

After assembly, the pipeline sends the video to the owner via Telegram with two inline buttons.

```
┌─────────────────────────────────┐
│ [Review] Topic Title            │
│                                  │
│ Instagram caption here...        │
│                                  │
│  [✓ Approve]  [✗ Reject]        │
└─────────────────────────────────┘
```

- **Approve** → immediately posts to all platforms
- **Reject** → skips this video, logs the decision
- **No response in 4 hours** → auto-rejects with a follow-up notification

Security: callbacks from any Telegram user ID other than `TELEGRAM_OWNER_USER_ID` are silently ignored.

### Social Posting

`SocialPoster.post_all_short_form()` fans out to three platforms simultaneously via Ayrshare.

```
final_video.mp4
    │
    ├──► Instagram Reels
    ├──► TikTok
    └──► YouTube Shorts
```

The caption includes:
- Script description
- Up to 3 affiliate links (from `config/settings.py` AFFILIATES dict)
- Platform-specific AI disclosure
- Hashtags from the script

---

## 10. GPU Cost Optimization

The pipeline is designed to spend $0 on GPU on most days.

### Phase Gate

```python
gpu_jobs = [j for j in jobs if j.needs_gpu_broll]
if not gpu_jobs:
    logger.info("Phase 2 skipped — GPU pod NOT started.")
    return
```

The RunPod pod **only starts** if at least one job has `needs_gpu_broll=True`, meaning all four CPU generators failed for that topic.

### Network Volume

The pod attaches `RUNPOD_NETWORK_VOLUME_ID`, a persistent 50GB volume that caches:
- ComfyUI installation
- Wan2.1 model weights (~8GB)
- Any other models

When the pod stops, the volume is preserved. Next startup skips the 10–30 minute model download, cutting latency to ~2 minutes for pod boot.

### Daily Cost Scenarios

| Scenario | GPU Pod | Est. Cost |
|---|---|---|
| All CPU b-roll succeeds (typical) | Never starts | $0.00 |
| 1 of 3 topics needs GPU b-roll | ~20 min | ~$0.23 |
| All 3 topics need GPU b-roll | ~40 min | ~$0.46 |

CPU-only API costs (Claude + ElevenLabs + Kling) run approximately $1.50–2.00/day for 3 topics.

---

## 11. Configuration Reference

All config lives in `.env` at the project root. The pipeline reads it via `python-dotenv`.

### Required

| Variable | Used By | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Script generation, b-roll (Haiku) | Must have credits |
| `ELEVENLABS_API_KEY` | Voiceover | Free plan: premade voices only |
| `ELEVENLABS_VOICE_ID` | Voiceover | Use a `premade` voice on free plan |
| `AYRSHARE_API_KEY` | Audio upload, social posting | Required for avatar generation too |
| `TELEGRAM_BOT_TOKEN` | Approval bot | From BotFather |
| `TELEGRAM_OWNER_USER_ID` | Approval bot | Your numeric Telegram ID |
| `FAL_API_KEY` | Kling avatar | From fal.ai dashboard |
| `KLING_AVATAR_IMAGE_URL` | Kling avatar | Public URL to your portrait JPG |

### Optional but Recommended

| Variable | Used By | Notes |
|---|---|---|
| `PEXELS_API_KEY` | image_montage | Free at pexels.com/api |
| `BING_SEARCH_API_KEY` | image_montage | Azure Cognitive Services |
| `RUNPOD_API_KEY` | GPU b-roll fallback | Only needed if CPU fails |
| `RUNPOD_NETWORK_VOLUME_ID` | GPU startup speed | Saves 10–30 min on pod boot |

### Avatar Provider Switch

```bash
# Default — Kling via fal.ai (~$388/month, 8/10 quality)
AVATAR_PROVIDER=kling
KLING_AVATAR_IMAGE_URL=https://...your-portrait.jpg
FAL_API_KEY=...

# Alternative — HeyGen (~$775+/month, 9/10 quality)
AVATAR_PROVIDER=heygen
HEYGEN_API_KEY=...
HEYGEN_AVATAR_ID=...  # from setup_heygen_avatar.py
```

### ElevenLabs Voice IDs (premade, free plan)

| Voice ID | Name | Style |
|---|---|---|
| `onwK4e9ZLuTAKqWW03F9` | Daniel | Steady broadcaster **(current)** |
| `TX3LPaxmHKxFdv7VOQHJ` | Liam | Energetic, social media creator |
| `IKne3meq5aSn9XLyUdCD` | Charlie | Deep, confident, energetic |
| `JBFqnCBsd6RMkjVDRZzb` | George | Warm, captivating storyteller |
| `EXAVITQu4vr4xnSDxMaL` | Sarah | Mature, reassuring, confident |

---

## 12. Running the Pipeline

### Manual Run

```bash
cd scripts/
python3 commoncreed_pipeline.py
```

Logs to stdout. Set `LOG_LEVEL=DEBUG` for verbose output.

### Automated Daily Run (macOS LaunchAgent)

```bash
# Install — runs at 08:00 every day
cp deploy/com.commoncreed.pipeline.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.commoncreed.pipeline.plist

# Trigger immediately (without waiting for 08:00)
launchctl start com.commoncreed.pipeline

# View logs
tail -f logs/pipeline_$(date +%Y-%m-%d).log

# Disable
launchctl unload ~/Library/LaunchAgents/com.commoncreed.pipeline.plist
```

### Smoke Test (verify all API keys before first run)

```bash
cd scripts/
python3 smoke_test.py
```

Runs 7 checks: news sourcing → script → b-roll selector → CPU b-roll → voiceover → avatar connectivity → Telegram. Exits 0 on full pass, 1 on any failure. Does not post anything or spend GPU.

### Skip GPU Entirely (local ComfyUI)

```bash
# In .env
COMFYUI_URL=http://localhost:8188
```

When `COMFYUI_URL` is set, the RunPod pod is never started. The pipeline uses the local ComfyUI instance for GPU b-roll if needed.

---

## 13. Failure Modes & Recovery

| Failure | Effect | Recovery |
|---|---|---|
| Anthropic credits empty | Script generation fails; uses fallback script stub | Top up at console.anthropic.com |
| ElevenLabs 401 | Voiceover fails; job skipped | Check API key and voice ID (must be premade on free plan) |
| Kling/fal.ai timeout | Avatar generation fails; `broll_only=True`; video assembled without avatar | Retry tomorrow; Telegram alert sent |
| All CPU b-roll fail | `needs_gpu_broll=True`; Phase 2 starts GPU pod | RunPod pod spins up automatically |
| RunPod pod startup fails | Phase 2 aborted; Telegram alert sent; job skipped | Check RUNPOD_API_KEY and GPU availability |
| Telegram bot not started | "Chat not found" error | Send `/start` to your bot once |
| Pexels/Bing keys missing | image_montage tries OG image fallback only | Add keys to .env for richer results |
| faster-whisper not installed | Captions disabled, silence trimming disabled | `pip install faster-whisper` |
| No topics found | `InsufficientTopicsError`; Telegram alert; pipeline stops | Check internet; wait for HN/Google to update |
| Owner rejects all videos | Nothing posted | Normal — try again tomorrow |
| Owner doesn't respond (4h) | Auto-reject; Telegram notification sent | Nothing — pipeline continues next run |

### Telegram Alerts

The pipeline sends a Telegram message for every significant failure:
- Topic script/voice failed → skips that topic
- B-roll failed → skips that topic
- Avatar failed → uses b-roll-only layout (no avatar)
- RunPod pod failed to start → aborts Phase 2
- Phase 3 assembly/post error → skips that topic

This means you can leave the pipeline running unattended and only get notified when something needs attention.
