"""Tests for :class:`MonetizationModFilter` (Unit 7)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from story_gen._types import ModDecision
from story_gen.mod_filter import (
    MonetizationModFilter,
    _PassthroughClassifier,
)


class _StubClassifier:
    """Test classifier with pre-scripted responses."""

    def __init__(
        self,
        real_person: bool = False,
        gore_primary: bool = False,
        real_crime: bool = False,
    ):
        self.real_person = real_person
        self.gore_primary = gore_primary
        self.real_crime = real_crime

    def classify_named_real_person(self, text: str) -> bool:
        return self.real_person

    def classify_gore_primary_focus(self, text: str) -> bool:
        return self.gore_primary

    def classify_identifiable_real_crime(self, text: str) -> bool:
        return self.real_crime


class RegexPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.filt = MonetizationModFilter()

    def test_clean_atmospheric_story_passes(self):
        script = (
            "The trucker pulled over at the rest stop. The fog was thick. "
            "He heard something rustling in the treeline but saw nothing. "
            "Later, on the road, the wipers were moving on their own."
        )
        r = self.filt.evaluate(script)
        self.assertEqual(r.decision, ModDecision.PASS)
        self.assertEqual(r.reasons, [])

    def test_url_in_script_rejected(self):
        script = "He wrote the address on a napkin: https://nowhere.example"
        r = self.filt.evaluate(script)
        self.assertEqual(r.decision, ModDecision.REJECT)
        self.assertIn("url_in_script", r.reasons)

    def test_self_harm_method_specificity_rejected(self):
        script = (
            "She tied a rope from the rafter in the shed. I don't want to think "
            "about the rest."
        )
        r = self.filt.evaluate(script)
        self.assertEqual(r.decision, ModDecision.REJECT)
        self.assertIn("self_harm_method_specificity", r.reasons)

    def test_dosage_specificity_rejected(self):
        script = (
            "On the nightstand — a white bottle, 30 pills missing. The rest, "
            "I'm told, were still sealed."
        )
        r = self.filt.evaluate(script)
        self.assertEqual(r.decision, ModDecision.REJECT)

    def test_sexual_violence_rejected(self):
        script = "The story she told ended with a rape allegation against a cousin."
        r = self.filt.evaluate(script)
        self.assertEqual(r.decision, ModDecision.REJECT)
        self.assertIn("sexual_violence", r.reasons)

    def test_minor_age_flagged(self):
        script = "A 7-year-old was in the house when they heard the first knock."
        r = self.filt.evaluate(script)
        self.assertEqual(r.decision, ModDecision.REJECT)
        self.assertIn("minor_victim_or_perpetrator", r.reasons)

    def test_kindergartener_flagged(self):
        script = (
            "The grade-schooler next door said he'd seen the man in the trees. "
            "He never came back outside."
        )
        r = self.filt.evaluate(script)
        self.assertEqual(r.decision, ModDecision.REJECT)

    def test_hash_is_populated(self):
        r = self.filt.evaluate("clean narrative text")
        self.assertIsNotNone(r.content_sha256)
        self.assertEqual(len(r.content_sha256), 64)


class ClassifierPathTests(unittest.TestCase):
    def test_real_person_classifier_triggers_rewrite(self):
        filt = MonetizationModFilter(classifier=_StubClassifier(real_person=True))
        r = filt.evaluate("A clean narrative.")
        self.assertEqual(r.decision, ModDecision.REWRITE)
        self.assertIn("real_person_named", r.reasons)

    def test_gore_primary_classifier_triggers_rewrite_when_gore_regex_above_threshold(self):
        filt = MonetizationModFilter(
            classifier=_StubClassifier(gore_primary=True),
            gore_regex_threshold=1,  # lower bar so test text trips
        )
        script = (
            "The viscera lay on the floor. Disembowelment was, the witness said, "
            "the eviscerated focal point. Gore everywhere."
        )
        r = filt.evaluate(script)
        self.assertEqual(r.decision, ModDecision.REWRITE)
        self.assertIn("gore_primary_focus", r.reasons)

    def test_real_crime_classifier_rejects(self):
        filt = MonetizationModFilter(classifier=_StubClassifier(real_crime=True))
        r = filt.evaluate("A clean narrative.")
        self.assertEqual(r.decision, ModDecision.REJECT)
        self.assertIn("identifiable_real_crime", r.reasons)

    def test_multiple_categories_rejected_wins(self):
        # Reject (real_crime) takes precedence over rewrite (real_person).
        filt = MonetizationModFilter(
            classifier=_StubClassifier(real_person=True, real_crime=True),
        )
        r = filt.evaluate("A clean narrative.")
        self.assertEqual(r.decision, ModDecision.REJECT)


class PassthroughClassifierTests(unittest.TestCase):
    def test_returns_false_for_all_categories(self):
        c = _PassthroughClassifier()
        self.assertFalse(c.classify_named_real_person("x"))
        self.assertFalse(c.classify_gore_primary_focus("x"))
        self.assertFalse(c.classify_identifiable_real_crime("x"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
