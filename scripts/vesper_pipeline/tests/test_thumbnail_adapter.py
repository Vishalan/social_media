"""Tests for :class:`VesperThumbnailAdapter`."""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import List

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from vesper_pipeline._types import VesperJob  # noqa: E402
from vesper_pipeline.thumbnail_adapter import (  # noqa: E402
    VesperThumbnailAdapter,
    _hex_to_rgb,
)


@dataclass
class _FakePalette:
    primary: str = "#E8E2D4"
    background: str = "#0A0A0C"
    accent: str = "#8B1A1A"
    shadow: str = "#2C2826"


@dataclass
class _FakeThumbnailStyle:
    font_path: str = "assets/fonts/CormorantGaramond-Bold.ttf"
    max_title_words: int = 7
    timestamp_motif: bool = True


class _CaptureCompose:
    """Fake compose_thumbnail that records its inputs."""

    def __init__(self):
        self.calls: List[dict] = []

    def __call__(self, *, headline, background_path, cutout_path,
                 output_path, brand_logo_path, config):
        self.calls.append({
            "headline": headline,
            "background_path": background_path,
            "cutout_path": cutout_path,
            "output_path": output_path,
            "brand_logo_path": brand_logo_path,
            "config": config,
        })
        return output_path


class HexToRgbTests(unittest.TestCase):
    def test_parses_hash_prefixed(self):
        self.assertEqual(_hex_to_rgb("#E8E2D4"), (232, 226, 212))

    def test_parses_bare_hex(self):
        self.assertEqual(_hex_to_rgb("0A0A0C"), (10, 10, 12))

    def test_rejects_malformed(self):
        with self.assertRaises(ValueError):
            _hex_to_rgb("#FFF")


class ThumbnailAdapterRenderTests(unittest.TestCase):
    def _make_job(self, title: str = "The last bus at 03:47"):
        return VesperJob(
            topic_title=title,
            subreddit="nosleep",
            job_id="job-test",
            story_script="x",
        )

    def test_render_invokes_compose_with_vesper_palette(self):
        compose = _CaptureCompose()
        adapter = VesperThumbnailAdapter(
            palette=_FakePalette(),
            thumbnail_style=_FakeThumbnailStyle(),
            compose_fn=compose,
        )
        out = "/tmp/vesper-thumb.png"
        result = adapter.render(
            job=self._make_job("The last bus at 03:47"),
            output_path=out,
        )

        self.assertEqual(str(result), out)
        self.assertEqual(len(compose.calls), 1)
        call = compose.calls[0]
        self.assertEqual(call["headline"], "The last bus at 03:47")
        self.assertIsNone(call["background_path"])  # gradient fallback

        cfg = call["config"]
        # Palette translated from hex to RGB tuples.
        self.assertEqual(cfg.bg, (10, 10, 12))
        self.assertEqual(cfg.primary, (232, 226, 212))
        self.assertEqual(cfg.accent, (139, 26, 26))
        self.assertEqual(cfg.bg_deep, (44, 40, 38))
        # Font candidate is Vesper's.
        self.assertEqual(
            cfg.font_candidates[0].name,
            "CormorantGaramond-Bold.ttf",
        )
        # Faceless channel — PiP explicitly off.
        self.assertFalse(cfg.pip_enabled)
        self.assertEqual(cfg.aspect, "9:16")

    def test_uses_job_topic_title_as_headline(self):
        compose = _CaptureCompose()
        adapter = VesperThumbnailAdapter(
            palette=_FakePalette(),
            thumbnail_style=_FakeThumbnailStyle(),
            compose_fn=compose,
        )
        adapter.render(
            job=self._make_job("A drive through nowhere"),
            output_path="/tmp/x.png",
        )
        self.assertEqual(compose.calls[0]["headline"], "A drive through nowhere")

    def test_placeholder_cutout_forwarded_when_pip_disabled(self):
        """pip_enabled=False means the compositor ignores cutout_path,
        but the signature requires it — adapter passes the configured
        placeholder path."""
        compose = _CaptureCompose()
        adapter = VesperThumbnailAdapter(
            palette=_FakePalette(),
            thumbnail_style=_FakeThumbnailStyle(),
            compose_fn=compose,
            placeholder_cutout="assets/vesper/refs/_fake.png",
        )
        adapter.render(
            job=self._make_job(),
            output_path="/tmp/x.png",
        )
        self.assertEqual(
            str(compose.calls[0]["cutout_path"]),
            "assets/vesper/refs/_fake.png",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
