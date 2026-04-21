"""Tests for :class:`VesperAssembler`.

Uses a fake MoviePy clip-factory so tests run without MoviePy
installed. Verifies beat routing, cursor advance, audio mix, and
error paths.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, List

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from still_gen._types import Beat, BeatMode, Timeline  # noqa: E402

from vesper_pipeline._types import VesperJob  # noqa: E402
from vesper_pipeline.assembler import (  # noqa: E402
    AssemblyError,
    VesperAssembler,
)


# ─── Fake MoviePy ──────────────────────────────────────────────────────────


class _FakeClip:
    def __init__(self, kind: str, source: str):
        self.kind = kind
        self.source = source
        self.duration = 1.0
        self.audio = None
        self.resized_calls: List[Any] = []
        self.duration_calls: List[float] = []
        self.write_calls: List[dict] = []

    def with_duration(self, s):
        self.duration = s
        self.duration_calls.append(s)
        return self

    def resized(self, *args, **kw):
        self.resized_calls.append({"args": args, "kw": kw})
        return self

    def with_audio(self, audio):
        self.audio = audio
        return self

    def write_videofile(self, path, **kw):
        self.write_calls.append({"path": path, **kw})
        Path(path).write_bytes(b"fake mp4")


class _FakeAudio:
    def __init__(self, path):
        self.source = path


class _FakeClipFactory:
    def __init__(self):
        self.created: List[_FakeClip] = []

    def ImageClip(self, path):
        c = _FakeClip("image", path)
        self.created.append(c)
        return c

    def VideoFileClip(self, path):
        c = _FakeClip("video", path)
        self.created.append(c)
        return c

    def AudioFileClip(self, path):
        return _FakeAudio(path)

    def concatenate_videoclips(self, clips):
        concat = _FakeClip("concat", "")
        concat.duration = sum(c.duration for c in clips)
        concat._inputs = clips  # type: ignore[attr-defined]
        self.created.append(concat)
        return concat


# ─── Fixtures ──────────────────────────────────────────────────────────────


def _beat(mode: BeatMode, motion: str = "push_in", duration: float = 3.0,
          prompt: str = "x") -> Beat:
    return Beat(
        mode=mode,
        motion_hint=motion,  # type: ignore[arg-type]
        duration_s=duration,
        shot_class="interior",  # type: ignore[arg-type]
        prompt=prompt if mode != BeatMode.HERO_I2V else "",
    )


def _mixed_timeline() -> Timeline:
    """6 beats: KB, KB, PAR, KB, I2V, KB."""
    return Timeline(beats=[
        _beat(BeatMode.STILL_KENBURNS, "push_in", 3.0),
        _beat(BeatMode.STILL_KENBURNS, "pull_back", 3.2),
        _beat(BeatMode.STILL_PARALLAX, "push_in_2d", 3.5),
        _beat(BeatMode.STILL_KENBURNS, "slow_pan_right", 2.8),
        _beat(BeatMode.HERO_I2V, "subtle_dolly_in", 4.0),
        _beat(BeatMode.STILL_KENBURNS, "push_in", 3.0),
    ])


def _job_for_timeline(tl: Timeline, tmpdir: Path) -> VesperJob:
    """Build a VesperJob with still_paths aligned to beats, one parallax
    clip, one i2v clip, and a voice file stub."""
    stills = []
    for i, beat in enumerate(tl.beats):
        if beat.mode == BeatMode.HERO_I2V:
            stills.append("")  # hero beats skip Flux
        else:
            p = tmpdir / f"still_{i:03d}.png"
            p.write_bytes(b"png-stub")
            stills.append(str(p))

    parallax_path = tmpdir / "parallax_001.mp4"
    parallax_path.write_bytes(b"mp4-stub")
    i2v_path = tmpdir / "i2v_001.mp4"
    i2v_path.write_bytes(b"mp4-stub")
    voice_path = tmpdir / "voice.mp3"
    voice_path.write_bytes(b"mp3-stub")

    return VesperJob(
        topic_title="x",
        subreddit="nosleep",
        job_id="job-test",
        story_script="x",
        voice_path=str(voice_path),
        voice_duration_s=tl.total_duration_s,
        still_paths=stills,
        parallax_paths=[str(parallax_path)],
        i2v_paths=[str(i2v_path)],
        timeline=tl,
        beat_count=tl.count,
    )


# ─── Tests ─────────────────────────────────────────────────────────────────


class AssembleHappyPathTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="vesper-asm-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_beat_routing_picks_correct_clip_type(self):
        factory = _FakeClipFactory()
        tl = _mixed_timeline()
        job = _job_for_timeline(tl, self.tmp)
        asm = VesperAssembler(clip_factory=factory)
        out = str(self.tmp / "final.mp4")

        result = asm.assemble(job=job, output_path=out)
        self.assertEqual(result, out)

        # Count each clip-kind in created order. The concat clip is
        # created last, then final (concat after audio attach).
        created_kinds = [c.kind for c in factory.created if c.kind != "concat"]
        # 4 KB + 1 parallax + 1 i2v = 4 image + 2 video
        self.assertEqual(created_kinds.count("image"), 4)
        self.assertEqual(created_kinds.count("video"), 2)

    def test_parallax_and_i2v_cursors_advance_independently(self):
        """Two parallax beats + two i2v beats — each cursor advances only
        within its kind."""
        beats = [
            _beat(BeatMode.STILL_PARALLAX, "push_in_2d", 3.0),
            _beat(BeatMode.HERO_I2V, "subtle_dolly_in", 3.0),
            _beat(BeatMode.STILL_PARALLAX, "orbit_slight", 3.0),
            _beat(BeatMode.HERO_I2V, "breathing_mist", 3.0),
        ]
        tl = Timeline(beats=beats)

        # Build job manually — need two parallax + two i2v.
        stills = ["", "", "", ""]
        parallax = []
        for i in range(2):
            p = self.tmp / f"par_{i}.mp4"
            p.write_bytes(b"mp4")
            parallax.append(str(p))
        i2v = []
        for i in range(2):
            p = self.tmp / f"i2v_{i}.mp4"
            p.write_bytes(b"mp4")
            i2v.append(str(p))
        voice = self.tmp / "v.mp3"
        voice.write_bytes(b"mp3")

        job = VesperJob(
            topic_title="x", subreddit="n", job_id="j",
            story_script="x",
            voice_path=str(voice), voice_duration_s=12.0,
            still_paths=stills,
            parallax_paths=parallax,
            i2v_paths=i2v,
            timeline=tl,
            beat_count=tl.count,
        )

        factory = _FakeClipFactory()
        asm = VesperAssembler(clip_factory=factory)
        asm.assemble(job=job, output_path=str(self.tmp / "final.mp4"))

        # Sources of video clips, in creation order, must be:
        # par_0, i2v_0, par_1, i2v_1.
        video_clips = [
            c for c in factory.created if c.kind == "video"
        ]
        sources = [Path(c.source).name for c in video_clips]
        self.assertEqual(sources, ["par_0.mp4", "i2v_0.mp4",
                                   "par_1.mp4", "i2v_1.mp4"])

    def test_audio_attached_to_final_concat(self):
        factory = _FakeClipFactory()
        tl = _mixed_timeline()
        job = _job_for_timeline(tl, self.tmp)
        asm = VesperAssembler(clip_factory=factory)
        asm.assemble(job=job, output_path=str(self.tmp / "final.mp4"))

        # Find the concat clip — it's the one whose audio got attached.
        concat = next(c for c in factory.created if c.kind == "concat")
        self.assertIsNotNone(concat.audio)
        self.assertEqual(concat.audio.source, job.voice_path)  # type: ignore[attr-defined]

    def test_write_videofile_invoked_with_path_and_fps(self):
        factory = _FakeClipFactory()
        tl = _mixed_timeline()
        job = _job_for_timeline(tl, self.tmp)
        asm = VesperAssembler(clip_factory=factory, fps=24)
        out_path = str(self.tmp / "final.mp4")
        asm.assemble(job=job, output_path=out_path)

        concat = next(c for c in factory.created if c.kind == "concat")
        self.assertEqual(len(concat.write_calls), 1)
        self.assertEqual(concat.write_calls[0]["path"], out_path)
        self.assertEqual(concat.write_calls[0]["fps"], 24)


class AssembleErrorPathTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="vesper-asm-err-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_timeline_raises(self):
        job = VesperJob(
            topic_title="x", subreddit="n", job_id="j",
            story_script="x", voice_path=str(self.tmp / "v.mp3"),
        )
        asm = VesperAssembler(clip_factory=_FakeClipFactory())
        with self.assertRaises(AssemblyError) as cm:
            asm.assemble(job=job, output_path=str(self.tmp / "final.mp4"))
        self.assertIn("timeline", str(cm.exception).lower())

    def test_missing_voice_path_raises(self):
        tl = _mixed_timeline()
        job = VesperJob(
            topic_title="x", subreddit="n", job_id="j",
            story_script="x", voice_path=None,
            timeline=tl, beat_count=tl.count,
        )
        asm = VesperAssembler(clip_factory=_FakeClipFactory())
        with self.assertRaises(AssemblyError) as cm:
            asm.assemble(job=job, output_path=str(self.tmp / "final.mp4"))
        self.assertIn("voice", str(cm.exception).lower())

    def test_parallax_cursor_exceeds_available_raises(self):
        """Timeline has 2 parallax beats but job.parallax_paths has 1."""
        tl = Timeline(beats=[
            _beat(BeatMode.STILL_PARALLAX, "push_in_2d", 3.0),
            _beat(BeatMode.STILL_PARALLAX, "orbit_slight", 3.0),
        ])
        voice = self.tmp / "v.mp3"
        voice.write_bytes(b"mp3")
        par = self.tmp / "par.mp4"
        par.write_bytes(b"mp4")
        job = VesperJob(
            topic_title="x", subreddit="n", job_id="j",
            story_script="x",
            voice_path=str(voice), voice_duration_s=6.0,
            still_paths=["", ""],
            parallax_paths=[str(par)],
            i2v_paths=[],
            timeline=tl, beat_count=2,
        )
        asm = VesperAssembler(clip_factory=_FakeClipFactory())
        with self.assertRaises(AssemblyError) as cm:
            asm.assemble(job=job, output_path=str(self.tmp / "final.mp4"))
        self.assertIn("beat 1", str(cm.exception))
        self.assertIn("cursor", str(cm.exception))

    def test_kenburns_missing_still_raises(self):
        tl = Timeline(beats=[
            _beat(BeatMode.STILL_KENBURNS, "push_in", 3.0),
        ])
        voice = self.tmp / "v.mp3"
        voice.write_bytes(b"mp3")
        job = VesperJob(
            topic_title="x", subreddit="n", job_id="j",
            story_script="x",
            voice_path=str(voice), voice_duration_s=3.0,
            still_paths=[""],  # empty path for the only beat
            parallax_paths=[],
            i2v_paths=[],
            timeline=tl, beat_count=1,
        )
        asm = VesperAssembler(clip_factory=_FakeClipFactory())
        with self.assertRaises(AssemblyError) as cm:
            asm.assemble(job=job, output_path=str(self.tmp / "final.mp4"))
        self.assertIn("missing still", str(cm.exception).lower())


class KenBurnsDurationTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="vesper-kb-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_kenburns_beat_applies_duration_from_beat(self):
        tl = Timeline(beats=[
            _beat(BeatMode.STILL_KENBURNS, "push_in", duration=4.2),
        ])
        voice = self.tmp / "v.mp3"
        voice.write_bytes(b"mp3")
        still = self.tmp / "s.png"
        still.write_bytes(b"png")
        job = VesperJob(
            topic_title="x", subreddit="n", job_id="j",
            story_script="x",
            voice_path=str(voice), voice_duration_s=4.2,
            still_paths=[str(still)],
            parallax_paths=[], i2v_paths=[],
            timeline=tl, beat_count=1,
        )
        factory = _FakeClipFactory()
        asm = VesperAssembler(clip_factory=factory)
        asm.assemble(job=job, output_path=str(self.tmp / "final.mp4"))

        img_clip = next(c for c in factory.created if c.kind == "image")
        self.assertEqual(img_clip.duration_calls, [4.2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
