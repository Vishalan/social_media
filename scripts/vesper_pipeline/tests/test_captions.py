"""Tests for :mod:`scripts.vesper_pipeline.captions`."""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from vesper_pipeline.captions import (  # noqa: E402
    CaptionStyle,
    _hex_to_ass_color,
    _ts,
    build_ass_captions,
    caption_style_from_palette,
)


class HexToAssTests(unittest.TestCase):
    def test_vesper_bone_primary(self):
        # Bone #E8E2D4 → BGR &H00D4E2E8
        self.assertEqual(_hex_to_ass_color("#E8E2D4"), "&H00D4E2E8")

    def test_vesper_accent_oxidized_blood(self):
        # #8B1A1A → &H001A1A8B
        self.assertEqual(_hex_to_ass_color("#8B1A1A"), "&H001A1A8B")

    def test_rejects_malformed(self):
        with self.assertRaises(ValueError):
            _hex_to_ass_color("#FFF")


class TimestampTests(unittest.TestCase):
    def test_under_minute(self):
        self.assertEqual(_ts(0.0), "0:00:00.00")
        # Use values away from float-rounding boundaries.
        self.assertEqual(_ts(12.34), "0:00:12.34")

    def test_over_minute(self):
        self.assertEqual(_ts(72.5), "0:01:12.50")

    def test_over_hour(self):
        self.assertEqual(_ts(3723.40), "1:02:03.40")


class BuildAssCaptionsTests(unittest.TestCase):
    def _style(self) -> CaptionStyle:
        return CaptionStyle(
            primary="#E8E2D4",
            accent="#8B1A1A",
            shadow="#2C2826",
            font_name="CormorantGaramond-Bold",
            fontsize=58,
            active_fontsize=70,
        )

    def test_header_contains_vesper_style_fields(self):
        segments = [{"word": "hello", "start": 0.0, "end": 0.5}]
        ass = build_ass_captions(segments, self._style())
        self.assertIn("[Script Info]", ass)
        self.assertIn("PlayResX: 1080", ass)
        self.assertIn("PlayResY: 1920", ass)
        self.assertIn("CormorantGaramond-Bold", ass)
        # Vesper active size 70 + inactive 58 both appear.
        self.assertIn(",58,", ass)
        self.assertIn(",70,", ass)
        # Accent color (oxidized blood BGR) appears for CaptionActive.
        self.assertIn("&H001A1A8B", ass)

    def test_each_word_becomes_its_own_dialogue_line(self):
        segments = [
            {"word": "three", "start": 0.0, "end": 0.4},
            {"word": "am", "start": 0.4, "end": 0.7},
        ]
        ass = build_ass_captions(segments, self._style())
        lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        self.assertEqual(len(lines), 2)
        self.assertIn("three", lines[0])
        self.assertIn("am", lines[1])

    def test_empty_word_dropped_with_no_dialogue(self):
        segments = [
            {"word": "", "start": 0.0, "end": 0.5},
            {"word": "good", "start": 0.5, "end": 1.0},
        ]
        ass = build_ass_captions(segments, self._style())
        lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        self.assertEqual(len(lines), 1)
        self.assertIn("good", lines[0])

    def test_end_before_start_dropped(self):
        segments = [
            {"word": "drift", "start": 0.8, "end": 0.5},
            {"word": "ok", "start": 1.0, "end": 1.2},
        ]
        ass = build_ass_captions(segments, self._style())
        lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        self.assertEqual(len(lines), 1)
        self.assertIn("ok", lines[0])

    def test_ass_injection_chars_escaped(self):
        """ASS override blocks are delimited by {} — a word containing
        literal braces must not inject override syntax."""
        segments = [
            {"word": "a{\\bord0}attack", "start": 0.0, "end": 0.3},
        ]
        ass = build_ass_captions(segments, self._style())
        line = next(l for l in ass.splitlines() if l.startswith("Dialogue:"))
        # Braces from the user stripped.
        self.assertNotIn("a{\\bord0}", line)
        # Legit override (our positioning block) must still be there.
        self.assertIn("{\\an5\\pos(540,1440)}", line)

    def test_empty_segments_produces_header_only(self):
        ass = build_ass_captions([], self._style())
        lines = [l for l in ass.splitlines() if l.startswith("Dialogue:")]
        self.assertEqual(len(lines), 0)
        self.assertIn("[V4+ Styles]", ass)


class PaletteAdapterTests(unittest.TestCase):
    def test_caption_style_from_palette(self):
        @dataclass
        class _P:
            primary: str = "#E8E2D4"
            accent: str = "#8B1A1A"
            shadow: str = "#2C2826"
            background: str = "#0A0A0C"

        @dataclass
        class _TS:
            font_name: str = "CormorantGaramond-Bold"

        style = caption_style_from_palette(_P(), _TS())
        self.assertEqual(style.primary, "#E8E2D4")
        self.assertEqual(style.accent, "#8B1A1A")
        self.assertEqual(style.shadow, "#2C2826")
        self.assertEqual(style.font_name, "CormorantGaramond-Bold")


if __name__ == "__main__":
    unittest.main(verbosity=2)
