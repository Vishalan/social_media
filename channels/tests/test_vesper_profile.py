"""Tests for the Vesper profile module (Unit 5)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Ensure ``scripts/`` is on the path so the SFX pack registration side
# effect (which imports from ``audio.sfx``) resolves during ``import``.
_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from channels import ChannelProfile, load_channel_config


class VesperProfileLoadTests(unittest.TestCase):
    def test_load_vesper_returns_profile(self):
        profile = load_channel_config("vesper")
        self.assertIsInstance(profile, ChannelProfile)
        self.assertEqual(profile.channel_id, "vesper")
        self.assertEqual(profile.display_name, "Vesper")
        self.assertEqual(profile.niche, "horror-stories")
        self.assertEqual(profile.telegram_prefix, "[Vesper]")
        self.assertEqual(profile.languages_enabled, ["en"])

    def test_vesper_palette_is_horror_tuned(self):
        profile = load_channel_config("vesper")
        self.assertIsNotNone(profile.palette)
        # Bone on near-black; oxidized-blood accent; graphite shadows.
        self.assertEqual(profile.palette.primary, "#E8E2D4")
        self.assertEqual(profile.palette.background, "#0A0A0C")
        self.assertEqual(profile.palette.accent, "#8B1A1A")
        self.assertEqual(profile.palette.shadow, "#2C2826")
        # Cross-bleed guard — Vesper palette must NOT match CommonCreed's.
        cc = load_channel_config("commoncreed")
        self.assertNotEqual(profile.palette, cc.palette)

    def test_vesper_voice_is_chatterbox_archivist(self):
        profile = load_channel_config("vesper")
        self.assertEqual(profile.voice.provider, "chatterbox")
        self.assertIn("archivist", profile.voice.reference_audio.lower())
        # Whispered / tense register — low exaggeration + low cfg.
        self.assertAlmostEqual(profile.voice.exaggeration, 0.35)
        self.assertAlmostEqual(profile.voice.cfg, 0.3)

    def test_vesper_source_is_reddit_signal_only(self):
        """Critical: Vesper's source provider is ``reddit_signal``, NOT
        ``reddit_content`` — research-driven pivot from brainstorm R4."""
        profile = load_channel_config("vesper")
        self.assertIsNotNone(profile.source)
        self.assertEqual(profile.source.provider, "reddit_signal")
        subs = profile.source.params["subreddits"]
        self.assertIn("nosleep", subs)
        self.assertIn("LetsNotMeet", subs)

    def test_vesper_cadence_is_shorts_only_for_v1(self):
        profile = load_channel_config("vesper")
        self.assertEqual(profile.cadence.shorts_per_day, 1)
        self.assertEqual(profile.cadence.longs_per_week, 0)

    def test_vesper_postiz_profiles_set(self):
        profile = load_channel_config("vesper")
        self.assertEqual(profile.postiz.ig_profile, "vesper")
        self.assertEqual(profile.postiz.yt_profile, "vesper")
        self.assertEqual(profile.postiz.tt_profile, "vesper")

    def test_vesper_visual_style_has_anti_slop_targets(self):
        profile = load_channel_config("vesper")
        self.assertGreaterEqual(profile.visual.parallax_target_pct, 20)
        self.assertGreaterEqual(profile.visual.i2v_hero_pct, 10)
        self.assertIn("horror", profile.visual.flux_prompt_prefix.lower())

    def test_vesper_cpm_rates_include_horror_tier(self):
        profile = load_channel_config("vesper")
        self.assertIn("youtube", profile.cpm_rates)
        self.assertIn("youtube_limited_ads", profile.cpm_rates)
        # Limited-ads tier must be materially lower than default YT tier.
        self.assertLess(
            profile.cpm_rates["youtube_limited_ads"],
            profile.cpm_rates["youtube"],
        )

    def test_vesper_thumbnail_uses_cormorant_garamond(self):
        profile = load_channel_config("vesper")
        self.assertEqual(profile.thumbnail.font_name, "CormorantGaramond-Bold")
        self.assertTrue(profile.thumbnail.timestamp_motif, "Vesper's cold-open motif")


class VesperLegacyConfigTests(unittest.TestCase):
    def test_to_legacy_config_exposes_channel_identity(self):
        profile = load_channel_config("vesper")
        env = {
            "ANTHROPIC_API_KEY": "test-ak",
            "TELEGRAM_BOT_TOKEN": "test-tg",
            "TELEGRAM_OWNER_USER_ID": "12345",
        }
        config = profile.to_legacy_config(env)
        self.assertEqual(config["channel_id"], "vesper")
        self.assertEqual(config["channel_display_name"], "Vesper")
        self.assertEqual(config["voice_provider"], "chatterbox")
        self.assertEqual(config["sfx_pack"], "vesper")
        self.assertEqual(config["anthropic_api_key"], "test-ak")

    def test_chatterbox_reference_default_points_to_vesper_archivist(self):
        profile = load_channel_config("vesper")
        config = profile.to_legacy_config({})
        self.assertIn("vesper", config["chatterbox_reference_audio"])
        self.assertIn("archivist", config["chatterbox_reference_audio"])


class VesperSfxPackRegistrationTests(unittest.TestCase):
    """Importing the Vesper profile registers its SFX pack so
    ``pick_sfx(..., pack='vesper')`` resolves without explicit wiring."""

    def test_vesper_pack_is_registered(self):
        # Trigger import so the registration side-effect fires.
        load_channel_config("vesper")
        from audio.sfx import _PACKS
        self.assertIn("vesper", _PACKS)
        pack = _PACKS["vesper"]
        self.assertEqual(pack.name, "vesper")
        # Root dir points under assets/vesper/sfx
        self.assertIn("vesper", str(pack.root_dir))
        self.assertIn("sfx", str(pack.root_dir))

    def test_vesper_category_files_are_horror_tuned(self):
        load_channel_config("vesper")
        from audio.sfx import _PACKS
        cat_files = _PACKS["vesper"].category_files
        # Every filename in the Vesper pack must be prefixed ``vesper_``
        # — cross-bleed guard against the CommonCreed pack leaking in.
        for bucket in cat_files.values():
            for names in bucket.values():
                for n in names:
                    self.assertTrue(
                        n.startswith("vesper_"),
                        f"{n!r} is missing vesper_ prefix",
                    )
        # Categories present
        self.assertIn("cut", cat_files)
        self.assertIn("punch", cat_files)
        self.assertIn("reveal", cat_files)
        self.assertIn("tick", cat_files)


if __name__ == "__main__":
    unittest.main(verbosity=2)
