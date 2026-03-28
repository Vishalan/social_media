# Quick Start Guide

Get the social media automation pipeline running in minutes.

## 5-Minute Setup

### 1. Install Dependencies

```bash
cd /path/to/scripts
pip install -r requirements.txt
```

### 2. Set API Keys

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export ELEVENLABS_API_KEY="..."
export AYRSHARE_API_KEY="..."
```

Or create `.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...
ELEVENLABS_API_KEY=...
AYRSHARE_API_KEY=...
```

### 3. Run Your First Video

```bash
python pipeline.py single --topic "AI Tools" --niche "Technology"
```

That's it! The pipeline will:
- Generate a script with ChatGPT
- Create a voice-over with ElevenLabs
- Generate a video thumbnail
- Post to social media (optional)
- Track analytics

## Common Commands

### Generate Single Video

```bash
# Basic: Just the script
python pipeline.py single --topic "Your Topic" --niche "Your Niche" --no-voiceover --no-video

# Full pipeline with posting
python pipeline.py single \
  --topic "AI Tools for Creators" \
  --niche "Content Creators" \
  --post tiktok --post twitter
```

### Run Automated Daily Pipeline

```bash
python pipeline.py daily
```

Generates one video per niche configured in `config.json` and posts automatically.

### Generate Weekly Batch

```bash
python pipeline.py weekly
```

Creates 2 videos per day for 5 days (10 total videos).

### View Analytics

```bash
# Week report
python pipeline.py report --period week

# Revenue estimate
python pipeline.py report --period month
```

## Configuration

### Minimal Config

Create `config.json`:

```json
{
  "api": {
    "provider": "anthropic"
  },
  "daily": {
    "niches": ["Technology"],
    "topics_per_niche": 1,
    "post_platforms": ["tiktok", "twitter"]
  }
}
```

### Custom Voice for Voiceover

```bash
python pipeline.py single \
  --topic "Topic" \
  --niche "Niche" \
  --voice "Adam"  # or "Rachel", "Bella", etc.
```

### Skip Components

```bash
# Script only
python pipeline.py single --topic "Topic" --niche "Niche" \
  --no-voiceover --no-video

# Script + voiceover (no video)
python pipeline.py single --topic "Topic" --niche "Niche" \
  --no-video
```

## Module Usage (Advanced)

### Generate Script Only

```python
from content_gen.script_generator import ScriptGenerator

gen = ScriptGenerator(api_provider="anthropic")
script = gen.generate_long_form(
    topic="AI Tools",
    niche="Developers",
    duration_min=10
)

print(script['title'])
print(script['script'])
```

### Generate Voice-Over

```python
from voiceover.voice_generator import VoiceGenerator

voice = VoiceGenerator()
audio_path = voice.generate(
    text="Your script here...",
    output_path="output.mp3",
    voice_name="Rachel"
)
```

### Post to Social Media

```python
from posting.social_poster import SocialPoster

poster = SocialPoster(ayrshare_api_key="your_key")

# Post to single platform
result = poster.post_tiktok(
    caption="Check this out!",
    video_path="video.mp4"
)

# Post to multiple platforms
results = poster.post_all_short_form(
    caption="New video",
    video_path="video.mp4",
    hashtags=["ai", "tools"]
)
```

### Track Analytics

```python
from analytics.tracker import AnalyticsTracker

tracker = AnalyticsTracker()

# Log a post
post_id = tracker.log_post(
    platform="tiktok",
    content_id="video123",
    metadata={"title": "My Video"}
)

# Update metrics
tracker.update_metrics(post_id, views=5000, likes=250)

# Get report
report = tracker.get_report("week")
print(report)
```

## Environment Variables

Required:

- `ANTHROPIC_API_KEY` - For script generation
- `ELEVENLABS_API_KEY` - For voice-over

Optional (for posting):

- `AYRSHARE_API_KEY` - For cross-platform posting
- `TIKTOK_API_TOKEN` - For TikTok
- `INSTAGRAM_API_TOKEN` - For Instagram
- `TWITTER_BEARER_TOKEN` - For Twitter
- `YOUTUBE_CREDENTIALS` - For YouTube

## Troubleshooting

### "API key not found"

Make sure environment variables are set:

```bash
echo $ANTHROPIC_API_KEY
echo $ELEVENLABS_API_KEY
```

### "Failed to generate voice-over"

Check character count:

```python
from voiceover.voice_generator import VoiceGenerator
voice = VoiceGenerator()
cost = voice.estimate_cost("Your script...")
print(cost)  # Shows character count
```

### "ComfyUI connection failed"

Ensure ComfyUI is accessible at configured URL:

```bash
curl http://localhost:8188/api/status
```

Or update config with correct URL:

```json
{
  "comfyui": {
    "server_url": "http://your-comfyui-url:8188"
  }
}
```

## Output Files

All generated content is saved to `outputs/`:

- `scripts/` - Generated scripts (JSON)
- `voiceovers/` - Generated audio files (MP3)
- `videos/` - Generated videos (MP4)
- `thumbnails/` - Generated thumbnails (PNG)
- `analytics.db` - Performance metrics
- `posts_log.json` - Post history

## Next Steps

1. Check `SETUP.md` for detailed documentation
2. Customize `config.json` for your needs
3. Set up scheduling with cron or task scheduler
4. Monitor analytics and adjust strategy
5. Integrate with your content workflow

## Support

For issues:

1. Check logs in `outputs/logs/`
2. Review `SETUP.md` troubleshooting section
3. Verify API keys and URLs
4. Check API rate limits and quotas

## Tips

- **Batch processing** is more efficient than single runs
- **Local ComfyUI** reduces latency for video generation
- **Ayrshare** is recommended for reliable cross-platform posting
- **SQLite database** doesn't require additional setup
- **Schedule daily runs** with cron for fully automated pipeline

Happy content creating!
