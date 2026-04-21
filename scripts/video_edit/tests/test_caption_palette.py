"""Characterization tests for ``VideoEditor._build_ass_captions`` (Unit 3).

The no-arg ``VideoEditor()`` must render byte-identical ASS captions
to the pre-Unit-3 code (CommonCreed's navy/sky-blue/white + Inter 64/72).
Per-channel overrides (Vesper palette + typography) must produce
different — and structurally correct — ASS output.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from video_edit.video_editor import VideoEditor


def _sample_segments() -> list[dict]:
    """A deterministic 3-word transcript. Content doesn't matter beyond
    the need to exercise the caption path; we only assert on the ASS
    header + one Dialogue line."""
    return [
        {"word": "Hello", "start": 0.0, "end": 0.3},
        {"word": "world", "start": 0.3, "end": 0.6},
        {"word": "today", "start": 0.6, "end": 0.9},
    ]


class CommonCreedCharacterizationTests(unittest.TestCase):
    """VideoEditor() with no kwargs must keep producing CommonCreed's exact
    header (same font, sizes, palette). Regression guard for the refactor."""

    def test_default_header_uses_inter_64_72(self):
        editor = VideoEditor()
        header = editor._build_ass_captions(_sample_segments())

        # Font name
        self.assertIn("Style: Caption,Inter,", header)
        self.assertIn("Style: CaptionActive,Inter,", header)
        # Font sizes
        self.assertIn(",Inter,64,", header)
        self.assertIn(",Inter,72,", header)

    def test_default_palette_matches_commoncreed_navy_sky_white(self):
        """ASS color tokens are BGR-encoded hex. We compute the expected
        values from ``branding.to_ass_color`` so the test tracks any
        future fix to the encoding helper without drifting out of sync.
        """
        from branding import to_ass_color

        expected_primary = to_ass_color("#FFFFFF")  # default caption_primary
        expected_accent = to_ass_color("#5C9BFF")   # default caption_accent
        expected_shadow = to_ass_color("#1E3A8A")   # default caption_shadow

        editor = VideoEditor()
        header = editor._build_ass_captions(_sample_segments())

        # Every palette color appears somewhere in the rendered header.
        self.assertIn(expected_primary, header)
        self.assertIn(expected_accent, header)
        self.assertIn(expected_shadow, header)


class VesperOverrideTests(unittest.TestCase):
    """Passing Vesper-tuned palette + typography produces different —
    and structurally correct — ASS output."""

    VESPER_PRIMARY = "#E8E2D4"   # bone
    VESPER_ACCENT = "#8B1A1A"    # oxidized blood
    VESPER_SHADOW = "#0A0A0C"    # near-black
    VESPER_FONT = "CormorantGaramond-Bold"

    def test_vesper_header_uses_overrides(self):
        from branding import to_ass_color

        editor = VideoEditor(
            caption_primary=self.VESPER_PRIMARY,
            caption_accent=self.VESPER_ACCENT,
            caption_shadow=self.VESPER_SHADOW,
            caption_font=self.VESPER_FONT,
        )
        header = editor._build_ass_captions(_sample_segments())

        self.assertIn(f"Style: Caption,{self.VESPER_FONT},", header)
        self.assertIn(f"Style: CaptionActive,{self.VESPER_FONT},", header)
        self.assertIn(to_ass_color(self.VESPER_PRIMARY), header)
        self.assertIn(to_ass_color(self.VESPER_ACCENT), header)
        self.assertIn(to_ass_color(self.VESPER_SHADOW), header)

        # CommonCreed palette must NOT appear — this is the cross-bleed guard
        # that made it into the plan's Security Posture.
        self.assertNotIn(to_ass_color("#5C9BFF"), header)  # sky blue
        self.assertNotIn(to_ass_color("#1E3A8A"), header)  # navy
        # Font-name check: no Inter anywhere in header lines.
        self.assertNotIn("Style: Caption,Inter,", header)
        self.assertNotIn("Style: CaptionActive,Inter,", header)

    def test_vesper_and_commoncreed_produce_distinct_headers(self):
        editor_cc = VideoEditor()
        editor_vs = VideoEditor(
            caption_primary=self.VESPER_PRIMARY,
            caption_accent=self.VESPER_ACCENT,
            caption_shadow=self.VESPER_SHADOW,
            caption_font=self.VESPER_FONT,
        )
        self.assertNotEqual(
            editor_cc._build_ass_captions(_sample_segments()),
            editor_vs._build_ass_captions(_sample_segments()),
        )


class SfxPackWiringTests(unittest.TestCase):
    """VideoEditor stores the sfx_pack name — used by
    ``mix_sfx_into_audio`` downstream."""

    def test_default_sfx_pack_is_commoncreed(self):
        editor = VideoEditor()
        self.assertEqual(editor._sfx_pack, "commoncreed")

    def test_override_sfx_pack_stored(self):
        editor = VideoEditor(sfx_pack="vesper")
        self.assertEqual(editor._sfx_pack, "vesper")


if __name__ == "__main__":
    unittest.main(verbosity=2)
