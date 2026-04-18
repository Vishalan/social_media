"""Unit A3 — tests for the combined engagement-layer final ffmpeg pass.

The engagement pass is the single re-encode that folds zoom-punches,
ASS caption burn-in, and SFX-mixed audio into one ffmpeg invocation.
These tests mock ``subprocess.run`` so no real ffmpeg is invoked.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make scripts/ importable as a package root.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

try:
    from video_edit.video_editor import (  # type: ignore[import-not-found]
        VideoEditor,
        _build_zoom_expression,
        _shift_keyword_punches,
        _shift_sfx_events,
    )
    from audio.sfx import SfxEvent  # type: ignore[import-not-found]
    from content_gen.keyword_extractor import KeywordPunch  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    from scripts.video_edit.video_editor import (  # type: ignore[no-redef]
        VideoEditor,
        _build_zoom_expression,
        _shift_keyword_punches,
        _shift_sfx_events,
    )
    from scripts.audio.sfx import SfxEvent  # type: ignore[no-redef]
    from scripts.content_gen.keyword_extractor import KeywordPunch  # type: ignore[no-redef]


# ─── _build_zoom_expression ──────────────────────────────────────────────────


def test_build_zoom_expression_empty_returns_one():
    """Zero punches → literal ``1.0`` so the filter graph is valid."""
    assert _build_zoom_expression([]) == "1.0"


def test_build_zoom_expression_includes_each_punch_timestamp():
    punches = [
        KeywordPunch(word="GPT-5", t_start=1.3, t_end=1.55, intensity="heavy"),
        KeywordPunch(word="40%", t_start=2.2, t_end=2.45, intensity="medium"),
    ]
    expr = _build_zoom_expression(punches)
    # Starts with the baseline 1.0
    assert expr.startswith("1.0")
    # Each t_start appears in the expression.
    assert "1.300" in expr
    assert "2.200" in expr
    # Intensity deltas baked in.
    assert "0.2" in expr  # heavy
    assert "0.15" in expr  # medium
    # Uses sin bell and between() gating.
    assert "sin(" in expr
    assert "between(" in expr


def test_build_zoom_expression_unknown_intensity_defaults_to_medium():
    punches = [KeywordPunch(word="x", t_start=1.0, t_end=1.2, intensity="nuclear")]  # type: ignore[arg-type]
    expr = _build_zoom_expression(punches)
    assert "0.15" in expr  # medium default


# ─── _shift_keyword_punches / _shift_sfx_events ─────────────────────────────


def test_shift_keyword_punches_shifts_all_timestamps():
    punches = [KeywordPunch(word="x", t_start=1.0, t_end=1.2, intensity="medium")]
    shifted = _shift_keyword_punches(punches, 0.5)
    assert shifted[0].t_start == pytest.approx(1.5)
    assert shifted[0].t_end == pytest.approx(1.7)
    assert shifted[0].word == "x"
    assert shifted[0].intensity == "medium"


def test_shift_keyword_punches_zero_offset_noop():
    punches = [KeywordPunch(word="x", t_start=1.0, t_end=1.2, intensity="medium")]
    shifted = _shift_keyword_punches(punches, 0.0)
    assert shifted == punches


def test_shift_sfx_events_shifts_seconds():
    evts = [SfxEvent(t_seconds=2.5, category="cut", intensity="light")]
    shifted = _shift_sfx_events(evts, 0.5)
    assert shifted[0].t_seconds == pytest.approx(3.0)
    assert shifted[0].category == "cut"


# ─── _apply_engagement_pass — ffmpeg invocation shape ────────────────────────


class _FakeRunResult:
    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.args = []


def _tmp_file(suffix: str, content: bytes = b"") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    import os as _os
    _os.close(fd)
    Path(path).write_bytes(content)
    return path


def test_apply_engagement_pass_single_filter_complex_invocation():
    """One subprocess.run call, one filter_complex, with scale+crop+ass."""
    editor = VideoEditor()

    video_path = _tmp_file(".mp4", b"fake")
    voice_path = _tmp_file(".mp3", b"fake")
    ass_path = _tmp_file(".ass", b"fake")

    punches = [
        KeywordPunch(word="GPT-5", t_start=1.3, t_end=1.55, intensity="heavy"),
    ]
    sfx_events = [
        SfxEvent(t_seconds=0.5, category="cut", intensity="light"),
    ]

    # Track every subprocess.run call + command so we can assert the
    # engagement-pass command is the last one emitted.
    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeRunResult(returncode=0)

    # Mock mix_sfx_into_audio so we don't invoke real ffmpeg.
    def _fake_mix(audio_path, sfx_events, output_path, seed=0):
        Path(output_path).write_bytes(b"fake-sfx-track")
        return output_path

    try:
        with patch("video_edit.video_editor.subprocess.run", side_effect=_fake_run), \
             patch("audio.sfx.mix_sfx_into_audio", side_effect=_fake_mix):
            out = editor._apply_engagement_pass(
                video_path=video_path,
                voiceover_path=voice_path,
                ass_path=ass_path,
                keyword_punches=punches,
                sfx_events=sfx_events,
                output_path="/tmp/out_engagement.mp4",
                thumbnail_hold_s=0.0,
            )
        assert out == "/tmp/out_engagement.mp4"

        # Last subprocess.run call is the combined pass.
        combined_cmd = calls[-1]
        assert combined_cmd[-1] == "/tmp/out_engagement.mp4"
        # It is an ffmpeg call.
        assert combined_cmd[0].endswith("ffmpeg") or "ffmpeg" in combined_cmd[0]
        # Two input streams: base video + sfx track.
        cmd_str = " ".join(combined_cmd)
        assert cmd_str.count(" -i ") >= 2
        # filter_complex is present.
        fc_idx = combined_cmd.index("-filter_complex")
        fc_str = combined_cmd[fc_idx + 1]
        # Must contain zoom (scale), crop, and ass components.
        assert "scale=" in fc_str
        assert "crop=1080:1920" in fc_str
        assert "ass=" in fc_str
        # Zoom expression carries the punch timestamp.
        assert "1.300" in fc_str
        # Mapping outputs and re-encoding.
        assert "-map" in combined_cmd
        assert "libx264" in combined_cmd
        assert "aac" in combined_cmd
    finally:
        for p in (video_path, voice_path, ass_path):
            Path(p).unlink(missing_ok=True)


def test_apply_engagement_pass_no_sfx_feeds_voice_directly():
    """With no SFX events, the audio input is the voiceover, not an sfx track."""
    editor = VideoEditor()

    video_path = _tmp_file(".mp4", b"fake")
    voice_path = _tmp_file(".mp3", b"fake")

    punches = [
        KeywordPunch(word="x", t_start=1.0, t_end=1.2, intensity="medium"),
    ]

    calls: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeRunResult(returncode=0)

    try:
        with patch("video_edit.video_editor.subprocess.run", side_effect=_fake_run):
            editor._apply_engagement_pass(
                video_path=video_path,
                voiceover_path=voice_path,
                ass_path="",  # no captions
                keyword_punches=punches,
                sfx_events=[],  # no sfx
                output_path="/tmp/out_nosfx.mp4",
                thumbnail_hold_s=0.0,
            )

        combined_cmd = calls[-1]
        # voice_path appears as the audio input (no sfx prerender).
        assert voice_path in combined_cmd
        # No ass=... in filter_complex when ass_path is empty.
        fc_idx = combined_cmd.index("-filter_complex")
        assert "ass=" not in combined_cmd[fc_idx + 1]
    finally:
        for p in (video_path, voice_path):
            Path(p).unlink(missing_ok=True)


def test_apply_engagement_pass_propagates_ffmpeg_failure():
    """Non-zero ffmpeg exit raises subprocess.CalledProcessError."""
    import subprocess as _sp

    editor = VideoEditor()
    video_path = _tmp_file(".mp4", b"fake")
    voice_path = _tmp_file(".mp3", b"fake")

    def _fake_run(cmd, **kwargs):
        return _FakeRunResult(returncode=1, stderr=b"boom")

    try:
        with patch("video_edit.video_editor.subprocess.run", side_effect=_fake_run):
            with pytest.raises(_sp.CalledProcessError):
                editor._apply_engagement_pass(
                    video_path=video_path,
                    voiceover_path=voice_path,
                    ass_path="",
                    keyword_punches=[],
                    sfx_events=[],
                    output_path="/tmp/out_fail.mp4",
                    thumbnail_hold_s=0.0,
                )
    finally:
        for p in (video_path, voice_path):
            Path(p).unlink(missing_ok=True)
