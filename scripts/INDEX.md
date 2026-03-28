# Social Media Content Automation Pipeline - Index

Complete, production-ready automation pipeline for social media content creation.

## Quick Links

- **Getting Started**: See [QUICKSTART.md](QUICKSTART.md) (5 minutes)
- **Full Setup**: See [SETUP.md](SETUP.md) for complete configuration
- **Architecture**: See [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) for design details
- **File Reference**: See [FILES.txt](FILES.txt) for complete listing

## What This Does

1. **Generates Scripts** - AI-powered content creation using Claude or GPT
2. **Creates Voice-Overs** - Text-to-speech with ElevenLabs
3. **Generates Videos** - Thumbnails and video content via ComfyUI
4. **Posts to Social** - YouTube, TikTok, Instagram, Twitter simultaneously
5. **Tracks Analytics** - SQLite database with performance metrics

## Installation (3 Steps)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set API keys
export ANTHROPIC_API_KEY="your-key"
export ELEVENLABS_API_KEY="your-key"

# 3. Run
python pipeline.py single --topic "AI Tools" --niche "Developers"
```

## Core Modules

### 1. Script Generator
**File**: `content_gen/script_generator.py`

Generate optimized scripts for different content types.

```python
from content_gen.script_generator import ScriptGenerator

gen = ScriptGenerator(api_provider="anthropic")
script = gen.generate_short_form("AI Tools", "Digital Marketing")
```

**Methods**:
- `generate_long_form(topic, niche, duration_min=10)` - Long-form scripts
- `generate_short_form(topic, niche)` - 30-60 second scripts
- `generate_twitter_thread(topic, niche, num_tweets=5)` - Twitter threads
- `suggest_topics(niche, count=10)` - Get trending topics

### 2. Voice Generator
**File**: `voiceover/voice_generator.py`

Generate voice-overs with automatic chunking.

```python
from voiceover.voice_generator import VoiceGenerator

voice = VoiceGenerator()
audio_path = voice.generate("Your script...", "output.mp3")
cost = voice.estimate_cost("Script...")
```

**Methods**:
- `generate(text, output_path, voice_id=None)` - Generate audio
- `list_voices()` - Available voices
- `estimate_cost(text)` - Cost estimate

### 3. ComfyUI Client
**File**: `video_gen/comfyui_client.py`

Video and image generation via ComfyUI.

```python
from video_gen.comfyui_client import ComfyUIClient

client = ComfyUIClient("http://localhost:8188")
prompt_id = await client.run_workflow(workflow_json)
files = await client.download_output(prompt_id, "outputs/")
```

**Methods**:
- `run_workflow(workflow_json, params={})` - Submit workflow
- `get_status(prompt_id)` - Check progress
- `download_output(prompt_id, output_dir)` - Download files
- `generate_thumbnail(topic_prompt, output_path)` - Thumbnail
- `generate_short_video(prompt, output_path)` - Video

### 4. Social Poster
**File**: `posting/social_poster.py`

Post to YouTube, TikTok, Instagram, Twitter.

```python
from posting.social_poster import SocialPoster

poster = SocialPoster(ayrshare_api_key="key")
result = poster.post_tiktok("Caption text", "video.mp4")
results = poster.post_all_short_form("Caption", "video.mp4", ["#ai"])
```

**Methods**:
- `post_youtube_video(title, description, tags, video_path)` - YouTube
- `post_tiktok(caption, video_path)` - TikTok
- `post_instagram_reel(caption, video_path)` - Instagram
- `post_twitter(text, media_path=None)` - Twitter
- `post_all_short_form(caption, video_path, hashtags)` - All platforms
- `schedule_post(platform, content, scheduled_time)` - Schedule

### 5. Analytics Tracker
**File**: `analytics/tracker.py`

Track metrics and generate reports.

```python
from analytics.tracker import AnalyticsTracker

tracker = AnalyticsTracker()
post_id = tracker.log_post("youtube", "video123")
tracker.update_metrics(post_id, views=5000, likes=250)
report = tracker.get_report("week")
revenue = tracker.revenue_estimate()
```

**Methods**:
- `log_post(platform, content_id, metadata)` - Log a post
- `update_metrics(post_id, views, likes, comments, shares)` - Update stats
- `get_report(period)` - Generate report
- `top_performing(n=10)` - Top content
- `revenue_estimate(views_by_platform)` - Revenue estimate
- `export_to_csv(output_path, period)` - Export report

### 6. Pipeline Orchestrator
**File**: `pipeline.py`

Master class coordinating all modules.

```python
from pipeline import ContentPipeline

pipeline = ContentPipeline()
result = await pipeline.generate_single_video("Topic", "Niche")
```

**Methods**:
- `generate_single_video(topic, niche, video_type)` - End-to-end
- `run_daily()` - Daily automated pipeline
- `run_weekly_batch()` - Weekly batch (10 videos)
- `generate_report(period)` - Analytics

## CLI Commands

```bash
# Generate single video (with all options)
python pipeline.py single \
  --topic "AI Tools" \
  --niche "Developers" \
  --type short_form \
  --voice Rachel \
  --post tiktok --post twitter \
  --api-provider anthropic

# Run daily pipeline
python pipeline.py daily

# Run weekly batch
python pipeline.py weekly

# Generate report
python pipeline.py report --period week
```

## Configuration

Create `config.json` from `config.example.json`:

```json
{
  "api": {
    "provider": "anthropic"
  },
  "daily": {
    "niches": ["Technology", "Marketing"],
    "topics_per_niche": 1,
    "post_platforms": ["tiktok", "twitter"]
  }
}
```

## Environment Variables

**Required**:
```
ANTHROPIC_API_KEY=sk-ant-...
ELEVENLABS_API_KEY=...
```

**Optional**:
```
OPENAI_API_KEY=...
AYRSHARE_API_KEY=...
TIKTOK_API_TOKEN=...
INSTAGRAM_API_TOKEN=...
TWITTER_BEARER_TOKEN=...
```

## Output Structure

```
outputs/
├── scripts/           # Generated scripts (JSON)
├── voiceovers/        # Generated audio (MP3)
├── videos/            # Generated videos (MP4)
├── thumbnails/        # Generated images (PNG)
├── logs/              # Log files
├── analytics.db       # SQLite database
└── posts_log.json     # JSON post log
```

## Supported Platforms

**Content Generation**:
- Anthropic Claude (recommended)
- OpenAI GPT

**Voice**:
- ElevenLabs (15+ voices)

**Video**:
- ComfyUI (local or cloud)

**Posting**:
- YouTube
- TikTok
- Instagram
- Twitter/X
- LinkedIn (via Ayrshare)

## Examples

### Generate Script Only

```bash
python pipeline.py single --topic "AI" --niche "Tech" --no-voiceover --no-video
```

### Generate with All Features

```bash
python pipeline.py single \
  --topic "Machine Learning" \
  --niche "Data Scientists" \
  --type long_form \
  --voice Bella \
  --post youtube \
  --post tiktok
```

### Programmatic Use

```python
from pipeline import ContentPipeline

pipeline = ContentPipeline(api_provider="anthropic")
result = await pipeline.generate_single_video(
    topic="AI Tools",
    niche="Developers",
    post_to_platforms=["tiktok", "twitter"]
)
print(result['assets']['script']['title'])
```

### Batch Processing

```bash
python pipeline.py weekly  # 10 videos (2/day for 5 days)
```

### Analytics

```bash
python pipeline.py report --period month
```

## File Organization

| File | Purpose |
|------|---------|
| `pipeline.py` | Master orchestrator and CLI |
| `content_gen/script_generator.py` | Script generation |
| `voiceover/voice_generator.py` | Voice-over generation |
| `video_gen/comfyui_client.py` | Video generation |
| `posting/social_poster.py` | Social media posting |
| `analytics/tracker.py` | Analytics and reporting |
| `config.example.json` | Configuration template |
| `requirements.txt` | Dependencies |
| `QUICKSTART.md` | 5-minute guide |
| `SETUP.md` | Complete setup |
| `PROJECT_SUMMARY.md` | Architecture |
| `FILES.txt` | File reference |
| `INDEX.md` | This file |

## Getting Help

1. **Quick questions**: See QUICKSTART.md
2. **Setup issues**: See SETUP.md troubleshooting
3. **Architecture**: See PROJECT_SUMMARY.md
4. **Code details**: Read module docstrings and comments
5. **Examples**: Check `if __name__ == "__main__"` sections

## Key Features

- Production-quality code with type hints
- Comprehensive error handling
- Retry logic with exponential backoff
- Rate limiting (60 requests/minute)
- Rich terminal UI with progress display
- SQLite database (no server needed)
- JSON logging of all actions
- Configuration files with examples
- CLI interface with multiple commands
- Async/await support
- Context managers for resource cleanup

## Requirements

- Python 3.9+
- 4GB RAM minimum
- Internet connection (for APIs)
- Optional: Local ComfyUI instance

## Installation

```bash
pip install -r requirements.txt
```

## Quick Start

```bash
# 1. Set keys
export ANTHROPIC_API_KEY="sk-ant-..."
export ELEVENLABS_API_KEY="..."

# 2. Run
python pipeline.py single --topic "Topic" --niche "Niche"

# 3. Check outputs
ls outputs/
```

## Next Steps

1. Read QUICKSTART.md (5 minutes)
2. Install dependencies
3. Set API keys
4. Run first pipeline
5. Configure config.json
6. Schedule with cron

## Support

See SETUP.md for detailed troubleshooting and advanced configuration.

---

**Status**: Production-ready | **Version**: 1.0 | **Last Updated**: 2024
