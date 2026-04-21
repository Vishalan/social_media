"""Tests for :mod:`scripts.vesper_pipeline.overlays`."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import List

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from vesper_pipeline.overlays import (  # noqa: E402
    OverlayBurner,
    OverlayError,
    OverlayPack,
    _DEFAULT_OPACITY,
    _LAYER_ORDER,
    build_overlay_pack,
)


def _seed_layers(base: Path, names: list[str]) -> None:
    base.mkdir(parents=True, exist_ok=True)
    for n in names:
        (base / f"{n}.mp4").write_bytes(b"mp4-stub")


class OverlayPackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="overlay-pack-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_available_layers_respects_canonical_order(self):
        _seed_layers(self.tmp, ["grain", "fog"])
        pack = OverlayPack(base_dir=self.tmp)
        # Grain comes before fog per _LAYER_ORDER, even though we seeded
        # them in a different order.
        self.assertEqual(pack.available_layers(), ["grain", "fog"])

    def test_available_layers_empty_when_none_present(self):
        pack = OverlayPack(base_dir=self.tmp)
        self.assertEqual(pack.available_layers(), [])

    def test_opacity_override_beats_default(self):
        pack = OverlayPack(
            base_dir=self.tmp,
            opacity_overrides={"grain": 0.25},
        )
        self.assertEqual(pack.opacity("grain"), 0.25)
        # Non-overridden layer falls back to default.
        self.assertEqual(pack.opacity("dust"), _DEFAULT_OPACITY["dust"])


class OverlayBurnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="overlay-burn-"))
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
                Path(cmd[-1]).write_bytes(b"burned mp4")
                return _Result()

        return _R()

    def test_zero_layers_returns_false_and_no_ffmpeg(self):
        runner = self._runner()
        pack = OverlayPack(base_dir=self.tmp)  # empty
        burner = OverlayBurner(runner=runner)
        result = burner.apply(
            input_mp4=self.in_mp4,
            output_mp4=self.out_mp4,
            pack=pack,
        )
        self.assertFalse(result)
        self.assertEqual(runner.calls, [])

    def test_four_layers_produces_full_ffmpeg_graph(self):
        _seed_layers(self.tmp, list(_LAYER_ORDER))
        runner = self._runner()
        pack = OverlayPack(base_dir=self.tmp)
        burner = OverlayBurner(runner=runner)
        self.assertTrue(burner.apply(
            input_mp4=self.in_mp4,
            output_mp4=self.out_mp4,
            pack=pack,
        ))
        self.assertEqual(len(runner.calls), 1)
        cmd = runner.calls[0]
        self.assertEqual(cmd[0], "ffmpeg")
        # Five inputs total: base + 4 layers.
        self.assertEqual(cmd.count("-i"), 5)
        # The filter graph includes each layer's colorchannelmixer.
        filter_idx = cmd.index("-filter_complex")
        graph = cmd[filter_idx + 1]
        for name in _LAYER_ORDER:
            self.assertIn(
                f"aa={_DEFAULT_OPACITY[name]:.3f}",
                graph,
                f"expected aa={_DEFAULT_OPACITY[name]:.3f} for {name} in graph",
            )
        # Final overlay output label mapped.
        self.assertIn("-map", cmd)
        self.assertIn("[vout]", cmd)

    def test_partial_pack_uses_only_available_layers(self):
        _seed_layers(self.tmp, ["grain", "flicker"])
        runner = self._runner()
        pack = OverlayPack(base_dir=self.tmp)
        burner = OverlayBurner(runner=runner)
        burner.apply(
            input_mp4=self.in_mp4,
            output_mp4=self.out_mp4,
            pack=pack,
        )
        cmd = runner.calls[0]
        # 2 layer inputs.
        self.assertEqual(cmd.count("-i"), 3)  # base + 2 layers
        filter_idx = cmd.index("-filter_complex")
        graph = cmd[filter_idx + 1]
        # Only grain + flicker opacities in the graph.
        self.assertIn(f"aa={_DEFAULT_OPACITY['grain']:.3f}", graph)
        self.assertIn(f"aa={_DEFAULT_OPACITY['flicker']:.3f}", graph)
        self.assertNotIn(f"aa={_DEFAULT_OPACITY['dust']:.3f}", graph)
        self.assertNotIn(f"aa={_DEFAULT_OPACITY['fog']:.3f}", graph)

    def test_nonzero_ffmpeg_rc_raises_overlay_error(self):
        _seed_layers(self.tmp, ["grain"])
        runner = self._runner(rc=1, stderr=b"ffmpeg: bad filter")
        pack = OverlayPack(base_dir=self.tmp)
        burner = OverlayBurner(runner=runner)
        with self.assertRaises(OverlayError) as cm:
            burner.apply(
                input_mp4=self.in_mp4,
                output_mp4=self.out_mp4,
                pack=pack,
            )
        self.assertIn("overlay pass failed", str(cm.exception).lower())
        self.assertIn("bad filter", str(cm.exception))

    def test_opacity_override_flows_into_graph(self):
        _seed_layers(self.tmp, ["grain"])
        runner = self._runner()
        pack = OverlayPack(
            base_dir=self.tmp,
            opacity_overrides={"grain": 0.44},
        )
        burner = OverlayBurner(runner=runner)
        burner.apply(
            input_mp4=self.in_mp4,
            output_mp4=self.out_mp4,
            pack=pack,
        )
        graph = runner.calls[0][runner.calls[0].index("-filter_complex") + 1]
        self.assertIn("aa=0.440", graph)
        self.assertNotIn("aa=0.120", graph)  # grain default not used


class BuildOverlayPackTests(unittest.TestCase):
    def test_points_at_channel_scoped_dir(self):
        root = Path(tempfile.mkdtemp(prefix="overlay-root-"))
        try:
            pack = build_overlay_pack("vesper", repo_root=root)
            self.assertEqual(
                pack.base_dir,
                root / "assets" / "vesper" / "overlays",
            )
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
