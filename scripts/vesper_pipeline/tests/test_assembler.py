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
        self.effects: List[dict] = []

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

    def with_effects(self, effects):
        for e in effects:
            if isinstance(e, dict):
                self.effects.append(e)
            else:
                # Record real MoviePy FX objects by class name so tests
                # assert on "FadeIn"/"FadeOut" the same way they'd assert
                # on {"kind": "fade_in"} markers.
                cls = type(e).__name__
                kind = "fade_in" if cls.lower() == "fadein" else (
                    "fade_out" if cls.lower() == "fadeout" else cls.lower()
                )
                self.effects.append({"kind": kind, "class": cls})
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


class CaptionBurnTests(unittest.TestCase):
    """When caption_style + job.caption_segments are present, the
    assembler runs a second FFmpeg pass to burn ASS subtitles."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="vesper-cap-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _job_with_captions(self):
        tl = _mixed_timeline()
        job = _job_for_timeline(tl, self.tmp)
        job.caption_segments = [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.5, "end": 1.0},
        ]
        return job

    def _runner_stub(self, *, rc: int = 0, stderr: bytes = b""):
        class _R:
            def __init__(self):
                self.calls = []

            def __call__(self, cmd, capture_output=False, **kw):
                self.calls.append(cmd)

                class _Result:
                    returncode = rc
                    stdout = b""

                _Result.stderr = stderr
                # Simulate FFmpeg having written the final output.
                out_path = cmd[-1]
                Path(out_path).write_bytes(b"final mp4 with captions")
                return _Result()

        return _R()

    def _style(self):
        from vesper_pipeline.captions import CaptionStyle
        return CaptionStyle(
            primary="#E8E2D4",
            accent="#8B1A1A",
            shadow="#2C2826",
            font_name="CormorantGaramond-Bold",
        )

    def test_burn_pass_invoked_when_segments_and_style_present(self):
        runner = self._runner_stub()
        factory = _FakeClipFactory()
        asm = VesperAssembler(
            clip_factory=factory,
            caption_style=self._style(),
            ass_burn_runner=runner,
        )
        out = str(self.tmp / "final.mp4")
        asm.assemble(job=self._job_with_captions(), output_path=out)

        self.assertEqual(len(runner.calls), 1)
        cmd = runner.calls[0]
        self.assertTrue(
            cmd[0].endswith("ffmpeg") or "ffmpeg" in cmd[0],
            f"expected an ffmpeg binary, got {cmd[0]!r}",
        )
        self.assertEqual(cmd[-1], out)
        vf_idx = cmd.index("-vf")
        self.assertTrue(cmd[vf_idx + 1].startswith("ass="))

    def test_no_burn_when_style_omitted(self):
        runner = self._runner_stub()
        factory = _FakeClipFactory()
        asm = VesperAssembler(
            clip_factory=factory,
            caption_style=None,
            ass_burn_runner=runner,
        )
        asm.assemble(
            job=self._job_with_captions(),
            output_path=str(self.tmp / "final.mp4"),
        )
        self.assertEqual(len(runner.calls), 0)

    def test_no_burn_when_segments_empty(self):
        runner = self._runner_stub()
        factory = _FakeClipFactory()
        asm = VesperAssembler(
            clip_factory=factory,
            caption_style=self._style(),
            ass_burn_runner=runner,
        )
        tl = _mixed_timeline()
        job = _job_for_timeline(tl, self.tmp)
        job.caption_segments = []  # explicit empty
        asm.assemble(job=job, output_path=str(self.tmp / "final.mp4"))
        self.assertEqual(len(runner.calls), 0)

    def test_ffmpeg_nonzero_becomes_assembly_error(self):
        runner = self._runner_stub(rc=1, stderr=b"ffmpeg: bad filter")
        factory = _FakeClipFactory()
        asm = VesperAssembler(
            clip_factory=factory,
            caption_style=self._style(),
            ass_burn_runner=runner,
        )
        with self.assertRaises(AssemblyError) as cm:
            asm.assemble(
                job=self._job_with_captions(),
                output_path=str(self.tmp / "final.mp4"),
            )
        self.assertIn("ASS burn", str(cm.exception))
        self.assertIn("bad filter", str(cm.exception))

    def test_staging_file_cleaned_up_on_success(self):
        runner = self._runner_stub()
        factory = _FakeClipFactory()
        asm = VesperAssembler(
            clip_factory=factory,
            caption_style=self._style(),
            ass_burn_runner=runner,
        )
        out = str(self.tmp / "final.mp4")
        asm.assemble(job=self._job_with_captions(), output_path=out)
        staging = Path(out + ".nocap.mp4")
        self.assertFalse(staging.exists(), "staging file must be cleaned up")


class OverlayPassTests(unittest.TestCase):
    """Overlay pack runs as an FFmpeg pass between MoviePy write and
    (optional) caption burn. Captions must land ON TOP of overlays."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="vesper-ov-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _job(self):
        tl = _mixed_timeline()
        return _job_for_timeline(tl, self.tmp)

    def _fake_overlay_burner(self, *, applied: bool = True, raise_exc=None):
        class _Burner:
            def __init__(self):
                self.calls: List[dict] = []

            def apply(self, *, input_mp4, output_mp4, pack):
                self.calls.append({
                    "input_mp4": input_mp4,
                    "output_mp4": output_mp4,
                    "pack": pack,
                })
                if raise_exc is not None:
                    raise raise_exc
                if applied:
                    Path(output_mp4).write_bytes(b"overlaid mp4")
                return applied

        return _Burner()

    def _fake_ass_runner(self):
        class _R:
            def __init__(self):
                self.calls: List[list] = []

            def __call__(self, cmd, capture_output=False, **kw):
                self.calls.append(list(cmd))

                class _Res:
                    returncode = 0
                    stdout = b""
                    stderr = b""

                Path(cmd[-1]).write_bytes(b"captioned mp4")
                return _Res()

        return _R()

    def _style(self):
        from vesper_pipeline.captions import CaptionStyle
        return CaptionStyle(
            primary="#E8E2D4", accent="#8B1A1A", shadow="#2C2826",
            font_name="CormorantGaramond-Bold",
        )

    def test_overlay_only_runs_when_pack_provided(self):
        factory = _FakeClipFactory()
        burner = self._fake_overlay_burner()
        asm = VesperAssembler(
            clip_factory=factory,
            overlay_pack="fake-pack-sentinel",
            overlay_burner=burner,
        )
        out = str(self.tmp / "final.mp4")
        asm.assemble(job=self._job(), output_path=out)
        self.assertEqual(len(burner.calls), 1)
        self.assertEqual(burner.calls[0]["pack"], "fake-pack-sentinel")
        # Output path written — overlay output promoted to final.
        self.assertTrue(Path(out).exists())

    def test_no_overlay_when_pack_none(self):
        factory = _FakeClipFactory()
        burner = self._fake_overlay_burner()
        asm = VesperAssembler(
            clip_factory=factory,
            overlay_pack=None,
            overlay_burner=burner,
        )
        asm.assemble(
            job=self._job(),
            output_path=str(self.tmp / "final.mp4"),
        )
        self.assertEqual(burner.calls, [])

    def test_overlay_then_captions_chained(self):
        """With both overlays + captions, overlay runs first, then
        caption burn writes the final output. Captions sit on top."""
        factory = _FakeClipFactory()
        overlay = self._fake_overlay_burner()
        ass_runner = self._fake_ass_runner()
        job = self._job()
        job.caption_segments = [
            {"word": "hi", "start": 0.0, "end": 0.3},
        ]
        asm = VesperAssembler(
            clip_factory=factory,
            overlay_pack="sentinel",
            overlay_burner=overlay,
            caption_style=self._style(),
            ass_burn_runner=ass_runner,
        )
        out = str(self.tmp / "final.mp4")
        asm.assemble(job=job, output_path=out)

        self.assertEqual(len(overlay.calls), 1)
        self.assertEqual(len(ass_runner.calls), 1)

        # Caption pass reads from the overlay's output (stage1), not
        # the raw MoviePy stage0. Its -i argument proves the ordering.
        ass_cmd = ass_runner.calls[0]
        in_idx = ass_cmd.index("-i")
        caption_input = ass_cmd[in_idx + 1]
        self.assertIn(".stage1.mp4", caption_input)

    def test_zero_layer_pack_falls_through_to_captions(self):
        """If overlay burner returns False (pack had no wavs), caption
        burn still runs against the raw MoviePy output."""
        factory = _FakeClipFactory()
        overlay = self._fake_overlay_burner(applied=False)
        ass_runner = self._fake_ass_runner()
        job = self._job()
        job.caption_segments = [
            {"word": "hi", "start": 0.0, "end": 0.3},
        ]
        asm = VesperAssembler(
            clip_factory=factory,
            overlay_pack="sentinel",
            overlay_burner=overlay,
            caption_style=self._style(),
            ass_burn_runner=ass_runner,
        )
        asm.assemble(
            job=job,
            output_path=str(self.tmp / "final.mp4"),
        )
        # Overlay attempted but returned False → caption input is stage0
        self.assertEqual(len(overlay.calls), 1)
        self.assertEqual(len(ass_runner.calls), 1)
        ass_cmd = ass_runner.calls[0]
        caption_input = ass_cmd[ass_cmd.index("-i") + 1]
        self.assertIn(".stage0.mp4", caption_input)
        self.assertNotIn(".stage1.mp4", caption_input)

    def test_overlay_without_captions_promotes_overlay_output(self):
        """Pack applied + no captions → overlay output becomes final."""
        factory = _FakeClipFactory()
        overlay = self._fake_overlay_burner()
        asm = VesperAssembler(
            clip_factory=factory,
            overlay_pack="sentinel",
            overlay_burner=overlay,
        )
        out = str(self.tmp / "final.mp4")
        asm.assemble(job=self._job(), output_path=out)
        self.assertTrue(Path(out).exists())
        # Staging files cleaned up.
        self.assertFalse(Path(out + ".stage0.mp4").exists())
        self.assertFalse(Path(out + ".stage1.mp4").exists())


class ZoomBellPassTests(unittest.TestCase):
    """Zoom-bell pass sits between overlays and captions. Runs only
    when enable_zoom_bells is True AND job.keyword_punches is non-empty."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="vesper-zoom-asm-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _job_with_punches(self):
        from vesper_pipeline.keyword_punch import KeywordPunch
        tl = _mixed_timeline()
        job = _job_for_timeline(tl, self.tmp)
        job.keyword_punches = [
            KeywordPunch(t_seconds=1.5, word="DAVID", reason="capitalized"),
            KeywordPunch(t_seconds=8.0, word="silence.", reason="end_of_sentence"),
        ]
        return job

    def _zoom_burner(self, *, applied: bool = True):
        class _Burner:
            def __init__(self):
                self.calls: List[dict] = []

            def apply(self, *, input_mp4, output_mp4, punches):
                self.calls.append({
                    "input_mp4": input_mp4,
                    "output_mp4": output_mp4,
                    "punches": list(punches),
                })
                if applied:
                    Path(output_mp4).write_bytes(b"zoomed mp4")
                return applied

        return _Burner()

    def test_zoom_fires_when_punches_and_enabled(self):
        factory = _FakeClipFactory()
        burner = self._zoom_burner()
        asm = VesperAssembler(
            clip_factory=factory,
            zoom_bell_burner=burner,
            enable_zoom_bells=True,
        )
        out = str(self.tmp / "final.mp4")
        asm.assemble(job=self._job_with_punches(), output_path=out)
        self.assertEqual(len(burner.calls), 1)
        self.assertEqual(len(burner.calls[0]["punches"]), 2)

    def test_zoom_skipped_when_disabled(self):
        factory = _FakeClipFactory()
        burner = self._zoom_burner()
        asm = VesperAssembler(
            clip_factory=factory,
            zoom_bell_burner=burner,
            enable_zoom_bells=False,
        )
        asm.assemble(
            job=self._job_with_punches(),
            output_path=str(self.tmp / "final.mp4"),
        )
        self.assertEqual(burner.calls, [])

    def test_zoom_skipped_when_no_punches(self):
        factory = _FakeClipFactory()
        burner = self._zoom_burner()
        asm = VesperAssembler(
            clip_factory=factory,
            zoom_bell_burner=burner,
            enable_zoom_bells=True,
        )
        tl = _mixed_timeline()
        job = _job_for_timeline(tl, self.tmp)
        # No keyword_punches on job.
        asm.assemble(job=job, output_path=str(self.tmp / "final.mp4"))
        self.assertEqual(burner.calls, [])

    def test_zoom_between_overlays_and_captions_chains_correctly(self):
        """With overlays + zoom + captions, chain is:
        stage0 → stage1 (overlay) → stage2 (zoom) → final (caption)."""
        from vesper_pipeline.captions import CaptionStyle

        factory = _FakeClipFactory()

        class _OverlayBurner:
            def __init__(self):
                self.calls: List[dict] = []

            def apply(self, *, input_mp4, output_mp4, pack):
                self.calls.append({
                    "input_mp4": input_mp4, "output_mp4": output_mp4,
                })
                Path(output_mp4).write_bytes(b"ov")
                return True

        overlay = _OverlayBurner()
        zoom = self._zoom_burner()

        class _AssRunner:
            def __init__(self):
                self.calls: List[list] = []

            def __call__(self, cmd, capture_output=False, **kw):
                self.calls.append(list(cmd))

                class _R:
                    returncode = 0
                    stdout = b""
                    stderr = b""

                Path(cmd[-1]).write_bytes(b"captioned")
                return _R()

        ass_runner = _AssRunner()

        job = self._job_with_punches()
        job.caption_segments = [{"word": "hi", "start": 0.0, "end": 0.3}]
        asm = VesperAssembler(
            clip_factory=factory,
            overlay_pack="sentinel",
            overlay_burner=overlay,
            zoom_bell_burner=zoom,
            caption_style=CaptionStyle(
                primary="#E8E2D4", accent="#8B1A1A", shadow="#2C2826",
                font_name="CormorantGaramond-Bold",
            ),
            ass_burn_runner=ass_runner,
        )
        out = str(self.tmp / "final.mp4")
        asm.assemble(job=job, output_path=out)

        # Overlay reads stage0, writes stage1.
        self.assertIn(".stage0.mp4", overlay.calls[0]["input_mp4"])
        self.assertIn(".stage1.mp4", overlay.calls[0]["output_mp4"])
        # Zoom reads stage1, writes stage2.
        self.assertIn(".stage1.mp4", zoom.calls[0]["input_mp4"])
        self.assertIn(".stage2.mp4", zoom.calls[0]["output_mp4"])
        # Caption reads stage2.
        caption_in = ass_runner.calls[0][ass_runner.calls[0].index("-i") + 1]
        self.assertIn(".stage2.mp4", caption_in)

    def test_zero_punches_but_enabled_falls_through(self):
        """Enabled + empty punches still no-ops (burner returns False)."""
        factory = _FakeClipFactory()
        burner = self._zoom_burner(applied=False)  # applied=False won't fire
        asm = VesperAssembler(
            clip_factory=factory,
            zoom_bell_burner=burner,
            enable_zoom_bells=True,
        )
        tl = _mixed_timeline()
        job = _job_for_timeline(tl, self.tmp)
        # Empty keyword_punches — zoom check short-circuits, burner never called.
        asm.assemble(job=job, output_path=str(self.tmp / "final.mp4"))
        self.assertEqual(burner.calls, [])


class SceneFadeTests(unittest.TestCase):
    """Dip-to-black on scene change (Key Decision #10 transition vocab).

    Fades fire when consecutive beats have different non-empty tags.
    Missing tags never trigger fades — graceful fallback when the
    timeline planner leaves tags blank."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="vesper-fade-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _beats_with_tags(self, tags: list[str]) -> list:
        """Build Kenburns-only beats with the given tag sequence."""
        motions = ["push_in", "pull_back", "slow_pan_left", "slow_pan_right"]
        return [
            Beat(
                mode=BeatMode.STILL_KENBURNS,
                motion_hint=motions[i % 4],  # type: ignore[arg-type]
                duration_s=3.0,
                shot_class="interior",  # type: ignore[arg-type]
                prompt=f"beat {i}",
                tag=tags[i],
            )
            for i in range(len(tags))
        ]

    def _job_for_beats(self, beats) -> VesperJob:
        voice = self.tmp / "v.mp3"
        voice.write_bytes(b"mp3")
        stills = []
        for i in range(len(beats)):
            p = self.tmp / f"still_{i:03d}.png"
            p.write_bytes(b"png")
            stills.append(str(p))
        tl = Timeline(beats=beats)
        return VesperJob(
            topic_title="x", subreddit="n", job_id="j",
            story_script="x",
            voice_path=str(voice), voice_duration_s=tl.total_duration_s,
            still_paths=stills,
            parallax_paths=[], i2v_paths=[],
            timeline=tl, beat_count=tl.count,
        )

    def test_fade_applied_on_tag_transition(self):
        beats = self._beats_with_tags([
            "hook", "hook", "setup", "setup",
        ])
        factory = _FakeClipFactory()
        asm = VesperAssembler(
            clip_factory=factory,
            enable_scene_fades=True,
        )
        asm.assemble(
            job=self._job_for_beats(beats),
            output_path=str(self.tmp / "final.mp4"),
        )

        image_clips = [c for c in factory.created if c.kind == "image"]
        self.assertEqual(len(image_clips), 4)
        # Boundary at beats[1]→beats[2]: fade_out on beats[1], fade_in on beats[2].
        self.assertTrue(any(
            e.get("kind") == "fade_out" for e in image_clips[1].effects
        ), "fade_out not applied to beats[1] at scene boundary")
        self.assertTrue(any(
            e.get("kind") == "fade_in" for e in image_clips[2].effects
        ), "fade_in not applied to beats[2] at scene boundary")
        # Non-boundary beats (0→1, 2→3) don't carry fades.
        self.assertFalse(any(
            e.get("kind") in ("fade_in", "fade_out")
            for e in image_clips[0].effects
        ))
        self.assertFalse(any(
            e.get("kind") == "fade_in" for e in image_clips[1].effects
        ))

    def test_fade_skipped_when_tags_empty(self):
        """All-blank tags is the timeline-planner-didn't-emit-tags
        case. No fades should fire."""
        beats = self._beats_with_tags(["", "", "", ""])
        factory = _FakeClipFactory()
        asm = VesperAssembler(
            clip_factory=factory,
            enable_scene_fades=True,
        )
        asm.assemble(
            job=self._job_for_beats(beats),
            output_path=str(self.tmp / "final.mp4"),
        )
        image_clips = [c for c in factory.created if c.kind == "image"]
        for c in image_clips:
            self.assertFalse(any(
                e.get("kind") in ("fade_in", "fade_out")
                for e in c.effects
            ), f"unexpected fade on blank-tag beat")

    def test_fade_skipped_when_disabled(self):
        beats = self._beats_with_tags(["hook", "setup"])
        factory = _FakeClipFactory()
        asm = VesperAssembler(
            clip_factory=factory,
            enable_scene_fades=False,
        )
        asm.assemble(
            job=self._job_for_beats(beats),
            output_path=str(self.tmp / "final.mp4"),
        )
        image_clips = [c for c in factory.created if c.kind == "image"]
        for c in image_clips:
            self.assertFalse(any(
                e.get("kind") in ("fade_in", "fade_out")
                for e in c.effects
            ))

    def test_partial_tags_mid_timeline(self):
        """Some beats tagged, others blank — fade only fires when BOTH
        beats at the boundary have non-empty, distinct tags."""
        beats = self._beats_with_tags(["hook", "", "setup", "setup"])
        factory = _FakeClipFactory()
        asm = VesperAssembler(
            clip_factory=factory,
            enable_scene_fades=True,
        )
        asm.assemble(
            job=self._job_for_beats(beats),
            output_path=str(self.tmp / "final.mp4"),
        )
        image_clips = [c for c in factory.created if c.kind == "image"]
        # Boundary 0→1: prev="hook", cur="" → no fade
        # Boundary 1→2: prev="", cur="setup" → no fade
        # Boundary 2→3: both "setup" → no fade
        for c in image_clips:
            self.assertFalse(any(
                e.get("kind") in ("fade_in", "fade_out")
                for e in c.effects
            ), "no fade expected when either side tag is blank or equal")


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
