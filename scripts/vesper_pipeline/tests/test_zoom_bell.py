"""Tests for :mod:`scripts.vesper_pipeline.zoom_bell`."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import List

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from vesper_pipeline.keyword_punch import KeywordPunch  # noqa: E402
from vesper_pipeline.zoom_bell import (  # noqa: E402
    ZoomBellBurner,
    ZoomBellError,
    _DEFAULT_AMPLITUDE,
    _PUNCH_DURATION_S,
    _REASON_AMPLITUDE,
    build_zoom_expression,
)


class ZoomExpressionTests(unittest.TestCase):
    def test_empty_punches_returns_identity(self):
        self.assertEqual(build_zoom_expression([]), "1.0")

    def test_single_capitalized_punch_has_expected_amplitude(self):
        punches = [KeywordPunch(t_seconds=1.5, word="DAVID", reason="capitalized")]
        expr = build_zoom_expression(punches, punch_duration_s=0.2)
        # Starts with the identity "1.0+".
        self.assertTrue(expr.startswith("1.0+"))
        # Amplitude matches the reason mapping.
        self.assertIn(str(_REASON_AMPLITUDE["capitalized"]), expr)
        # Sin-bell over [1.5, 1.7].
        self.assertIn("1.500", expr)
        self.assertIn("1.700", expr)
        self.assertIn("sin(PI*(t-1.500)/0.200)", expr)

    def test_long_word_punch_uses_lower_amplitude(self):
        punches = [
            KeywordPunch(t_seconds=2.0, word="whispered", reason="long_word"),
        ]
        expr = build_zoom_expression(punches)
        self.assertIn(f"{_REASON_AMPLITUDE['long_word']}", expr)
        self.assertNotIn(
            f"{_REASON_AMPLITUDE['capitalized']}*if",
            expr,
            "long_word amplitude must not leak capitalized's value",
        )

    def test_unknown_reason_falls_back_to_default_amplitude(self):
        punches = [
            KeywordPunch(t_seconds=1.0, word="x", reason="future_rule"),
        ]
        expr = build_zoom_expression(punches)
        self.assertIn(str(_DEFAULT_AMPLITUDE), expr)

    def test_multi_punch_expression_sums_all(self):
        punches = [
            KeywordPunch(t_seconds=1.0, word="A", reason="capitalized"),
            KeywordPunch(t_seconds=5.0, word="B", reason="long_word"),
            KeywordPunch(t_seconds=8.0, word="C.", reason="end_of_sentence"),
        ]
        expr = build_zoom_expression(punches)
        # Four additive parts: identity + three bells.
        self.assertEqual(expr.count("+"), 3)
        self.assertIn("1.000", expr)
        self.assertIn("5.000", expr)
        self.assertIn("8.000", expr)


class ZoomBellBurnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="vesper-zoom-"))
        self.in_mp4 = str(self.tmp / "in.mp4")
        self.out_mp4 = str(self.tmp / "out.mp4")
        Path(self.in_mp4).write_bytes(b"in-mp4")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _runner(self, rc: int = 0, stderr: bytes = b""):
        class _Result:
            returncode = rc
            stdout = b""

        _Result.stderr = stderr

        class _R:
            def __init__(self):
                self.calls: List[list] = []

            def __call__(self, cmd, capture_output=False, **kw):
                self.calls.append(list(cmd))
                Path(cmd[-1]).write_bytes(b"zoomed mp4")
                return _Result()

        return _R()

    def test_empty_punches_returns_false_and_no_ffmpeg(self):
        runner = self._runner()
        burner = ZoomBellBurner(runner=runner)
        self.assertFalse(burner.apply(
            input_mp4=self.in_mp4,
            output_mp4=self.out_mp4,
            punches=[],
        ))
        self.assertEqual(runner.calls, [])

    def test_single_punch_builds_expected_cmd(self):
        runner = self._runner()
        burner = ZoomBellBurner(runner=runner)
        punches = [
            KeywordPunch(t_seconds=1.5, word="DAVID", reason="capitalized"),
        ]
        self.assertTrue(burner.apply(
            input_mp4=self.in_mp4,
            output_mp4=self.out_mp4,
            punches=punches,
        ))
        self.assertEqual(len(runner.calls), 1)
        cmd = runner.calls[0]
        self.assertEqual(cmd[0], "ffmpeg")
        # -vf contains scale + crop referencing the expression.
        vf_idx = cmd.index("-vf")
        vf = cmd[vf_idx + 1]
        self.assertIn("scale=iw*(", vf)
        self.assertIn("crop=iw/(", vf)
        self.assertIn("sin(PI*(t-1.500)/0.200)", vf)
        # Audio stream-copied.
        self.assertIn("-c:a", cmd)
        c_a_idx = cmd.index("-c:a")
        self.assertEqual(cmd[c_a_idx + 1], "copy")

    def test_nonzero_ffmpeg_rc_raises(self):
        runner = self._runner(rc=1, stderr=b"bad expr")
        burner = ZoomBellBurner(runner=runner)
        punches = [KeywordPunch(t_seconds=1.0, word="x", reason="capitalized")]
        with self.assertRaises(ZoomBellError) as cm:
            burner.apply(
                input_mp4=self.in_mp4,
                output_mp4=self.out_mp4,
                punches=punches,
            )
        self.assertIn("zoom pass failed", str(cm.exception).lower())
        self.assertIn("bad expr", str(cm.exception))

    def test_custom_duration_propagates_to_expression(self):
        runner = self._runner()
        burner = ZoomBellBurner(runner=runner, punch_duration_s=0.5)
        punches = [KeywordPunch(t_seconds=0.0, word="x", reason="capitalized")]
        burner.apply(
            input_mp4=self.in_mp4,
            output_mp4=self.out_mp4,
            punches=punches,
        )
        vf = runner.calls[0][runner.calls[0].index("-vf") + 1]
        self.assertIn("sin(PI*(t-0.000)/0.500)", vf)


if __name__ == "__main__":
    unittest.main(verbosity=2)
