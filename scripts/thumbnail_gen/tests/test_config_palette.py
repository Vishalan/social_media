"""Tests for ``ThumbnailConfig`` (Unit 4).

Covers:
  * Default config mirrors the module-level CommonCreed palette exactly
    (byte-identical guard for pre-Unit-4 rendering).
  * Overriding the config changes the effective palette + font + pip flag.
  * Unsupported aspect raises ``NotImplementedError`` (v1.1 ships 16:9).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from thumbnail_gen.compositor import (
    BRAND_ACCENT_BLUE,
    BRAND_NAVY,
    BRAND_NAVY_DEEP,
    BRAND_WHITE,
    ThumbnailConfig,
    _DEFAULT_CONFIG,
    compose_thumbnail,
)


class DefaultConfigCharacterizationTests(unittest.TestCase):
    """``ThumbnailConfig()`` must mirror the module constants exactly."""

    def test_default_palette_matches_module_constants(self):
        self.assertEqual(_DEFAULT_CONFIG.bg, BRAND_NAVY)
        self.assertEqual(_DEFAULT_CONFIG.bg_deep, BRAND_NAVY_DEEP)
        self.assertEqual(_DEFAULT_CONFIG.accent, BRAND_ACCENT_BLUE)
        self.assertEqual(_DEFAULT_CONFIG.primary, BRAND_WHITE)

    def test_default_font_candidates_include_inter_black(self):
        paths = [str(p) for p in _DEFAULT_CONFIG.font_candidates]
        self.assertTrue(
            any("Inter-Black.ttf" in p for p in paths),
            f"Inter-Black missing from default candidates: {paths}",
        )

    def test_default_pip_enabled(self):
        self.assertTrue(_DEFAULT_CONFIG.pip_enabled)

    def test_default_aspect_is_9_16(self):
        self.assertEqual(_DEFAULT_CONFIG.aspect, "9:16")


class VesperConfigTests(unittest.TestCase):
    """Vesper-shaped config produces the expected per-channel values."""

    VESPER_NEAR_BLACK = (10, 10, 12)       # #0A0A0C
    VESPER_GRAPHITE = (44, 40, 38)         # #2C2826
    VESPER_BLOOD = (139, 26, 26)           # #8B1A1A
    VESPER_BONE = (232, 226, 212)          # #E8E2D4

    def test_override_palette(self):
        cfg = ThumbnailConfig(
            bg=self.VESPER_NEAR_BLACK,
            bg_deep=self.VESPER_GRAPHITE,
            accent=self.VESPER_BLOOD,
            primary=self.VESPER_BONE,
        )
        self.assertEqual(cfg.bg, self.VESPER_NEAR_BLACK)
        self.assertEqual(cfg.accent, self.VESPER_BLOOD)
        self.assertEqual(cfg.primary, self.VESPER_BONE)
        # CommonCreed palette must NOT leak — cross-bleed guard.
        self.assertNotEqual(cfg.bg, BRAND_NAVY)
        self.assertNotEqual(cfg.accent, BRAND_ACCENT_BLUE)

    def test_pip_disabled_for_faceless_channel(self):
        """Faceless Vesper sets ``pip_enabled=False``; the PiP branch in
        ``compose_thumbnail`` must be skipped entirely."""
        cfg = ThumbnailConfig(pip_enabled=False)
        self.assertFalse(cfg.pip_enabled)

    def test_override_font_candidates(self):
        vesper_font = Path("/tmp/CormorantGaramond-Bold.ttf")
        cfg = ThumbnailConfig(font_candidates=(vesper_font,))
        self.assertEqual(cfg.font_candidates, (vesper_font,))


class AspectGateTests(unittest.TestCase):
    """Aspect ≠ '9:16' raises cleanly — deferred to v1.1."""

    def test_16_9_aspect_raises(self):
        cfg = ThumbnailConfig(aspect="16:9")
        # Use any path args — the aspect check fires before file I/O.
        with self.assertRaises(NotImplementedError) as ctx:
            compose_thumbnail(
                headline="x",
                background_path=None,
                cutout_path=Path("/nope"),
                output_path=Path("/tmp/x.png"),
                config=cfg,
            )
        self.assertIn("16:9", str(ctx.exception))
        self.assertIn("v1.1", str(ctx.exception))


class PipSkipWhenDisabledTests(unittest.TestCase):
    """When ``pip_enabled=False``, ``_circle_pip`` must not be invoked
    (otherwise faceless channels would fail when the cutout file is absent)."""

    def test_compose_thumbnail_skips_pip_branch_when_disabled(self):
        cfg = ThumbnailConfig(pip_enabled=False)

        # Patch _circle_pip so we can assert it's never called.
        with patch("thumbnail_gen.compositor._circle_pip") as mock_pip:
            # Use a non-existent cutout path — with pip_enabled=False this must
            # NOT raise. The rest of the render (gradient background + text)
            # proceeds normally.
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "vesper_sample.png"
                compose_thumbnail(
                    headline="Test headline",
                    background_path=None,
                    cutout_path=Path("/nonexistent/cutout.png"),
                    output_path=out,
                    config=cfg,
                )
                self.assertTrue(out.exists(), "expected PNG to be written")
        mock_pip.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
