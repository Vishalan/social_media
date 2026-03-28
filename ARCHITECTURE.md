# System Architecture

## High-Level Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                     CONTENT PIPELINE                            │
│                                                                 │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   │
│  │  Topic    │──▶│  Script  │──▶│  Voice   │──▶│  Video   │   │
│  │ Research  │   │   Gen    │   │   Gen    │   │   Gen    │   │
│  │          │   │          │   │          │   │          │   │
│  │ VidIQ    │   │ Claude/  │   │ Eleven   │   │ ComfyUI  │   │
│  │ Trends   │   │ GPT-4o   │   │ Labs     │   │ (Cloud)  │   │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘   │
│                                                     │          │
│                                              ┌──────▼──────┐   │
│                                              │   Editing   │   │
│                                              │ (CapCut/    │   │
│                                              │  MoviePy)   │   │
│                                              └──────┬──────┘   │
│                                                     │          │
│  ┌──────────────────────────────────────────────────▼──────┐   │
│  │              CROSS-PLATFORM POSTING                     │   │
│  │                                                         │   │
│  │  ┌────────┐ ┌───────┐ ┌─────────┐ ┌────────┐ ┌──────┐│   │
│  │  │YouTube │ │TikTok │ │Instagram│ │Facebook│ │  X   ││   │
│  │  │Long+   │ │       │ │Reels    │ │Reels   │ │      ││   │
│  │  │Shorts  │ │       │ │         │ │        │ │      ││   │
│  │  └────────┘ └───────┘ └─────────┘ └────────┘ └──────┘│   │
│  │                    via Ayrshare API                     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                              │                                  │
│                       ┌──────▼──────┐                          │
│                       │  Analytics  │                          │
│                       │  (SQLite)   │                          │
│                       └─────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
```

## Module Dependencies

```
pipeline.py (orchestrator + CLI)
├── content_gen/script_generator.py
│   └── anthropic / openai SDK
├── voiceover/voice_generator.py
│   └── elevenlabs SDK
├── video_gen/comfyui_client.py
│   └── requests + websockets → ComfyUI server
├── posting/social_poster.py
│   └── social-post-api (Ayrshare)
│   └── google-api-python-client (YouTube)
└── analytics/tracker.py
    └── sqlite3 (stdlib)
```

## GPU Cloud Architecture

```
┌──────────────────┐         ┌─────────────────────────┐
│   Your Machine   │  HTTP   │    GPU Cloud Instance    │
│                  │────────▶│                           │
│  pipeline.py     │         │  ComfyUI Server (:8188)  │
│  comfyui_client  │◀────────│                           │
│                  │  WS/HTTP│  Models:                  │
└──────────────────┘         │  ├── SDXL (thumbnails)    │
                             │  ├── Wan2.1 (video)       │
                             │  └── CogVideoX (b-roll)   │
                             │                           │
                             │  GPU: RTX 4090 / L40      │
                             │  Cost: $0.44-0.69/hr      │
                             └─────────────────────────────┘
```

## n8n Automation Flow

```
Cron (8 AM daily)
    │
    ▼
Fetch trending topics (HTTP → YouTube/Reddit API)
    │
    ▼
AI Script Generation (HTTP → Anthropic API)
    │
    ▼
ElevenLabs Voiceover (HTTP → ElevenLabs API)
    │
    ▼
[Optional] ComfyUI Video Gen (HTTP → GPU cloud)
    │
    ▼
Upload to YouTube (HTTP → YouTube Data API)
    │
    ▼
Cross-post clips (HTTP → Ayrshare API)
    │
    ▼
Log to Google Sheets / SQLite
    │
    ▼
Slack notification with results
```

## Data Flow

```
Topic idea
  → AI Script (JSON: title, hook, script, description, tags)
    → Voiceover MP3 (from script text)
      → Thumbnail PNG (from title prompt via SDXL)
      → B-roll clips MP4 (from script b-roll markers via CogVideoX/Wan2.1)
        → Assembled video MP4 (voiceover + b-roll + captions)
          → Posted to all platforms
            → Metrics tracked in SQLite
```

## Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| AI Writing | Claude (Anthropic) | Best long-form quality, good JSON output |
| Voice | ElevenLabs v2 | Most natural, good cloning, affordable |
| Image Gen | SDXL via ComfyUI | Open-source, customizable, LoRA support |
| Video Gen | Wan2.1 1.3B | Best quality/speed ratio at low VRAM |
| B-Roll | CogVideoX-5B | Good image-to-video, 6-sec clips |
| Posting | Ayrshare | Single API for all platforms |
| Analytics | SQLite | Zero config, good enough for this scale |
| Automation | n8n | Visual, self-hostable, good API integration |
| GPU Cloud | Vast.ai/RunPod | Cheapest for on-demand GPU |
| CLI | Click + Rich | Clean CLI with progress display |

## Scaling Path

```
Phase 1 (Month 1-3):   1 channel  → pipeline.py manual runs
Phase 2 (Month 3-6):   1 channel  → n8n automated daily
Phase 3 (Month 6-12):  2 channels → n8n + cron + GPU auto-scaling
Phase 4 (Month 12+):   3+ channels → dedicated GPU instance, VA team
```
