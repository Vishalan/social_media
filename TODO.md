# Project TODO — Current Status & Next Steps

## Immediate Priority (Do First)

- [ ] **Copy .env.example to .env and add API keys** — Nothing works without this
  - Anthropic key: console.anthropic.com
  - ElevenLabs key: elevenlabs.io/app/settings/api-keys
  - Ayrshare key: app.ayrshare.com (need $15/mo plan)
  - YouTube API key: console.cloud.google.com (enable YouTube Data API v3)
  - RunPod key: runpod.io/console/user/settings

- [ ] **Run niche analysis notebook** — Confirm niche with data before building content
  ```bash
  pip install -r requirements.txt
  jupyter notebook notebooks/01_niche_analysis.ipynb
  ```

- [ ] **Choose brand name** — Check availability on all platforms at namecheckr.com

## Setup Phase (Week 1)

- [ ] Create accounts on all 8 platforms with chosen brand name
- [ ] Design branding in Canva (logo, banners, thumbnail templates)
- [ ] Select/clone ElevenLabs voice and update config/settings.py `VOICE.voice_id`
- [ ] Update `config/settings.py` → `BRAND.name` and `BRAND.niche`
- [ ] Set up YouTube OAuth (client_secret.json in config/)
- [ ] Provision GPU cloud instance (Vast.ai or RunPod) and deploy ComfyUI
- [ ] Test each script module individually (see GETTING_STARTED.md Phase 6)

## Build Phase (Week 2-3)

- [ ] Integration test: run `python scripts/pipeline.py single --topic "test" --type short` end-to-end
- [ ] Set up n8n instance (local Docker or n8n.cloud) and import flows
- [ ] Create first batch of 5-6 long-form YouTube videos
- [ ] Extract 10-12 short-form clips from long-form content
- [ ] Design first set of thumbnails using ComfyUI or Canva
- [ ] Sign up for affiliate programs (ElevenLabs, Canva, VidIQ, Pictory, NordVPN, etc.)
- [ ] Create Linktree page with all social + affiliate links

## Code Improvements (Backlog)

- [ ] Add unit tests for all script modules
- [ ] Add `scripts/trend_research/` module — scrape trending topics from YouTube, Reddit, HN
- [ ] Add `scripts/seo/` module — automated title/description/tag optimization using VidIQ API
- [ ] Add video concatenation script — stitch b-roll clips + voiceover into final video
- [ ] Add subtitle/caption generator using Whisper
- [ ] Build a simple web dashboard for analytics (Flask/Streamlit)
- [ ] Add Telegram bot for mobile notifications when content is posted
- [ ] Create notebook `02_competitor_analysis.ipynb` — analyze top channels in niche
- [ ] Create notebook `03_content_calendar.ipynb` — generate and export monthly calendars
- [ ] Add LoRA training workflow for consistent visual style in ComfyUI
- [ ] Add video upscaling workflow (Real-ESRGAN) for improving AI-generated clips

## Content Milestones

- [ ] First video published
- [ ] 10 videos published
- [ ] 50 videos published
- [ ] 1,000 subscribers (YouTube Partner Program threshold)
- [ ] 4,000 watch hours (YouTube Partner Program threshold)
- [ ] First $100 earned
- [ ] First sponsorship deal
- [ ] $1,000/month
- [ ] Launch second channel
- [ ] $5,000/month target reached
