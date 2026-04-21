"""Tests for :mod:`scripts.vesper_pipeline.sfx_mix`."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import List

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from still_gen._types import Beat, BeatMode, Timeline  # noqa: E402

from vesper_pipeline._types import VesperJob  # noqa: E402
from vesper_pipeline.sfx_mix import SfxMixStage, derive_sfx_events  # noqa: E402


def _beat(mode: BeatMode, motion: str = "push_in",
          duration: float = 3.0) -> Beat:
    return Beat(
        mode=mode,
        motion_hint=motion,  # type: ignore[arg-type]
        duration_s=duration,
        shot_class="interior",  # type: ignore[arg-type]
        prompt="x" if mode != BeatMode.HERO_I2V else "",
    )


class DeriveEventsTests(unittest.TestCase):
    def test_cuts_at_beat_transitions_skip_first(self):
        tl = Timeline(beats=[
            _beat(BeatMode.STILL_KENBURNS, "push_in", 3.0),
            _beat(BeatMode.STILL_KENBURNS, "pull_back", 3.0),
            _beat(BeatMode.STILL_KENBURNS, "slow_pan_right", 3.0),
        ])
        events = derive_sfx_events(tl)
        # Cut at t=3.0 and t=6.0 — not at t=0.0.
        self.assertEqual(len(events), 2)
        for ev in events:
            self.assertEqual(ev.category, "cut")
            self.assertEqual(ev.intensity, "light")
        self.assertAlmostEqual(events[0].t_seconds, 3.0)
        self.assertAlmostEqual(events[1].t_seconds, 6.0)

    def test_hero_i2v_beat_gets_punch_at_entry_and_heavy_cut_on_exit(self):
        tl = Timeline(beats=[
            _beat(BeatMode.STILL_KENBURNS, "push_in", 3.0),
            _beat(BeatMode.HERO_I2V, "subtle_dolly_in", 4.0),
            _beat(BeatMode.STILL_KENBURNS, "slow_pan_right", 3.0),
        ])
        events = derive_sfx_events(tl)
        # At t=3.0: punch on hero entry. The cut-on-enter would land at
        # the same timestamp and is suppressed by the 0.25 s min-gap
        # dedup so the punch reads cleanly.
        # At t=7.0: heavy cut out of hero (prev beat was HERO_I2V).
        cats = [(e.category, e.intensity, round(e.t_seconds, 2))
                for e in events]
        self.assertIn(("punch", "heavy", 3.0), cats)
        self.assertIn(("cut", "heavy", 7.0), cats)
        # No cut at t=3.0 — gap-dedupe suppressed it.
        self.assertNotIn(("cut", "light", 3.0), cats)
        self.assertNotIn(("cut", "heavy", 3.0), cats)

    def test_cuts_deduped_within_min_gap(self):
        """Two beats closer than 0.25s apart would produce overlapping
        cut events — the second must be suppressed."""
        tl = Timeline(beats=[
            _beat(BeatMode.STILL_KENBURNS, "push_in", 0.1),
            _beat(BeatMode.STILL_KENBURNS, "pull_back", 0.1),
            _beat(BeatMode.STILL_KENBURNS, "slow_pan_right", 0.1),
        ])
        events = derive_sfx_events(tl)
        # Only one cut should survive the <0.25s gap filter.
        cuts = [e for e in events if e.category == "cut"]
        self.assertEqual(len(cuts), 1)
        self.assertAlmostEqual(cuts[0].t_seconds, 0.1)

    def test_single_beat_timeline_has_no_events(self):
        tl = Timeline(beats=[_beat(BeatMode.STILL_KENBURNS, "push_in", 3.0)])
        events = derive_sfx_events(tl)
        self.assertEqual(events, [])


class SfxMixStageRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vesper-sfx-"))
        self.voice_path = self.tmp / "voice.mp3"
        self.voice_path.write_bytes(b"mp3-stub")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _job(self) -> VesperJob:
        tl = Timeline(beats=[
            _beat(BeatMode.STILL_KENBURNS, "push_in", 3.0),
            _beat(BeatMode.STILL_PARALLAX, "push_in_2d", 3.0),
            _beat(BeatMode.STILL_KENBURNS, "pull_back", 3.0),
        ])
        return VesperJob(
            topic_title="x",
            subreddit="n",
            job_id="abc123",
            story_script="x",
            voice_path=str(self.voice_path),
            voice_duration_s=9.0,
            timeline=tl,
            beat_count=3,
        )

    def test_run_produces_mixed_file_and_swaps_voice_path(self):
        calls: List[dict] = []

        def _mixer(*, audio_path, sfx_events, output_path, seed, pack):
            calls.append({
                "audio_path": audio_path,
                "sfx_events": list(sfx_events),
                "output_path": output_path,
                "seed": seed,
                "pack": pack,
            })
            Path(output_path).write_bytes(b"mixed-mp3")
            return output_path

        stage = SfxMixStage(pack_name="vesper", mixer=_mixer)
        job = self._job()
        result = stage.run(job=job, output_dir=str(self.tmp))
        self.assertTrue(result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["pack"], "vesper")
        self.assertEqual(len(calls[0]["sfx_events"]), 2)  # 2 cuts
        # voice_path swapped
        self.assertTrue(job.voice_path.endswith("abc123_mixed.mp3"))

    def test_no_timeline_no_op(self):
        stage = SfxMixStage(pack_name="vesper", mixer=lambda **kw: None)
        job = VesperJob(
            topic_title="x", subreddit="n", job_id="j",
            story_script="x", voice_path=str(self.voice_path),
        )
        self.assertFalse(stage.run(job=job, output_dir=str(self.tmp)))

    def test_no_voice_no_op(self):
        stage = SfxMixStage(pack_name="vesper", mixer=lambda **kw: None)
        tl = Timeline(beats=[_beat(BeatMode.STILL_KENBURNS, "push_in", 3.0)])
        job = VesperJob(
            topic_title="x", subreddit="n", job_id="j",
            story_script="x", voice_path=None, timeline=tl,
        )
        self.assertFalse(stage.run(job=job, output_dir=str(self.tmp)))

    def test_empty_events_no_op(self):
        """Single-beat timeline derives 0 events → stage no-ops without
        calling the mixer."""
        calls: List[dict] = []

        def _mixer(**kw):
            calls.append(kw)
            return kw["output_path"]

        stage = SfxMixStage(pack_name="vesper", mixer=_mixer)
        tl = Timeline(beats=[_beat(BeatMode.STILL_KENBURNS, "push_in", 3.0)])
        job = VesperJob(
            topic_title="x", subreddit="n", job_id="j",
            story_script="x", voice_path=str(self.voice_path),
            timeline=tl,
        )
        self.assertFalse(stage.run(job=job, output_dir=str(self.tmp)))
        self.assertEqual(calls, [])

    def test_missing_pack_degrades_to_raw_voice(self):
        """Pack .wav files absent is the common pre-launch case. Mixer
        raises FileNotFoundError; stage returns False and leaves
        voice_path untouched."""
        def _mixer(**kw):
            raise FileNotFoundError("no .wav in assets/vesper/sfx/")

        stage = SfxMixStage(pack_name="vesper", mixer=_mixer)
        job = self._job()
        original_voice = job.voice_path
        self.assertFalse(stage.run(job=job, output_dir=str(self.tmp)))
        self.assertEqual(job.voice_path, original_voice)

    def test_mixer_error_does_not_fail_short(self):
        """ffmpeg or other subprocess error — stage swallows and returns
        False so the pipeline continues with raw voice."""
        def _mixer(**kw):
            raise RuntimeError("ffmpeg exit 1")

        stage = SfxMixStage(pack_name="vesper", mixer=_mixer)
        job = self._job()
        original_voice = job.voice_path
        self.assertFalse(stage.run(job=job, output_dir=str(self.tmp)))
        self.assertEqual(job.voice_path, original_voice)

    def test_deterministic_seed_per_job_id(self):
        """Same job_id → same seed (so retries pick identical SFX)."""
        seeds: List[int] = []

        def _mixer(**kw):
            seeds.append(kw["seed"])
            Path(kw["output_path"]).write_bytes(b"mp3")
            return kw["output_path"]

        stage = SfxMixStage(pack_name="vesper", mixer=_mixer)
        job1 = self._job()
        job2 = self._job()
        stage.run(job=job1, output_dir=str(self.tmp))
        stage.run(job=job2, output_dir=str(self.tmp))
        self.assertEqual(seeds[0], seeds[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
