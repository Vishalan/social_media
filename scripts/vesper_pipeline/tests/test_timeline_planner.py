"""Tests for :class:`TimelinePlanner`.

LLM is stubbed with scripted JSON strings. Verifies:
  * Happy-path JSON → Timeline parse + lint pass
  * Invalid JSON raises TimelineShapeError after shape retry
  * Mode/motion_hint mismatch rejected
  * Out-of-range duration rejected
  * Still-mode with empty prompt rejected
  * Lint failure triggers retry with tightened prompt; second success
  * Lint failure twice raises TimelineLintError
  * Retry prompt contains the previous lint summary
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import List

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from still_gen.timeline_lint import LintPolicy  # noqa: E402
from vesper_pipeline.timeline_planner import (  # noqa: E402
    TimelineLintError,
    TimelinePlanner,
    TimelineShapeError,
    _parse_timeline,
)


def _beat(
    mode: str = "still_kenburns",
    motion: str = "push_in",
    duration: float = 3.0,
    shot_class: str = "interior",
    prompt: str = "a bone-white hallway at 3am",
    tag: str = "hook",
) -> dict:
    return {
        "mode": mode,
        "motion_hint": motion,
        "duration_s": duration,
        "shot_class": shot_class,
        "prompt": prompt,
        "tag": tag,
    }


def _well_formed_timeline_json() -> str:
    """14 beats — 7 kenburns (50%), 4 parallax (~29%→ boost below), 3 i2v (~21%).

    We actually need ≥30% parallax and ~20% i2v. Let me use 15 beats:
    8 kenburns / 5 parallax / 3 i2v + varied durations."""
    beats = []
    # 5 parallax = 5/15 = 33% ≥ 30%
    # 3 i2v = 3/15 = 20%
    # 7 kenburns = 7/15 = 47%
    kb_motions = ["push_in", "pull_back", "slow_pan_left", "slow_pan_right"]
    px_motions = ["push_in_2d", "orbit_slight", "dolly_in_subtle"]
    i2v_motions = ["subtle_dolly_in", "breathing_mist", "shadow_movement"]
    durs = [2.8, 3.2, 4.0, 3.6, 2.4, 3.8, 3.0]
    for i in range(7):
        beats.append(_beat(
            mode="still_kenburns",
            motion=kb_motions[i % 4],
            duration=durs[i % len(durs)],
            prompt=f"kenburns scene {i}",
        ))
    for i in range(5):
        beats.append(_beat(
            mode="still_parallax",
            motion=px_motions[i % 3],
            duration=durs[(i + 2) % len(durs)],
            prompt=f"parallax scene {i}",
        ))
    for i in range(3):
        beats.append(_beat(
            mode="hero_i2v",
            motion=i2v_motions[i],
            duration=durs[(i + 4) % len(durs)],
            prompt="",
        ))
    return json.dumps({"beats": beats})


class _ScriptedLlm:
    """LLM stub returning a predetermined list of responses, FIFO."""

    def __init__(self, responses: List[str]):
        self.responses = list(responses)
        self.calls: List[dict] = []

    def complete_json(self, *, system_prompt, user_message, max_tokens=2048):
        self.calls.append({
            "system_prompt": system_prompt,
            "user_message": user_message,
            "max_tokens": max_tokens,
        })
        if not self.responses:
            raise AssertionError("_ScriptedLlm exhausted")
        return self.responses.pop(0)


# ─── Parser tests ───────────────────────────────────────────────────────


class ParserShapeTests(unittest.TestCase):
    def test_well_formed_json_parses_to_timeline(self):
        tl = _parse_timeline(_well_formed_timeline_json())
        self.assertEqual(tl.count, 15)

    def test_invalid_json_raises(self):
        with self.assertRaises(TimelineShapeError) as cm:
            _parse_timeline("not json")
        self.assertIn("invalid JSON", str(cm.exception))

    def test_non_object_root_raises(self):
        with self.assertRaises(TimelineShapeError):
            _parse_timeline(json.dumps([1, 2, 3]))

    def test_missing_beats_raises(self):
        with self.assertRaises(TimelineShapeError):
            _parse_timeline(json.dumps({"foo": "bar"}))

    def test_empty_beats_raises(self):
        with self.assertRaises(TimelineShapeError):
            _parse_timeline(json.dumps({"beats": []}))


class ParserBeatValidationTests(unittest.TestCase):
    def test_unknown_mode_rejected(self):
        beats = [_beat(mode="flashy_glitch")]
        with self.assertRaises(TimelineShapeError) as cm:
            _parse_timeline(json.dumps({"beats": beats}))
        self.assertIn("mode=", str(cm.exception))

    def test_unknown_motion_hint_rejected(self):
        beats = [_beat(motion="whip_pan")]
        with self.assertRaises(TimelineShapeError) as cm:
            _parse_timeline(json.dumps({"beats": beats}))
        self.assertIn("motion_hint=", str(cm.exception))

    def test_mode_motion_mismatch_rejected(self):
        # still_kenburns + push_in_2d (a parallax move) — invalid pairing
        beats = [_beat(mode="still_kenburns", motion="push_in_2d")]
        with self.assertRaises(TimelineShapeError) as cm:
            _parse_timeline(json.dumps({"beats": beats}))
        self.assertIn("incompatible", str(cm.exception))

    def test_unknown_shot_class_rejected(self):
        beats = [_beat(shot_class="montage")]
        with self.assertRaises(TimelineShapeError):
            _parse_timeline(json.dumps({"beats": beats}))

    def test_duration_out_of_range_rejected(self):
        beats = [_beat(duration=10.0)]
        with self.assertRaises(TimelineShapeError) as cm:
            _parse_timeline(json.dumps({"beats": beats}))
        self.assertIn("duration_s", str(cm.exception))

    def test_still_mode_empty_prompt_rejected(self):
        beats = [_beat(prompt="")]
        with self.assertRaises(TimelineShapeError) as cm:
            _parse_timeline(json.dumps({"beats": beats}))
        self.assertIn("non-empty prompt", str(cm.exception))

    def test_i2v_mode_may_have_empty_prompt(self):
        """HERO_I2V uses its own motion-prompt template elsewhere; an
        empty Flux prompt is expected."""
        tl = _parse_timeline(json.dumps({"beats": [
            _beat(mode="hero_i2v", motion="subtle_dolly_in", prompt=""),
        ]}))
        self.assertEqual(tl.count, 1)


# ─── Planner happy path + retry ─────────────────────────────────────────


class PlannerHappyPathTests(unittest.TestCase):
    def test_first_attempt_succeeds(self):
        llm = _ScriptedLlm([_well_formed_timeline_json()])
        planner = TimelinePlanner(llm=llm)
        tl = planner.plan(
            story_text="A quiet hallway at 3am.",
            voice_duration_s=62.5,
        )
        self.assertEqual(tl.count, 15)
        self.assertEqual(len(llm.calls), 1)


class PlannerShapeRetryTests(unittest.TestCase):
    def test_shape_retry_succeeds(self):
        llm = _ScriptedLlm([
            "not json at all",       # first attempt — invalid
            _well_formed_timeline_json(),
        ])
        planner = TimelinePlanner(llm=llm)
        tl = planner.plan(
            story_text="A quiet hallway at 3am.",
            voice_duration_s=62.5,
        )
        self.assertEqual(tl.count, 15)
        self.assertEqual(len(llm.calls), 2)

    def test_shape_retry_exhaustion_raises(self):
        llm = _ScriptedLlm([
            "not json",
            "still not json",
        ])
        planner = TimelinePlanner(llm=llm, max_shape_retries=1)
        with self.assertRaises(TimelineShapeError):
            planner.plan(
                story_text="x", voice_duration_s=60.0,
            )


class PlannerLintRetryTests(unittest.TestCase):
    def _bad_lint_json(self) -> str:
        """10 beats, all kenburns with push_in, same duration — violates
        L1 (variance) + L2 (parallax ratio) + L3 (i2v ratio) + L4 (move
        diversity) + L5 (non-ken-burns)."""
        beats = [_beat(duration=3.0, motion="push_in") for _ in range(10)]
        return json.dumps({"beats": beats})

    def test_lint_retry_succeeds_on_second(self):
        llm = _ScriptedLlm([
            self._bad_lint_json(),
            _well_formed_timeline_json(),
        ])
        planner = TimelinePlanner(llm=llm)
        tl = planner.plan(
            story_text="x", voice_duration_s=60.0,
        )
        self.assertEqual(tl.count, 15)
        self.assertEqual(len(llm.calls), 2)
        # The retry prompt should include the previous lint summary.
        retry_prompt = llm.calls[1]["user_message"]
        self.assertIn("Previous attempt failed anti-slop lint", retry_prompt)

    def test_lint_retry_exhaustion_raises(self):
        llm = _ScriptedLlm([
            self._bad_lint_json(),
            self._bad_lint_json(),
        ])
        planner = TimelinePlanner(llm=llm, max_lint_retries=1)
        with self.assertRaises(TimelineLintError) as cm:
            planner.plan(
                story_text="x", voice_duration_s=60.0,
            )
        # Error message should tell us which rule(s) failed.
        self.assertIn("L", str(cm.exception))


class PlannerInputCanonicalizationTests(unittest.TestCase):
    def test_zero_width_joiner_stripped_from_story(self):
        llm = _ScriptedLlm([_well_formed_timeline_json()])
        planner = TimelinePlanner(llm=llm)
        # Embed a zero-width joiner — should be stripped before reaching
        # the LLM's user message.
        planner.plan(
            story_text="hallway\u200dat\u200d3am",
            voice_duration_s=60.0,
        )
        user_msg = llm.calls[0]["user_message"]
        self.assertNotIn("\u200d", user_msg)
        self.assertIn("hallwayat3am", user_msg)

    def test_very_long_story_truncates(self):
        llm = _ScriptedLlm([_well_formed_timeline_json()])
        planner = TimelinePlanner(llm=llm)
        planner.plan(
            story_text="x" * 8000,
            voice_duration_s=60.0,
        )
        user_msg = llm.calls[0]["user_message"]
        # Story is truncated to 4000 chars in canonicalization; the
        # full 8000-char story should NOT appear in the user message.
        self.assertLess(len(user_msg), 6000)


class PlannerHeroI2VDisabledTests(unittest.TestCase):
    def test_hero_disabled_policy_allows_all_parallax_timeline(self):
        """When Unit 10 is deferred (hero_i2v_enabled=False), the planner
        runs lint with the hero_i2v gate off. A timeline with 0% i2v
        must pass."""
        # 15 beats: 9 parallax + 6 kenburns. Vary durations + motions.
        beats = []
        motions_kb = ["push_in", "pull_back", "slow_pan_left", "slow_pan_right"]
        motions_px = ["push_in_2d", "orbit_slight", "dolly_in_subtle"]
        durs = [2.8, 3.2, 4.0, 3.6, 2.4, 3.8, 3.0]
        for i in range(9):
            beats.append(_beat(
                mode="still_parallax",
                motion=motions_px[i % 3],
                duration=durs[i % len(durs)],
                prompt=f"parallax {i}",
            ))
        for i in range(6):
            beats.append(_beat(
                mode="still_kenburns",
                motion=motions_kb[i % 4],
                duration=durs[(i + 3) % len(durs)],
                prompt=f"kenburns {i}",
            ))

        llm = _ScriptedLlm([json.dumps({"beats": beats})])
        policy = LintPolicy(hero_i2v_enabled=False)
        planner = TimelinePlanner(llm=llm, policy=policy)
        tl = planner.plan(
            story_text="x", voice_duration_s=50.0,
        )
        self.assertEqual(tl.count, 15)
        self.assertEqual(tl.hero_i2v_ratio(), 0.0)
        self.assertGreaterEqual(tl.total_duration_s, 45.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
