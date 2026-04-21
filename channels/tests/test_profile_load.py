"""Tests for ``channels.load_channel_config``."""

from __future__ import annotations

import pytest

from channels import (
    ChannelNotFound,
    ChannelProfile,
    load_channel_config,
)


def test_load_commoncreed_returns_profile():
    profile = load_channel_config("commoncreed")
    assert isinstance(profile, ChannelProfile)
    assert profile.channel_id == "commoncreed"
    assert profile.display_name == "CommonCreed"
    assert profile.niche == "AI & Technology"
    assert profile.voice.provider == "elevenlabs"
    assert profile.postiz.ig_profile == "commoncreed"
    assert profile.palette is not None
    assert profile.palette.primary == "#1E3A8A"  # Navy
    assert "instagram_reels" in profile.platforms_enabled
    assert profile.languages_enabled == ["en"]
    assert profile.telegram_prefix == "[CommonCreed]"


def test_load_unknown_channel_raises():
    with pytest.raises(ChannelNotFound):
        load_channel_config("nonexistent_channel_xyz")


def test_commoncreed_to_legacy_config_matches_legacy_shape():
    """The flattened config must contain every key the pipeline's
    ``__init__`` consumes. Catches regressions from renaming env vars
    or dropping keys.
    """
    profile = load_channel_config("commoncreed")

    # Minimal environment — builder fills missing keys with "" defaults.
    env = {
        "ANTHROPIC_API_KEY": "test-anthropic",
        "AYRSHARE_API_KEY": "test-ayr",
        "TELEGRAM_BOT_TOKEN": "test-tg",
        "TELEGRAM_OWNER_USER_ID": "12345",
    }
    config = profile.to_legacy_config(env)

    # Identity fields from the profile
    assert config["channel_id"] == "commoncreed"
    assert config["channel_display_name"] == "CommonCreed"

    # All keys the existing pipeline consumes (from CommonCreedPipeline.__init__
    # and downstream module constructors). If any key is missing, the pipeline
    # breaks at runtime with KeyError or a silent default.
    expected_keys = {
        "anthropic_api_key",
        "voice_provider",
        "elevenlabs_api_key",
        "voice_id",
        "chatterbox_reference_audio",
        "chatterbox_endpoint",
        "chatterbox_device",
        "comfyui_url",
        "comfyui_api_key",
        "ayrshare_api_key",
        "telegram_bot_token",
        "telegram_owner_user_id",
        "niche",
        "runpod_api_key",
        "runpod_gpu_type_id",
        "runpod_template_id",
        "runpod_network_volume_id",
        "runpod_comfyui_port",
        "avatar_provider",
        "heygen_api_key",
        "heygen_avatar_id",
        "fal_api_key",
        "kling_avatar_image_url",
        "veed_avatar_image_url",
        "veed_resolution",
        "pexels_api_key",
        "bing_api_key",
    }
    missing = expected_keys - set(config.keys())
    assert not missing, f"Legacy config missing keys: {missing}"

    # Env values are passed through verbatim (no ad-hoc transforms).
    assert config["anthropic_api_key"] == "test-anthropic"
    assert config["ayrshare_api_key"] == "test-ayr"
    # Default values are applied when env is missing.
    assert config["niche"] == "AI & Technology"
    assert config["voice_provider"] == "elevenlabs"
    assert config["avatar_provider"] == "veed"
    assert config["runpod_gpu_type_id"] == "NVIDIA GeForce RTX 4090"
