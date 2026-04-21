"""Tests for ``channels.load_channel_config`` (runs under plain unittest
so the laptop venv without pytest can execute them)."""

from __future__ import annotations

import unittest

from channels import (
    ChannelNotFound,
    ChannelProfile,
    load_channel_config,
)


class ProfileLoadTests(unittest.TestCase):
    def test_load_commoncreed_returns_profile(self):
        profile = load_channel_config("commoncreed")
        self.assertIsInstance(profile, ChannelProfile)
        self.assertEqual(profile.channel_id, "commoncreed")
        self.assertEqual(profile.display_name, "CommonCreed")
        self.assertEqual(profile.niche, "AI & Technology")
        self.assertEqual(profile.voice.provider, "elevenlabs")
        self.assertEqual(profile.postiz.ig_profile, "commoncreed")
        self.assertIsNotNone(profile.palette)
        self.assertEqual(profile.palette.primary, "#1E3A8A")  # Navy
        self.assertIn("instagram_reels", profile.platforms_enabled)
        self.assertEqual(profile.languages_enabled, ["en"])
        self.assertEqual(profile.telegram_prefix, "[CommonCreed]")

    def test_load_unknown_channel_raises(self):
        with self.assertRaises(ChannelNotFound):
            load_channel_config("nonexistent_channel_xyz")


class LegacyConfigShapeTests(unittest.TestCase):
    def test_commoncreed_to_legacy_config_matches_legacy_shape(self):
        """The flattened config must contain every key the pipeline's
        ``__init__`` consumes. Catches regressions from renaming env vars
        or dropping keys."""
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
        self.assertEqual(config["channel_id"], "commoncreed")
        self.assertEqual(config["channel_display_name"], "CommonCreed")

        # All keys the existing pipeline consumes. If any key is missing,
        # the pipeline breaks at runtime with KeyError or a silent default.
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
        self.assertFalse(missing, f"Legacy config missing keys: {missing}")

        # Env values are passed through verbatim.
        self.assertEqual(config["anthropic_api_key"], "test-anthropic")
        self.assertEqual(config["ayrshare_api_key"], "test-ayr")
        # Defaults are applied when env is missing.
        self.assertEqual(config["niche"], "AI & Technology")
        self.assertEqual(config["voice_provider"], "elevenlabs")
        self.assertEqual(config["avatar_provider"], "veed")
        self.assertEqual(config["runpod_gpu_type_id"], "NVIDIA GeForce RTX 4090")


if __name__ == "__main__":
    unittest.main(verbosity=2)
