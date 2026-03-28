"""
Central configuration for the Social Media Automation Pipeline.
Copy .env.example to .env and fill in your API keys.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Project Paths ───────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "output"
SCRIPTS_DIR = OUTPUT_DIR / "scripts"
AUDIO_DIR = OUTPUT_DIR / "audio"
VIDEO_DIR = OUTPUT_DIR / "video"
THUMBNAILS_DIR = OUTPUT_DIR / "thumbnails"

# ─── API Keys (loaded from .env) ────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
AYRSHARE_API_KEY = os.getenv("AYRSHARE_API_KEY", "")
RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY", "")
VASTAI_API_KEY = os.getenv("VASTAI_API_KEY", "")

# ─── Avatar Provider Config ──────────────────────────────────────────────────
AVATAR_PROVIDER = os.environ.get("AVATAR_PROVIDER", "kling")
FAL_API_KEY = os.environ.get("FAL_API_KEY", "")
KLING_AVATAR_IMAGE_URL = os.environ.get("KLING_AVATAR_IMAGE_URL", "")
HEYGEN_API_KEY = os.environ.get("HEYGEN_API_KEY", "")
HEYGEN_AVATAR_ID = os.environ.get("HEYGEN_AVATAR_ID", "")

# ─── YouTube API ─────────────────────────────────────────────────────────────
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
YOUTUBE_CLIENT_SECRET_FILE = os.getenv("YOUTUBE_CLIENT_SECRET_FILE", "config/client_secret.json")

# ─── Brand Configuration ────────────────────────────────────────────────────
BRAND = {
    "name": "YourBrandName",           # Change this!
    "niche": "AI & Technology",         # Primary niche
    "secondary_niche": "Personal Finance",
    "tagline": "Making AI Simple",
    "voice_tone": "conversational, informative, slightly casual",
    "target_audience": "tech-curious professionals aged 25-45",
}

# ─── ElevenLabs Voice Config ────────────────────────────────────────────────
VOICE = {
    "voice_id": "",                     # Set after cloning/selecting a voice
    "model_id": "eleven_multilingual_v2",
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.3,
    "output_format": "mp3_44100_128",
}

# ─── Video Generation Config ────────────────────────────────────────────────
VIDEO_GEN = {
    "default_model": "wan2.1-1.3b",    # wan2.1-1.3b, wan2.1-14b, cogvideox-5b, ltx-video
    "resolution": "1280x720",
    "fps": 24,
    "long_form_duration": "8-12min",
    "short_form_duration": "30-60sec",
    "thumbnail_size": "1280x720",
}

# ─── GPU Cloud Config ───────────────────────────────────────────────────────
GPU_CLOUD = {
    "preferred_provider": "runpod",     # runpod, vastai, lambda
    "preferred_gpu": "RTX_4090",        # RTX_4090, L40, A100_40GB, A100_80GB
    "max_hourly_budget": 1.00,          # USD per hour
    "auto_shutdown_minutes": 30,        # Auto-stop after idle
}

# ─── Posting Schedule ───────────────────────────────────────────────────────
SCHEDULE = {
    "youtube_long": {
        "days": ["Monday", "Wednesday", "Friday"],
        "time": "14:00",
        "timezone": "America/New_York",
    },
    "youtube_shorts": {"frequency": "daily", "time": "10:00"},
    "tiktok": {"frequency": "daily", "times": ["12:00", "18:00"]},
    "instagram_reels": {"frequency": "daily", "time": "11:00"},
    "instagram_carousel": {"days": ["Tuesday", "Thursday"], "time": "09:00"},
    "facebook_reels": {"frequency": "daily", "time": "13:00"},
    "twitter": {"frequency": "daily", "times": ["09:00", "15:00", "20:00"]},
    "linkedin": {"days": ["Monday", "Wednesday", "Friday"], "time": "08:00"},
    "pinterest": {"days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], "time": "16:00"},
}

# ─── Niche CPM Data (for analysis) ──────────────────────────────────────────
NICHE_DATA = {
    "AI & Technology": {"rpm_low": 12, "rpm_high": 30, "competition": "medium-high", "ai_suitability": 5, "trend": "rising"},
    "Personal Finance": {"rpm_low": 15, "rpm_high": 40, "competition": "high", "ai_suitability": 5, "trend": "stable"},
    "Business & Entrepreneurship": {"rpm_low": 10, "rpm_high": 25, "competition": "medium", "ai_suitability": 5, "trend": "stable"},
    "True Crime & Mystery": {"rpm_low": 8, "rpm_high": 13, "competition": "medium", "ai_suitability": 3, "trend": "stable"},
    "Health & Wellness": {"rpm_low": 8, "rpm_high": 15, "competition": "medium", "ai_suitability": 3, "trend": "rising"},
    "Education & How-To": {"rpm_low": 9, "rpm_high": 14, "competition": "medium", "ai_suitability": 5, "trend": "stable"},
    "Sleep & Relaxation": {"rpm_low": 4, "rpm_high": 8, "competition": "low", "ai_suitability": 5, "trend": "rising"},
    "Animated Stories": {"rpm_low": 9, "rpm_high": 13, "competition": "medium", "ai_suitability": 3, "trend": "stable"},
    "Crypto & Web3": {"rpm_low": 12, "rpm_high": 35, "competition": "high", "ai_suitability": 4, "trend": "volatile"},
    "Productivity & Tools": {"rpm_low": 10, "rpm_high": 20, "competition": "medium", "ai_suitability": 5, "trend": "rising"},
}

# ─── Affiliate Programs ─────────────────────────────────────────────────────
AFFILIATES = {
    "claude_ai": {"url": "", "commission": "N/A", "category": "AI Tools"},
    "chatgpt_plus": {"url": "", "commission": "N/A", "category": "AI Tools"},
    "elevenlabs": {"url": "", "commission": "22%", "category": "AI Voice"},
    "midjourney": {"url": "", "commission": "N/A", "category": "AI Image"},
    "canva_pro": {"url": "", "commission": "Up to 80%", "category": "Design"},
    "vidiq": {"url": "", "commission": "25%", "category": "YouTube SEO"},
    "pictory": {"url": "", "commission": "30%", "category": "Video AI"},
    "invideo": {"url": "", "commission": "50%", "category": "Video AI"},
    "runpod": {"url": "", "commission": "Variable", "category": "GPU Cloud"},
    "hostinger": {"url": "", "commission": "60%", "category": "Hosting"},
    "nordvpn": {"url": "", "commission": "40-100%", "category": "VPN"},
    # CommonCreed affiliate links — 2-3 included in every video description
    # Replace with actual tracked affiliate URLs before launch
    "ai_tools": "https://example.com/affiliate/ai-tools",
    "courses": "https://example.com/affiliate/courses",
    "hardware": "https://example.com/affiliate/hardware",
}
