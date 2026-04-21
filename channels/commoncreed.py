"""CommonCreed channel profile.

First concrete channel. Declares the current pipeline's behavior as a
:class:`ChannelProfile` so the CLI can load it via ``--channel commoncreed``
and the pipeline receives the same flat ``config`` dict it already
consumes.

All secrets are read from ``env`` (typically ``os.environ``) at build
time — never committed. This module is safe to read in diffs.
"""

from __future__ import annotations

from typing import Any, Dict

from ._types import (
    BrandPalette,
    Cadence,
    ChannelProfile,
    PostizProfile,
    SourceConfig,
    ThumbnailStyle,
    VisualStyle,
    VoiceProfile,
)


# ─── Brand palette (from auto-memory project_commoncreed_brand_palette.md) ──

PALETTE = BrandPalette(
    primary="#1E3A8A",       # Navy — caption text, thumbnail title
    background="#FFFFFF",    # White — caption/thumbnail matte (on top of media)
    accent="#5C9BFF",        # Sky blue — keyword-punch / active-caption word
    shadow="#0A1428",        # Darker navy for drop-shadows and plates
)


# ─── Legacy-config builder ──────────────────────────────────────────────────
# Flattens env vars into the dict shape that ``CommonCreedPipeline.__init__``
# already consumes. Extracted verbatim from the CLI block in
# ``scripts/commoncreed_pipeline.py`` so swapping the CLI over to this
# builder is byte-for-byte equivalent.


def _build_legacy_config(env: Dict[str, str]) -> Dict[str, Any]:
    return {
        # Channel identity — read by the pipeline for logging + per-channel
        # routing (analytics channel_id scoping lands in Unit 2).
        "channel_id": "commoncreed",
        "channel_display_name": "CommonCreed",
        "anthropic_api_key": env.get("ANTHROPIC_API_KEY", ""),
        # Voice provider switch + provider-specific config
        "voice_provider": env.get("VOICE_PROVIDER", "elevenlabs").lower(),
        "elevenlabs_api_key": env.get("ELEVENLABS_API_KEY", ""),
        "voice_id": env.get("ELEVENLABS_VOICE_ID", ""),
        "chatterbox_reference_audio": env.get("CHATTERBOX_REFERENCE_AUDIO", ""),
        "chatterbox_endpoint": env.get("CHATTERBOX_ENDPOINT", ""),
        "chatterbox_device": env.get("CHATTERBOX_DEVICE", "cuda"),
        "comfyui_url": env.get("COMFYUI_URL", ""),  # empty = use RunPod
        "comfyui_api_key": env.get("COMFYUI_API_KEY", ""),
        "ayrshare_api_key": env.get("AYRSHARE_API_KEY", ""),
        "telegram_bot_token": env.get("TELEGRAM_BOT_TOKEN", ""),
        "telegram_owner_user_id": env.get("TELEGRAM_OWNER_USER_ID", ""),
        "niche": env.get("NICHE", "AI & Technology"),
        # RunPod config (used when COMFYUI_URL is not set)
        "runpod_api_key": env.get("RUNPOD_API_KEY", ""),
        "runpod_gpu_type_id": env.get("RUNPOD_GPU_TYPE_ID", "NVIDIA GeForce RTX 4090"),
        "runpod_template_id": env.get("RUNPOD_TEMPLATE_ID", ""),
        "runpod_network_volume_id": env.get("RUNPOD_NETWORK_VOLUME_ID", ""),
        "runpod_comfyui_port": env.get("RUNPOD_COMFYUI_PORT", "8188"),
        # Avatar provider config
        "avatar_provider": env.get("AVATAR_PROVIDER", "veed"),
        "heygen_api_key": env.get("HEYGEN_API_KEY", ""),
        "heygen_avatar_id": env.get("HEYGEN_AVATAR_ID", ""),
        "fal_api_key": env.get("FAL_API_KEY", ""),
        "kling_avatar_image_url": env.get("KLING_AVATAR_IMAGE_URL", ""),
        "veed_avatar_image_url": env.get("VEED_AVATAR_IMAGE_URL", ""),
        "veed_resolution": env.get("VEED_RESOLUTION", "480p"),
        # B-roll image sources (optional — degrades gracefully without keys)
        "pexels_api_key": env.get("PEXELS_API_KEY", ""),
        "bing_api_key": env.get("BING_SEARCH_API_KEY", ""),
    }


# ─── Profile ────────────────────────────────────────────────────────────────

PROFILE = ChannelProfile(
    channel_id="commoncreed",
    display_name="CommonCreed",
    niche="AI & Technology",
    voice=VoiceProfile(
        provider="elevenlabs",  # default; env VOICE_PROVIDER overrides at runtime
    ),
    postiz=PostizProfile(
        ig_profile="commoncreed",
        yt_profile="commoncreed",
        # TikTok posting for CommonCreed goes through SocialPoster today;
        # Postiz tt_profile wiring lands in Unit 12.
        tt_profile="",
    ),
    cadence=Cadence(shorts_per_day=2, longs_per_week=0),  # ~2-3/day per CLAUDE.md
    visual=VisualStyle(),  # CommonCreed's visual pipeline is avatar + b-roll;
    # no Flux stills or parallax/I2V mix to declare here.
    palette=PALETTE,
    source=SourceConfig(
        provider="rss_news",
        params={"max_topics": 3},  # NewsSourcer(max_topics=3) in current code
    ),
    thumbnail=ThumbnailStyle(
        font_name="Inter-Bold",
        font_path="assets/fonts/Inter-Bold.ttf",
        max_title_words=9,
        timestamp_motif=False,
        face_pct=60,
    ),
    platforms_enabled=["instagram_reels", "tiktok", "youtube_shorts"],
    languages_enabled=["en"],
    telegram_prefix="[CommonCreed]",
    cpm_rates={},  # Unit 2b populates per-channel CPM rates.
    _legacy_config_builder=_build_legacy_config,
)
