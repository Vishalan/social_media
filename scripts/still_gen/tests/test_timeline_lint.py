"""Tests for the anti-slop timeline lint (Unit 9)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from still_gen._types import Beat, BeatMode, Timeline
from still_gen.timeline_lint import (
    LintPolicy,
    LintReport,
    LintViolation,
    lint_timeline,
)


def _beat(
    mode: BeatMode = BeatMode.STILL_KENBURNS,
    motion: str = "push_in",
    duration: float = 3.0,
    shot_class: str = "interior",
    prompt: str = "",
    tag: str = "",
) -> Beat:
    return Beat(
        mode=mode,
        motion_hint=motion,  # type: ignore[arg-type]
        duration_s=duration,
        shot_class=shot_class,  # type: ignore[arg-type]
        prompt=prompt,
        tag=tag,
    )


def _healthy_timeline() -> Timeline:
    """A 20-beat timeline satisfying all default policy rules."""
    beats = []
    motions = [
        "push_in", "push_in_2d", "subtle_dolly_in", "slow_pan_right",
        "orbit_slight", "pull_back", "breathing_mist",
    ]
    durs = [2.8, 3.2, 4.0, 3.6, 2.4, 3.8, 3.0]
    for i in range(20):
        # 60% ken burns / 25% parallax / 15% hero i2v — hits ratios
        if i % 5 in (0, 1, 4):
            mode = BeatMode.STILL_KENBURNS
            motion = motions[i % len(motions)]
        elif i % 5 == 2:
            mode = BeatMode.STILL_PARALLAX
            motion = "push_in_2d" if i % 2 == 0 else "orbit_slight"
        else:
            mode = BeatMode.HERO_I2V
            motion = "subtle_dolly_in" if i % 2 == 0 else "breathing_mist"
        beats.append(_beat(
            mode=mode,
            motion=motion,
            duration=durs[i % len(durs)],
        ))
    return Timeline(beats=beats)


class HealthyTimelineTests(unittest.TestCase):
    def test_default_policy_passes_healthy_timeline(self):
        # Use a wider parallax policy — the fixture hits 20% parallax /
        # 20% hero I2V. Default lint demands 30% parallax.
        policy = LintPolicy(min_parallax_ratio=0.20)
        report = lint_timeline(_healthy_timeline(), policy)
        self.assertTrue(report.ok, f"unexpected violations: {report.summary()}")


class L1DurationVarianceTests(unittest.TestCase):
    def test_flags_4_consecutive_same_duration(self):
        beats = [
            _beat(duration=3.0, motion="push_in"),
            _beat(duration=3.0, motion="push_in_2d"),
            _beat(duration=3.0, motion="subtle_dolly_in"),
            _beat(duration=3.0, motion="pull_back"),  # 4th at same dur
            _beat(duration=4.0, motion="breathing_mist"),
        ] + [_beat(duration=3.5 + i * 0.1, motion="orbit_slight") for i in range(15)]
        report = lint_timeline(
            Timeline(beats=beats),
            LintPolicy(min_parallax_ratio=0.0, hero_i2v_enabled=False,
                       min_total_s=10, max_total_s=200),
        )
        rules = {v.rule for v in report.violations}
        self.assertIn("L1", rules)

    def test_3_consecutive_same_duration_is_allowed(self):
        beats = [
            _beat(duration=3.0, motion="push_in"),
            _beat(duration=3.0, motion="push_in_2d"),
            _beat(duration=3.0, motion="subtle_dolly_in"),   # 3rd — boundary
            _beat(duration=4.0, motion="pull_back"),
        ] + [_beat(duration=3.5 + i * 0.1, motion="orbit_slight") for i in range(15)]
        report = lint_timeline(
            Timeline(beats=beats),
            LintPolicy(min_parallax_ratio=0.0, hero_i2v_enabled=False,
                       min_total_s=10, max_total_s=200),
        )
        self.assertNotIn("L1", {v.rule for v in report.violations})


class L2ParallaxRatioTests(unittest.TestCase):
    def test_below_threshold_violates(self):
        # 10 KB beats, 0 parallax.
        beats = [
            _beat(mode=BeatMode.STILL_KENBURNS, duration=3.5, motion="push_in_2d")
        ] * 10
        report = lint_timeline(
            Timeline(beats=beats),
            LintPolicy(hero_i2v_enabled=False, min_total_s=10, max_total_s=200),
        )
        self.assertIn("L2", {v.rule for v in report.violations})

    def test_meeting_threshold_passes(self):
        # 7 KB + 3 parallax on a 10-beat timeline = 30% parallax.
        beats = [
            _beat(mode=BeatMode.STILL_KENBURNS, duration=3.0 + 0.1 * i,
                  motion=("push_in" if i % 2 else "pull_back"))
            for i in range(7)
        ] + [
            _beat(mode=BeatMode.STILL_PARALLAX, duration=3.0 + 0.1 * i,
                  motion="push_in_2d")
            for i in range(3)
        ]
        report = lint_timeline(
            Timeline(beats=beats),
            LintPolicy(hero_i2v_enabled=False, min_total_s=10, max_total_s=200),
        )
        self.assertNotIn("L2", {v.rule for v in report.violations})


class L3HeroI2VTests(unittest.TestCase):
    def test_missing_hero_when_enabled_violates(self):
        beats = [
            _beat(mode=BeatMode.STILL_PARALLAX, motion="push_in_2d",
                  duration=3.0 + 0.1 * i)
            for i in range(10)
        ]
        report = lint_timeline(
            Timeline(beats=beats),
            LintPolicy(hero_i2v_enabled=True, min_total_s=10, max_total_s=200),
        )
        self.assertIn("L3", {v.rule for v in report.violations})

    def test_hero_when_disabled_violates(self):
        """If Unit 10 is deferred, timeline must contain no hero beats."""
        beats = [
            _beat(mode=BeatMode.STILL_PARALLAX, motion="push_in_2d",
                  duration=3.0 + 0.1 * i)
            for i in range(9)
        ] + [_beat(mode=BeatMode.HERO_I2V, motion="subtle_dolly_in", duration=3.0)]
        report = lint_timeline(
            Timeline(beats=beats),
            LintPolicy(hero_i2v_enabled=False, min_total_s=10, max_total_s=200),
        )
        self.assertIn("L3", {v.rule for v in report.violations})

    def test_hero_disabled_no_hero_passes(self):
        beats = [
            _beat(
                mode=BeatMode.STILL_PARALLAX if i % 3 == 0 else BeatMode.STILL_KENBURNS,
                motion=("push_in_2d" if i % 3 == 0 else "push_in"),
                duration=3.0 + 0.1 * i,
            )
            for i in range(10)
        ]
        # Also diversify motions so L4/L5 pass
        diverse_beats = list(beats)
        diverse_beats[1] = _beat(
            mode=BeatMode.STILL_KENBURNS, motion="pull_back",
            duration=3.5,
        )
        diverse_beats[2] = _beat(
            mode=BeatMode.STILL_KENBURNS, motion="slow_pan_right",
            duration=3.7,
        )
        report = lint_timeline(
            Timeline(beats=diverse_beats),
            LintPolicy(hero_i2v_enabled=False, min_total_s=10, max_total_s=200),
        )
        self.assertNotIn("L3", {v.rule for v in report.violations})


class L4MoveDiversityTests(unittest.TestCase):
    def test_all_same_move_violates(self):
        beats = [_beat(motion="push_in", duration=3.0 + 0.2 * i) for i in range(10)]
        report = lint_timeline(
            Timeline(beats=beats),
            LintPolicy(hero_i2v_enabled=False, min_parallax_ratio=0.0,
                       min_total_s=10, max_total_s=200),
        )
        self.assertIn("L4", {v.rule for v in report.violations})


class L5NonKenBurnsTests(unittest.TestCase):
    def test_only_ken_burns_moves_violate(self):
        # Build 12 beats, all using Ken Burns moves but with varying
        # durations so L1 doesn't trip first.
        ken_burns = ["push_in", "pull_back", "slow_pan_left", "slow_pan_right"]
        beats = [
            _beat(motion=ken_burns[i % 4], duration=3.0 + 0.5 * (i % 5))
            for i in range(12)
        ]
        report = lint_timeline(
            Timeline(beats=beats),
            LintPolicy(hero_i2v_enabled=False, min_parallax_ratio=0.0,
                       min_total_s=10, max_total_s=200),
        )
        rules = {v.rule for v in report.violations}
        self.assertIn("L5", rules)


class L6TotalDurationTests(unittest.TestCase):
    def test_total_below_min_violates(self):
        beats = [_beat(duration=1.0, motion="push_in")]
        report = lint_timeline(Timeline(beats=beats))
        self.assertIn("L6", {v.rule for v in report.violations})

    def test_total_above_max_violates(self):
        beats = [_beat(duration=10.0, motion="push_in")] * 12  # 120s
        report = lint_timeline(
            Timeline(beats=beats),
            LintPolicy(hero_i2v_enabled=False, min_parallax_ratio=0.0),
        )
        self.assertIn("L6", {v.rule for v in report.violations})


class EmptyTimelineTests(unittest.TestCase):
    def test_zero_beats_violates_L6(self):
        report = lint_timeline(Timeline(beats=[]))
        self.assertIn("L6", {v.rule for v in report.violations})
        self.assertFalse(report.ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
