# Social Media Content Pipeline - Setup Guide

Complete automation pipeline for generating, editing, and posting social media content.

## Overview

This pipeline orchestrates:
1. **Script Generation** - AI-powered content creation (Claude/GPT)
2. **Voice-Over** - ElevenLabs text-to-speech with auto-chunking
3. **Video Generation** - ComfyUI for thumbnails, B-roll, and full videos
4. **Social Posting** - Multi-platform publishing (YouTube, TikTok, Instagram, Twitter)
5. **Analytics** - Performance tracking and revenue estimation

## System Requirements

- Python 3.9+
- 4GB RAM minimum (8GB+ recommended)
- Internet connection for API calls
- Optional: Local ComfyUI instance or cloud access

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API Keys

Create a `.env` file in the scripts directory:

```bash
# LLM APIs
ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx

# Voice & Video
ELEVENLABS_API_KEY=xxx

# Social Media APIs
TIKTOK_API_TOKEN=xxx
INSTAGRAM_API_TOKEN=xxx
TWITTER_BEARER_TOKEN=xxx
AYRSHARE_API_KEY=xxx
```

Or set as environment variables:

```bash
export ANTHROPIC_API_KEY="your-key"
export ELEVENLABS_API_KEY="your-key"
# ... etc
```

### 3. Configure Pipeline

Copy and customize the configuration:

```bash
cp config.example.json config.json
# Edit config.json with your settings
```

Key configuration options:

```json
{
  "api": {
    "provider": "anthropic"  // or "openai"
  },
  "comfyui": {
    "server_url": "http://localhost:8188"  // Local ComfyUI instance
  },
  "daily": {
    "niches": ["Technology", "Marketing"],
    "topics_per_niche": 1,
    "post_platforms": ["tiktok", "twitter"]
  }
}
```

## Usage

### Generate a Single Video (End-to-End)

```bash
python pipeline.py single --topic "AI Tools for 2024" --niche "Digital Marketing"
```

Advanced options:

```bash
python pipeline.py single \
  --topic "AI Tools for 2024" \
  --niche "Digital Marketing" \
  --type short_form \
  --voice Rachel \
  --post tiktok --post twitter --post instagram \
  --api-provider anthropic
```

### Run Daily Pipeline

Generates one video per configured niche and posts automatically:

```bash
python pipeline.py daily
```

Customize daily config in `config.json`:

```json
{
  "daily": {
    "niches": ["Technology", "Digital Marketing"],
    "topics_per_niche": 1,
    "post_platforms": ["tiktok", "twitter", "instagram"]
  }
}
```

### Run Weekly Batch

Generate 2 videos per day for 5 days:

```bash
python pipeline.py weekly
```

Customize in config:

```json
{
  "weekly": {
    "videos_per_day": 2,
    "batch_mode": true
  }
}
```

### Generate Analytics Report

```bash
# Weekly report
python pipeline.py report --period week

# Monthly report
python pipeline.py report --period month

# All-time report
python pipeline.py report --period all
```

## Module Documentation

### 1. Script Generator (`content_gen/script_generator.py`)

Generates optimized scripts for different content types.

**Class:** `ScriptGenerator`

**Methods:**

```python
# Generate long-form script (10+ minutes)
script = generator.generate_long_form(
    topic="AI Tools for Content Creation",
    niche="Digital Creators",
    duration_min=10
)

# Generate short-form script (30-60 seconds)
script = generator.generate_short_form(
    topic="Quick Python Tips",
    niche="Developers"
)

# Generate Twitter thread
thread = generator.generate_twitter_thread(
    topic="The Future of AI",
    niche="Tech Enthusiasts",
    num_tweets=7
)

# Get trending topic suggestions
topics = generator.suggest_topics(
    niche="Digital Marketing",
    count=10
)
```

**Output Format:**

```json
{
  "title": "Video Title",
  "hook": "First 10 seconds of the video...",
  "script": "Full video script...",
  "description": "Video description for posting",
  "tags": ["tag1", "tag2", "tag3"],
  "generated_at": "2024-03-26T10:30:00",
  "api_provider": "anthropic"
}
```

### 2. Voice Generator (`voiceover/voice_generator.py`)

Generates voice-over audio with automatic script chunking.

**Class:** `VoiceGenerator`

**Methods:**

```python
# Generate voice-over
voice_gen = VoiceGenerator()

audio_path = voice_gen.generate(
    text="Your script here...",
    output_path="./voiceover.mp3",
    voice_name="Rachel",
    stability=0.7,
    similarity_boost=0.75
)

# List available voices
voices = voice_gen.list_voices()

# Estimate cost
cost = voice_gen.estimate_cost(text)
print(f"Estimated cost: ${cost['estimated_cost_usd']}")
```

**Features:**

- Automatic text chunking for long scripts
- Retry logic with exponential backoff
- Multiple voice options
- Cost estimation

### 3. ComfyUI Client (`video_gen/comfyui_client.py`)

API client for ComfyUI video/image generation.

**Class:** `ComfyUIClient`

**Methods:**

```python
client = ComfyUIClient(server_url="http://localhost:8188")

# Run a workflow
prompt_id = await client.run_workflow(
    workflow_json=workflow,
    params={"prompt": "a sunset over mountains"}
)

# Check status
status = await client.get_status(prompt_id)

# Download outputs
files = await client.download_output(
    prompt_id,
    output_dir="./outputs"
)

# Convenience methods
await client.generate_thumbnail(
    topic_prompt="AI Tools",
    output_path="./thumbnail.png"
)

await client.generate_short_video(
    prompt="AI automation demo",
    output_path="./video.mp4"
)
```

### 4. Social Poster (`posting/social_poster.py`)

Cross-platform posting with rate limiting and logging.

**Class:** `SocialPoster`

**Methods:**

```python
poster = SocialPoster(ayrshare_api_key="your_key")

# Post to YouTube
result = poster.post_youtube_video(
    title="My Video",
    description="Video description",
    tags=["ai", "tools"],
    video_path="./video.mp4",
    privacy_status="unlisted"
)

# Post to TikTok
result = poster.post_tiktok(
    caption="Check this out!",
    video_path="./video.mp4"
)

# Post to Instagram Reel
result = poster.post_instagram_reel(
    caption="New content",
    video_path="./video.mp4"
)

# Post to Twitter
result = poster.post_twitter(
    text="Check out my latest video!"
)

# Post to all short-form platforms at once
results = poster.post_all_short_form(
    caption="My video",
    video_path="./video.mp4",
    hashtags=["ai", "automation"]
)

# Schedule a post
schedule = poster.schedule_post(
    platform="tiktok",
    content={"caption": "Coming soon..."},
    scheduled_time="2024-04-01T10:00:00Z"
)
```

### 5. Analytics Tracker (`analytics/tracker.py`)

SQLite-based performance tracking and reporting.

**Class:** `AnalyticsTracker`

**Methods:**

```python
tracker = AnalyticsTracker(db_path="./analytics.db")

# Log a post
post_id = tracker.log_post(
    platform="youtube",
    content_id="dQw4w9WgXcQ",
    metadata={"title": "My Video"}
)

# Update metrics
tracker.update_metrics(
    post_id=post_id,
    views=5000,
    likes=250,
    comments=50,
    shares=100
)

# Get report
report = tracker.get_report(period="week")

# Top performers
top_posts = tracker.top_performing(n=10)

# Revenue estimation
revenue = tracker.revenue_estimate()
print(f"Total estimated revenue: ${revenue['total_estimated_revenue']}")

# Export to CSV
csv_path = tracker.export_to_csv("report.csv", period="week")
```

## API Integrations

### Anthropic Claude

Uses Claude 3.5 Sonnet for script generation.

- Model: `claude-3-5-sonnet-20241022`
- Requires: `ANTHROPIC_API_KEY`

### OpenAI GPT

Alternative to Claude for script generation.

- Model: `gpt-4o-mini`
- Requires: `OPENAI_API_KEY`

### ElevenLabs

Text-to-speech voice generation.

- Pricing: ~$0.00002 per character
- Requires: `ELEVENLABS_API_KEY`
- Supports: Multiple voices and accents

### ComfyUI

Local or cloud-hosted image/video generation.

- Supports: Stable Diffusion, video generation workflows
- No API key needed for local instance
- Cloud instances may require authentication

### Ayrshare

Unified social media posting API.

- Supports: YouTube, TikTok, Instagram, Twitter, LinkedIn, etc.
- Requires: `AYRSHARE_API_KEY`
- Handles rate limiting and scheduling

## Output Structure

```
outputs/
├── scripts/
│   ├── long_form_20240326_103000.json
│   ├── short_form_20240326_104000.json
│   └── topic_suggestions_20240326_105000.json
├── voiceovers/
│   └── vo_20240326_103000.mp3
├── videos/
│   └── video_20240326_104000.mp4
├── thumbnails/
│   └── thumb_20240326_103000.png
├── logs/
│   └── pipeline_20240326.log
├── posts_log.json
└── analytics.db
```

## Advanced Configuration

### Custom Workflows

Add custom ComfyUI workflows in `config.json`:

```json
{
  "comfyui": {
    "workflows": {
      "custom_effect": "./workflows/my_effect.json"
    }
  }
}
```

### Platform-Specific Settings

```json
{
  "youtube": {
    "channel_id": "UCxxx",
    "playlist_id": "PLxxx"
  },
  "tiktok": {
    "hashtag_limit": 10
  },
  "twitter": {
    "character_limit": 280
  }
}
```

### Scheduling with Cron

Run daily pipeline via cron:

```bash
# Daily at 9 AM
0 9 * * * cd /path/to/scripts && python pipeline.py daily

# Weekly batch on Monday
0 10 * * 1 cd /path/to/scripts && python pipeline.py weekly
```

## Troubleshooting

### API Key Issues

Check that all required environment variables are set:

```bash
env | grep API_KEY
```

### ComfyUI Connection Failed

Ensure ComfyUI is running:

```bash
# Local ComfyUI
python -m comfyui.main

# Or check cloud instance URL
curl http://your-comfyui-url/api/status
```

### Voice Generation Timeout

Large scripts are automatically chunked. If still failing:

```python
cost = voice_gen.estimate_cost(text)
print(f"Characters: {cost['character_count']}")
# Reduce script length if over 50,000 characters
```

### Rate Limiting

The poster automatically handles rate limits with exponential backoff.
Monitor `posts_log.json` for details.

## Performance Tips

1. **Batch Processing**: Use `run_weekly_batch()` instead of multiple individual runs
2. **Caching**: Generated scripts are cached with timestamps
3. **Parallel Posting**: Post to multiple platforms simultaneously
4. **Local ComfyUI**: Run locally to avoid network latency
5. **API Provider**: Anthropic tends to be faster for script generation

## Development

### Running Tests

```bash
pytest tests/ -v
```

### Code Style

```bash
black scripts/
flake8 scripts/
mypy scripts/
```

### Logging

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Security Considerations

- Store API keys in environment variables, not in config files
- Use `.env` file with python-dotenv for local development
- Never commit credentials or keys to git
- Rotate API keys regularly
- Monitor API usage for unusual activity

## License

This project is provided as-is for automation and educational purposes.
