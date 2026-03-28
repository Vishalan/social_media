# Social Media Content Automation System

A complete, end-to-end system for building a $5,000+/month income stream through automated social media content creation across all major platforms.

## Project Structure

```
social_media/
├── config/
│   └── settings.py              # Central configuration (niche, APIs, schedule)
├── notebooks/
│   └── 01_niche_analysis.ipynb  # Data-driven niche selection with visualizations
├── comfyui_workflows/
│   ├── thumbnail_generator.json # SDXL YouTube thumbnail generation
│   ├── short_video_wan21.json   # Wan2.1 short video clip generation
│   └── broll_generator.json     # CogVideoX image-to-video b-roll
├── n8n_flows/
│   ├── content_pipeline.json    # Daily automated content pipeline
│   └── approval_workflow.json   # Content review & approval flow
├── scripts/
│   ├── content_gen/
│   │   └── script_generator.py  # AI script writing (Claude/GPT)
│   ├── voiceover/
│   │   └── voice_generator.py   # ElevenLabs voice generation
│   ├── video_gen/
│   │   └── comfyui_client.py    # ComfyUI API client
│   ├── posting/
│   │   └── social_poster.py     # Cross-platform posting
│   ├── analytics/
│   │   └── tracker.py           # SQLite performance tracking
│   └── pipeline.py              # Master orchestrator (CLI)
├── deploy/
│   ├── gpu_cost_comparison.py   # GPU cloud cost analysis
│   ├── runpod/
│   │   ├── setup_comfyui.sh     # RunPod ComfyUI setup
│   │   └── run_workflow.py      # RunPod workflow execution
│   ├── vastai/
│   │   └── setup.sh             # Vast.ai instance setup
│   └── docker-compose.yml       # Local Docker setup
├── .env.example                 # API keys template
├── .gitignore
└── requirements.txt             # Python dependencies
```

## Quick Start

1. Copy `.env.example` to `.env` and add your API keys
2. `pip install -r requirements.txt`
3. Edit `config/settings.py` with your brand name and niche
4. Run `jupyter notebook notebooks/01_niche_analysis.ipynb` to finalize your niche
5. Run `python scripts/pipeline.py daily` to start producing content

## GPU Cloud (for AI video generation)

Run `python deploy/gpu_cost_comparison.py` to see current pricing. Recommended: Vast.ai RTX 4090 (~$0.44/hr) for budget, RunPod L40 (~$0.69/hr) for reliability.

## n8n Automation

Import `n8n_flows/content_pipeline.json` into your n8n instance for fully automated daily content creation and cross-platform posting.

## Supported Platforms

YouTube, TikTok, Instagram, Facebook, X (Twitter), LinkedIn, Pinterest

## AI Models Used

- **Scripts:** Claude (Anthropic) or GPT-4o (OpenAI)
- **Voice:** ElevenLabs Multilingual v2
- **Thumbnails:** SDXL via ComfyUI
- **Short Videos:** Wan2.1 (1.3B or 14B) via ComfyUI
- **B-Roll:** CogVideoX-5B via ComfyUI
