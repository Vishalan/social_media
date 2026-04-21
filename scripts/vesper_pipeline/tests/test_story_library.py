"""Tests for :mod:`scripts.vesper_pipeline.story_library`."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from still_gen._types import Beat, BeatMode  # noqa: E402
from vesper_pipeline.story_library import (  # noqa: E402
    _STORIES,
    _TAG_PROMPT_TEMPLATES,
    build_flux_prompts,
    list_all_scored,
    pick_best_story,
    score_story,
    split_story_into_phases,
)


def _beat(tag: str = "hook") -> Beat:
    return Beat(
        mode=BeatMode.STILL_KENBURNS,
        motion_hint="push_in",  # type: ignore[arg-type]
        duration_s=3.0,
        shot_class="interior",  # type: ignore[arg-type]
        prompt="ignored",
        tag=tag,
    )


class ScorerTests(unittest.TestCase):
    def test_all_curated_stories_score_positively(self):
        """Every candidate should have a net-positive score —
        otherwise the curation bar is too low."""
        for s in _STORIES:
            score = score_story(s)
            self.assertGreater(
                score.total, 0.0,
                f"{s['id']} scored {score.total}",
            )

    def test_scorer_rewards_back_half_tension(self):
        """A story with all its tension markers in the back half
        outscores one with the same markers in the front half."""
        back_loaded = {
            "id": "back",
            "text": (
                "I worked the day shift. Nothing unusual happened. "
                "I arrived every morning at seven. I clocked out at "
                "five. One Tuesday I saw the man at the counter "
                "behind you — he hadn't moved. He didn't move. He "
                "was waiting for someone. I never came back."
            ),
        }
        front_loaded = {
            "id": "front",
            "text": (
                "The man behind you didn't move he hadn't moved he "
                "was waiting for someone I was frightened. Then "
                "nothing happened. I worked the day shift. I "
                "arrived at seven. I clocked out at five. Nothing "
                "unusual. I went home. I slept."
            ),
        }
        back_score = score_story(back_loaded)
        front_score = score_story(front_loaded)
        self.assertGreater(
            back_score.back_half_ratio,
            front_score.back_half_ratio,
        )

    def test_pick_best_returns_highest(self):
        chosen = pick_best_story()
        best_id = list_all_scored()[0][1]["id"]
        self.assertEqual(chosen["id"], best_id)

    def test_list_all_scored_sorted_desc(self):
        results = list_all_scored()
        totals = [r[0].total for r in results]
        self.assertEqual(totals, sorted(totals, reverse=True))


class PhaseSplitterTests(unittest.TestCase):
    def test_splits_story_into_n_phases(self):
        text = (
            "One. Two sentence. Three. Four sentence here. "
            "Five. Six. Seven here. Eight. Nine. Ten. Eleven. "
            "Twelve the last."
        )
        for n in (2, 4, 6, 12):
            phases = split_story_into_phases(text, n)
            self.assertEqual(len(phases), n)

    def test_phases_collectively_cover_the_story(self):
        text = "One two. Three four. Five six. Seven eight."
        phases = split_story_into_phases(text, 4)
        combined = " ".join(phases).lower()
        for word in ("one", "five", "eight"):
            self.assertIn(word, combined)


class FluxPromptBuilderTests(unittest.TestCase):
    def _story(self) -> str:
        return (
            "I pulled into the empty lot at two-forty-seven. Inside the "
            "waitress spoke quietly. There was a man at the counter "
            "behind me. He hadn't moved. He hadn't blinked. I left. "
            "I never came back."
        )

    def test_one_prompt_per_beat(self):
        beats = [_beat("hook"), _beat("setup"), _beat("rising")]
        prompts = build_flux_prompts(self._story(), beats)
        self.assertEqual(len(prompts), 3)

    def test_hook_prompt_is_neutral_not_bloody(self):
        """Palette gradient: hook/setup beats MUST NOT include the
        Vesper horror palette — keeps the open neutral."""
        beats = [_beat("hook")]
        prompts = build_flux_prompts(self._story(), beats)
        p = prompts[0].lower()
        self.assertNotIn("blood", p)
        self.assertNotIn("oxidized", p)
        self.assertNotIn("near-black", p)

    def test_climax_prompt_carries_horror_palette(self):
        beats = [_beat("climax")]
        prompts = build_flux_prompts(self._story(), beats)
        p = prompts[0].lower()
        self.assertIn("oxidized", p)
        self.assertIn("near-black", p)

    def test_palette_gradient_across_beats(self):
        """Early beats neutral, later beats escalate."""
        beats = [
            _beat("hook"), _beat("setup"),
            _beat("rising"), _beat("reveal"),
            _beat("climax"), _beat("tail"),
        ]
        prompts = build_flux_prompts(self._story(), beats)
        # hook + setup should NOT contain "oxidized"
        self.assertNotIn("oxidized", prompts[0].lower())
        self.assertNotIn("oxidized", prompts[1].lower())
        # reveal + climax SHOULD contain "oxidized" or "bone"
        self.assertTrue(
            any(w in prompts[3].lower() for w in ("oxidized", "bone"))
        )
        self.assertIn("oxidized", prompts[4].lower())

    def test_prompt_includes_scene_from_story_phase(self):
        """Each prompt should carry some content from the corresponding
        story phase so visuals align with narration."""
        beats = [_beat("hook"), _beat("climax")]
        prompts = build_flux_prompts(self._story(), beats)
        # The first phase mentions "two-forty-seven" or "empty lot".
        self.assertTrue(
            any(w in prompts[0].lower() for w in
                ("two-forty-seven", "lot", "pulled"))
        )
        # The second phase (back half) — scene summary pulls from its
        # first sentence: "He hadn't moved".
        self.assertTrue(
            any(w in prompts[1].lower() for w in
                ("hadn't", "moved", "blinked", "left", "never"))
        )


class IntegrationTests(unittest.TestCase):
    def test_end_to_end_pipeline_shape(self):
        """Pick a story → split → build 12 prompts. Smoke test
        the full chain used by demo_server."""
        chosen = pick_best_story()
        beats = [
            _beat(t) for t in
            ("hook", "hook", "setup", "setup",
             "rising", "rising", "reveal", "reveal",
             "climax", "climax", "tail", "tail")
        ]
        prompts = build_flux_prompts(chosen["text"], beats)
        self.assertEqual(len(prompts), 12)
        # Hook prompts must not contain blood imagery.
        self.assertNotIn("oxidized", prompts[0].lower())
        # Climax prompts must.
        self.assertIn("oxidized", prompts[8].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
