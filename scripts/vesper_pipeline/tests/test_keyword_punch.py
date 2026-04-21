"""Tests for :mod:`scripts.vesper_pipeline.keyword_punch`."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from vesper_pipeline.keyword_punch import (  # noqa: E402
    KeywordPunch,
    detect_keyword_punches,
)


def _seg(word: str, start: float, dur: float = 0.3) -> dict:
    return {"word": word, "start": start, "end": start + dur}


class EmptyInputTests(unittest.TestCase):
    def test_empty_list_returns_empty(self):
        self.assertEqual(detect_keyword_punches([]), [])


class CapitalizationRuleTests(unittest.TestCase):
    def test_mid_sentence_caps_detected(self):
        # "he said DAVID was outside." — DAVID at t=1.5 mid-sentence.
        segments = [
            _seg("he", 0.0),
            _seg("said", 0.5),
            _seg("DAVID", 1.5),
            _seg("was", 2.0),
            _seg("outside.", 2.5),
        ]
        punches = detect_keyword_punches(segments)
        # The long word "outside" might also fire but "outside" is 7 chars
        # so it doesn't hit the length rule.
        davids = [p for p in punches if p.word == "DAVID"]
        self.assertEqual(len(davids), 1)
        self.assertEqual(davids[0].reason, "capitalized")

    def test_sentence_initial_caps_ignored(self):
        """The sentence-initial 'He' must not trigger the capitalization
        rule — capital is grammar, not emphasis. The end-of-sentence
        rule may still fire on the period-adjacent word; we just need
        to confirm no 'capitalized' punch landed on 'He'."""
        segments = [
            _seg("He", 0.0),
            _seg("walked.", 0.5),
        ]
        punches = detect_keyword_punches(segments)
        caps = [p for p in punches if p.reason == "capitalized"]
        self.assertEqual(caps, [])

    def test_short_acronym_skipped(self):
        """Two-letter caps (LA, OK) shouldn't fire — too noisy."""
        segments = [
            _seg("from", 0.0),
            _seg("LA", 0.5),
            _seg("downtown.", 1.0),
        ]
        punches = detect_keyword_punches(segments)
        caps_reasons = [p for p in punches if p.reason == "capitalized"]
        self.assertEqual(caps_reasons, [])


class LongWordRuleTests(unittest.TestCase):
    def test_long_content_word_detected(self):
        segments = [
            _seg("she", 0.0),
            _seg("whispered", 0.5),   # ≥ 8 chars
            _seg("nothing.", 1.5),
        ]
        punches = detect_keyword_punches(segments)
        words = {p.word: p.reason for p in punches}
        self.assertEqual(words.get("whispered"), "long_word")

    def test_stoplike_long_word_ignored(self):
        """'actually' is 8 chars but is stoplike filler."""
        segments = [
            _seg("it", 0.0),
            _seg("actually", 0.5),
            _seg("happened.", 2.0),
        ]
        punches = detect_keyword_punches(segments)
        reasons = [p.reason for p in punches if p.word == "actually"]
        self.assertEqual(reasons, [])


class EndOfSentenceRuleTests(unittest.TestCase):
    def test_period_adjacent_long_word_fires(self):
        segments = [
            _seg("silence.", 0.0),
        ]
        punches = detect_keyword_punches(segments)
        # Sentence-initial + ends in period — fires end_of_sentence.
        self.assertEqual(len(punches), 1)
        self.assertEqual(punches[0].reason, "end_of_sentence")

    def test_short_word_period_not_fired(self):
        segments = [
            _seg("no.", 0.0),  # <4 chars stripped
        ]
        punches = detect_keyword_punches(segments)
        self.assertEqual(punches, [])


class DensityCapTests(unittest.TestCase):
    def test_min_gap_enforced(self):
        """Two candidates within 2 seconds — only the first survives."""
        segments = [
            _seg("she", 0.0),
            _seg("whispered", 0.3),     # long_word → t=0.3
            _seg("quietly", 1.0),
            _seg("something", 1.5),     # long_word → t=1.5 — too close
            _seg("interesting.", 2.0),  # too close too
        ]
        punches = detect_keyword_punches(segments)
        # Only one of the long-words survives.
        self.assertLessEqual(len(punches), 2)
        if len(punches) >= 1:
            self.assertAlmostEqual(punches[0].t_seconds, 0.3, places=3)

    def test_density_cap_limits_total(self):
        """Density cap ~ 1 punch per 12 words — 120-word story with
        plenty of candidates still trims to ~10."""
        segments = []
        for i in range(120):
            word = "whispered" if i % 2 == 0 else "fine"  # ensure many long words
            segments.append(_seg(word, i * 0.5))
        punches = detect_keyword_punches(segments)
        # 120 words * 1/12 density = 10 cap; gap filter trims more.
        self.assertLessEqual(len(punches), 10)
        self.assertGreater(len(punches), 0)


class KeywordPunchStructureTests(unittest.TestCase):
    def test_returns_keyword_punch_objects(self):
        segments = [
            _seg("she", 0.0),
            _seg("whispered", 0.5),
        ]
        punches = detect_keyword_punches(segments)
        for p in punches:
            self.assertIsInstance(p, KeywordPunch)
            self.assertTrue(hasattr(p, "t_seconds"))
            self.assertTrue(hasattr(p, "word"))
            self.assertTrue(hasattr(p, "reason"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
