"""Tests for :class:`ArchivistStoryWriter` (Unit 7).

LLM client mocked — no Anthropic API keys needed.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from story_gen.archivist_writer import (
    ArchetypeLibrary,
    ArchivistStoryWriter,
)
from story_gen.mod_filter import MonetizationModFilter


_ARCHETYPES_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "horror_archetypes.json"
)


def _make_story_text(word_count: int = 170) -> str:
    """Fake story text with a known word count."""
    return "word " * (word_count - 1) + "final."


def _make_llm_response(
    *,
    script: str = None,
    word_count: int = 170,
    setting_tag: str = "night_shift",
    flagged_topics=None,
) -> str:
    return json.dumps({
        "archivist_script": script or _make_story_text(word_count),
        "word_count": word_count,
        "setting_tag": setting_tag,
        "flagged_topics": flagged_topics or [],
    })


class FakeLlm:
    """Returns pre-scripted responses from a queue; records calls."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete_json(self, *, system_prompt, user_message, max_tokens=1024):
        self.calls.append({
            "system_prompt": system_prompt,
            "user_message": user_message,
            "max_tokens": max_tokens,
        })
        if not self.responses:
            raise AssertionError("FakeLlm: no more scripted responses")
        return self.responses.pop(0)


class ArchetypeLibraryTests(unittest.TestCase):
    def test_loads_shipping_library(self):
        lib = ArchetypeLibrary.load(_ARCHETYPES_PATH)
        self.assertGreater(len(lib.archetypes), 5)
        # Every archetype has the expected shape.
        for a in lib.archetypes:
            self.assertIn("id", a)
            self.assertIn("family", a)
            self.assertIn("setting_hint", a)
            self.assertIn("key_beats", a)
            self.assertIn("voice_patterns", a)

    def test_subreddit_hints_map_to_known_ids(self):
        lib = ArchetypeLibrary.load(_ARCHETYPES_PATH)
        known_ids = {a["id"] for a in lib.archetypes}
        for sub, ids in lib.subreddit_hints.items():
            for aid in ids:
                self.assertIn(aid, known_ids, f"subreddit hint {sub!r} points to unknown {aid!r}")

    def test_pick_for_subreddit_returns_hint_when_present(self):
        import random
        lib = ArchetypeLibrary.load(_ARCHETYPES_PATH)
        rng = random.Random(42)
        picked = lib.pick_for_subreddit("nosleep", rng=rng)
        # nosleep hints include night-shift + paranormal archetypes
        self.assertIn(
            picked["id"],
            lib.subreddit_hints.get("nosleep", []),
        )


class WriterHappyPathTests(unittest.TestCase):
    def test_clean_generation_returns_story_draft(self):
        lib = ArchetypeLibrary.load(_ARCHETYPES_PATH)
        llm = FakeLlm([_make_llm_response(word_count=170)])
        writer = ArchivistStoryWriter(
            llm=llm,
            library=lib,
            mod_filter=MonetizationModFilter(),
            min_words=150,
            max_words=200,
        )
        draft = writer.write_short(
            topic_title="Something odd on the late shift",
            subreddit="nosleep",
        )
        self.assertIsNotNone(draft)
        self.assertEqual(draft.word_count, 170)
        self.assertIn(draft.archetype_id, {a["id"] for a in lib.archetypes})
        self.assertEqual(len(llm.calls), 1)

    def test_title_canonicalization_applied_before_prompt(self):
        """Injection-bearing titles must be sanitized before hitting the LLM."""
        lib = ArchetypeLibrary.load(_ARCHETYPES_PATH)
        llm = FakeLlm([_make_llm_response()])
        writer = ArchivistStoryWriter(
            llm=llm,
            library=lib,
            mod_filter=MonetizationModFilter(),
            min_words=150,
            max_words=200,
        )
        injection = "Normal title\U000E0041\U000E0049with hidden tags"
        writer.write_short(topic_title=injection, subreddit="nosleep")
        self.assertEqual(len(llm.calls), 1)
        user_msg = llm.calls[0]["user_message"]
        # The Unicode-tag range must not survive into the prompt.
        for ch in user_msg:
            self.assertFalse(
                0xE0000 <= ord(ch) <= 0xE007F,
                f"Unicode-tag char {ord(ch):#x} reached LLM prompt",
            )


class WriterShapeRetryTests(unittest.TestCase):
    def test_malformed_json_triggers_shape_retry(self):
        lib = ArchetypeLibrary.load(_ARCHETYPES_PATH)
        llm = FakeLlm([
            "not json at all",
            _make_llm_response(word_count=170),
        ])
        writer = ArchivistStoryWriter(
            llm=llm,
            library=lib,
            mod_filter=MonetizationModFilter(),
            min_words=150,
            max_words=200,
            max_shape_retries=1,
        )
        draft = writer.write_short(
            topic_title="A topic",
            subreddit="nosleep",
        )
        self.assertIsNotNone(draft)
        self.assertEqual(len(llm.calls), 2)

    def test_shape_retry_exhausted_returns_none(self):
        lib = ArchetypeLibrary.load(_ARCHETYPES_PATH)
        llm = FakeLlm([
            "not json",
            "still not json",
            "not valid either",
        ])
        writer = ArchivistStoryWriter(
            llm=llm,
            library=lib,
            mod_filter=MonetizationModFilter(),
            min_words=150,
            max_words=200,
            max_shape_retries=1,
        )
        draft = writer.write_short(
            topic_title="A topic",
            subreddit="nosleep",
        )
        self.assertIsNone(draft)
        # 1 initial + 1 retry = 2 calls max.
        self.assertEqual(len(llm.calls), 2)


class WriterModRetryTests(unittest.TestCase):
    def test_mod_reject_returns_none_immediately(self):
        """A mod-filter REJECT (hard rejection) short-circuits — no
        retry budget is burned on REJECT the way REWRITE uses it."""
        lib = ArchetypeLibrary.load(_ARCHETYPES_PATH)
        # Use self-harm method specificity — only the mod filter catches
        # this; the output-shape validator has no rule for it. The text
        # is valid JSON, passes shape validation, then trips mod-filter
        # REJECT.
        bad_script = (
            "word " * 160 +
            "She tied a rope from the rafter in the shed that night."
        )
        llm = FakeLlm([_make_llm_response(script=bad_script, word_count=171)])
        writer = ArchivistStoryWriter(
            llm=llm,
            library=lib,
            mod_filter=MonetizationModFilter(),
            min_words=150,
            max_words=200,
        )
        draft = writer.write_short(topic_title="Topic", subreddit="nosleep")
        self.assertIsNone(draft)
        # REJECT short-circuits at first draft — no regeneration.
        self.assertEqual(len(llm.calls), 1)

    def test_mod_rewrite_retries_with_tightened_prompt(self):
        """REWRITE decisions regenerate with an appended "avoid" block."""
        lib = ArchetypeLibrary.load(_ARCHETYPES_PATH)

        # Stub classifier: first call says real-person=True → rewrite; second
        # call says no → pass.
        class _SwitchingClassifier:
            def __init__(self):
                self.calls = 0

            def classify_named_real_person(self, text):
                self.calls += 1
                return self.calls == 1

            def classify_gore_primary_focus(self, text):
                return False

            def classify_identifiable_real_crime(self, text):
                return False

        llm = FakeLlm([
            _make_llm_response(word_count=170),
            _make_llm_response(word_count=170),
        ])
        writer = ArchivistStoryWriter(
            llm=llm,
            library=lib,
            mod_filter=MonetizationModFilter(classifier=_SwitchingClassifier()),
            min_words=150,
            max_words=200,
            max_mod_rewrites=2,
        )
        draft = writer.write_short(topic_title="Topic", subreddit="nosleep")
        self.assertIsNotNone(draft)
        self.assertEqual(len(llm.calls), 2)
        # Second call must include the tightened-constraints block.
        second_user = llm.calls[1]["user_message"]
        self.assertIn("Additional constraints", second_user)
        self.assertIn("avoid", second_user.lower())

    def test_mod_rewrite_budget_exhausted(self):
        lib = ArchetypeLibrary.load(_ARCHETYPES_PATH)

        class _AlwaysFailClassifier:
            def classify_named_real_person(self, text):
                return True  # always

            def classify_gore_primary_focus(self, text):
                return False

            def classify_identifiable_real_crime(self, text):
                return False

        llm = FakeLlm([_make_llm_response(word_count=170)] * 4)
        writer = ArchivistStoryWriter(
            llm=llm,
            library=lib,
            mod_filter=MonetizationModFilter(classifier=_AlwaysFailClassifier()),
            min_words=150,
            max_words=200,
            max_mod_rewrites=2,
        )
        draft = writer.write_short(topic_title="Topic", subreddit="nosleep")
        self.assertIsNone(draft)
        # 1 initial + 2 rewrites = 3 calls when budget=2.
        self.assertEqual(len(llm.calls), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
