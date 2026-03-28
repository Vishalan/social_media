# Social Media Content Automation System

## Project Goal
Build a $5,000+/month income stream through automated AI-powered social media content creation across all major platforms (YouTube, TikTok, Instagram, Facebook, X, LinkedIn, Pinterest). The owner's current salary is $5,000+/month — the end goal is to match or exceed this.

## Strategy Summary
- **Model:** Faceless AI-generated content, "create once, distribute everywhere"
- **Primary revenue:** YouTube AdSense (long-form 8-15 min in high-CPM niche)
- **Growth engine:** Short-form clips cross-posted to TikTok/Reels/Shorts daily
- **Revenue stacking:** Ad revenue + affiliate marketing + sponsorships + digital products
- **Niche (pending final analysis):** AI & Technology (RPM $12-30) or Personal Finance (RPM $15-40)
- **Time target:** 5-10 hours/week once automation is running

## Project Structure

```
social_media/
├── CLAUDE.md                    # ← YOU ARE HERE — project context for Claude CLI
├── README.md                    # Project overview
├── .env.example                 # API keys template (copy to .env)
├── .gitignore
├── requirements.txt             # Python deps (root level)
│
├── config/
│   ├── __init__.py
│   └── settings.py              # Central config: niche data, schedules, API settings, affiliates
│
├── notebooks/
│   └── 01_niche_analysis.ipynb  # Jupyter: weighted niche scoring, charts, Google Trends
│
├── comfyui_workflows/
│   ├── thumbnail_generator.json # SDXL → 1280x720 YouTube thumbnails
│   ├── short_video_wan21.json   # Wan2.1 1.3B → 2-sec video clips (832x480)
│   └── broll_generator.json     # CogVideoX-5B → 6-sec b-roll from images (640x480)
│
├── n8n_flows/
│   ├── content_pipeline.json    # Daily automation: cron → AI script → voice → post → log
│   └── approval_workflow.json   # Review/approval flow with Slack notifications
│
├── scripts/                     # Python automation package (~3,500 lines)
│   ├── __init__.py
│   ├── pipeline.py              # Master orchestrator with Click CLI (548 lines)
│   ├── config.example.json      # Script-level config template
│   ├── content_gen/
│   │   ├── __init__.py
│   │   └── script_generator.py  # ScriptGenerator class: long-form, short-form, threads (310 lines)
│   ├── voiceover/
│   │   ├── __init__.py
│   │   └── voice_generator.py   # VoiceGenerator class: ElevenLabs with chunking/retry (341 lines)
│   ├── video_gen/
│   │   ├── __init__.py
│   │   └── comfyui_client.py    # ComfyUIClient class: workflow runner, WebSocket (461 lines)
│   ├── posting/
│   │   ├── __init__.py
│   │   └── social_poster.py     # SocialPoster class: multi-platform, Ayrshare + direct (481 lines)
│   ├── analytics/
│   │   ├── __init__.py
│   │   └── tracker.py           # AnalyticsTracker class: SQLite, reports, CSV export (510 lines)
│   └── *.md                     # Setup/quickstart/summary docs
│
├── deploy/
│   ├── gpu_cost_comparison.py   # GPU cloud pricing analysis script (266 lines)
│   ├── docker-compose.yml       # Local ComfyUI + n8n stack
│   ├── nginx.conf               # Reverse proxy config
│   ├── runpod/
│   │   ├── setup_comfyui.sh     # RunPod instance bootstrap
│   │   └── run_workflow.py      # RunPod serverless workflow runner (482 lines)
│   └── vastai/
│       └── setup.sh             # Vast.ai instance bootstrap
│
├── assets/                      # Brand assets (thumbnails, logos, templates)
│   ├── thumbnails/
│   ├── logos/
│   └── templates/
│
└── output/                      # Generated content (gitignored)
    ├── scripts/
    ├── audio/
    ├── video/
    └── thumbnails/
```

## Key Classes & CLI

### Pipeline CLI (`scripts/pipeline.py`)
```bash
cd scripts/
python pipeline.py daily                            # Run full daily pipeline
python pipeline.py single --topic "AI Tools" --type long  # Single video
python pipeline.py weekly                            # Batch a week's content
python pipeline.py report --period week              # Analytics report
```

### Core Classes
- `ScriptGenerator(api_provider, niche, output_dir)` — `.generate_long_form(topic)`, `.generate_short_form(topic)`, `.generate_twitter_thread(topic)`, `.suggest_topics(count)`
- `VoiceGenerator(api_key, voice_id)` — `.generate(text, output_path)`, `.list_voices()`, `.estimate_cost(text)`
- `ComfyUIClient(server_url)` — `.run_workflow(json, params)`, `.generate_thumbnail(prompt, path)`, `.generate_broll(image, prompt, path)`, `.generate_short_video(prompt, path)`
- `SocialPoster(ayrshare_key)` — `.post_youtube_video(...)`, `.post_tiktok(...)`, `.post_instagram_reel(...)`, `.post_twitter(...)`, `.post_all_short_form(...)`, `.schedule_post(...)`
- `AnalyticsTracker(db_path)` — `.log_post(...)`, `.update_metrics(...)`, `.get_report(period)`, `.top_performing(n)`, `.revenue_estimate(...)`

## External Dependencies & APIs
- **AI writing:** Anthropic (Claude) or OpenAI — set in .env
- **Voice:** ElevenLabs API — $5-22/month
- **Video/Image gen:** ComfyUI (self-hosted on GPU cloud) — models: SDXL, Wan2.1, CogVideoX-5B
- **Social posting:** Ayrshare API (multi-platform) — $15-25/month
- **YouTube upload:** Google YouTube Data API v3 (OAuth2)
- **GPU cloud:** RunPod (~$0.69/hr L40) or Vast.ai (~$0.44/hr RTX 4090)
- **Automation:** n8n (self-hosted or n8n.cloud)
- **Analytics:** SQLite (built-in, no server)

## Current Status
- [x] Project structure created (43 files)
- [x] All Python modules written with type hints, docstrings, error handling
- [x] ComfyUI workflows for thumbnails, short video, b-roll
- [x] n8n flows for daily pipeline and approval
- [x] GPU deploy scripts for RunPod and Vast.ai
- [x] Niche analysis notebook with weighted scoring model
- [x] Configuration system with .env + settings.py
- [ ] **API keys not yet configured** — need .env file
- [ ] **Niche not finalized** — run notebook to confirm
- [ ] **Brand name not chosen** — update config/settings.py
- [ ] **Social accounts not created** — need handles on all platforms
- [ ] **ElevenLabs voice not selected/cloned**
- [ ] **YouTube OAuth not configured** — need client_secret.json
- [ ] **Integration testing** — modules written but not tested end-to-end
- [ ] **n8n instance not deployed**
- [ ] **GPU cloud instance not provisioned**

## Important Conventions
- All config through `config/settings.py` and `.env` (never hardcode keys)
- Python 3.10+ required
- Scripts use `logging` module — check `automation.log`
- Output files go to `output/` (gitignored)
- ComfyUI workflows use placeholder strings like `{topic}` for param substitution
- All scripts support both Anthropic and OpenAI via `api_provider` param

## GPU Cloud Cost Reference (2026)
| Provider | GPU | $/hr | Best For |
|----------|-----|------|----------|
| Vast.ai | RTX 4090 | $0.44 | Budget video gen |
| RunPod | RTX 4090 | $0.69 | Reliable, good API |
| RunPod | L40 | $0.69 | Higher VRAM (48GB) |
| Lambda | A100 40GB | $1.10 | Heavy models (14B) |
| RunPod Serverless | Any | Pay-per-sec | Sporadic workloads |

## Revenue Model (target: $5,000+/month by month 12-18)
| Stream | Month 3-6 | Month 6-12 | Month 12+ |
|--------|-----------|------------|-----------|
| YouTube AdSense | $200-800 | $800-2,000 | $1,500-4,000 |
| Affiliate Marketing | $200-600 | $500-1,500 | $1,000-3,000 |
| Sponsorships | $200-500 | $500-2,000 | $1,000-4,000 |
| Short-Form Platforms | $50-200 | $200-500 | $300-800 |
| Digital Products | $50-200 | $200-800 | $500-2,000 |
