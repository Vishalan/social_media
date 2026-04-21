"""Tests for the SFX pack registry (Unit 3).

Covers:
  * CommonCreed pack is pre-registered and backward-compatible
    (callers that omit ``pack=`` get the same files they got pre-Unit-3).
  * ``register_pack`` lets Vesper (and future channels) add a distinct
    pack that resolves independently.
  * Unknown packs raise a clear error.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from audio.sfx import (
    SfxPack,
    _COMMONCREED_CATEGORY_FILES,
    _PACKS,
    pick_sfx,
    register_pack,
)


class CommonCreedPackBackwardsCompatTests(unittest.TestCase):
    def test_pick_sfx_without_pack_kwarg_uses_commoncreed(self):
        """Pre-Unit-3 callers passed no ``pack`` — they must still land on
        CommonCreed's files."""
        # CommonCreed pack is pre-registered — should be available.
        self.assertIn("commoncreed", _PACKS)
        # The legacy category_files dict is the CommonCreed category map.
        self.assertEqual(
            _PACKS["commoncreed"].category_files,
            _COMMONCREED_CATEGORY_FILES,
        )

    def test_pick_sfx_resolves_commoncreed_files(self):
        """A CommonCreed SFX pick returns a path under ``assets/sfx/``.

        Skips gracefully when the .wav files aren't present on disk
        (e.g., fresh checkouts that haven't run ``_generate_sfx``).
        """
        try:
            path = pick_sfx("punch", "light", seed=42)
        except FileNotFoundError:
            self.skipTest(
                "CommonCreed SFX .wav files not populated locally "
                "(run scripts/audio/_generate_sfx.py)"
            )
        self.assertIn("/assets/sfx/", str(path))

    def test_pick_sfx_with_explicit_commoncreed_pack_matches(self):
        """Passing ``pack='commoncreed'`` explicitly returns identical
        results to the default."""
        try:
            implicit = pick_sfx("punch", "light", seed=42)
            explicit = pick_sfx("punch", "light", seed=42, pack="commoncreed")
        except FileNotFoundError:
            self.skipTest("CommonCreed SFX not populated")
        self.assertEqual(implicit, explicit)


class VesperPackRegistrationTests(unittest.TestCase):
    """Register a Vesper-style pack with fake .wav files in a tmp dir and
    verify that ``pick_sfx(..., pack='vesper_test')`` resolves against the
    new pack, not CommonCreed's."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vesper-sfx-")
        # Create a minimal Vesper-shaped category_files map whose filenames
        # are different from CommonCreed's, touch the .wavs, and register.
        self.category_files = {
            "cut": {
                "light": ["vesper_cut_rev_short"],
                "heavy": ["vesper_cut_sub_slam"],
            },
            "punch": {
                "light": ["vesper_punch_wooddrop"],
                "heavy": ["vesper_punch_subhit"],
            },
            "reveal": {
                "light": ["vesper_reveal_breath"],
                "heavy": ["vesper_reveal_drone"],
            },
            "tick": {
                "light": ["vesper_tick_faint"],
                "heavy": ["vesper_tick_hard"],
            },
        }
        for bucket in self.category_files.values():
            for names in bucket.values():
                for n in names:
                    (Path(self.tmp) / f"{n}.wav").write_bytes(b"\x00")

        self.pack = SfxPack(
            name="vesper_test",
            root_dir=Path(self.tmp),
            category_files=self.category_files,
        )
        register_pack(self.pack)

    def tearDown(self) -> None:
        # Best-effort registry cleanup so other tests don't see the stub.
        _PACKS.pop("vesper_test", None)
        for p in Path(self.tmp).iterdir():
            p.unlink()
        Path(self.tmp).rmdir()

    def test_pick_sfx_resolves_vesper_files(self):
        path = pick_sfx("punch", "heavy", seed=7, pack="vesper_test")
        self.assertEqual(path.parent, Path(self.tmp))
        self.assertTrue(path.name.startswith("vesper_"))

    def test_pick_sfx_vesper_does_not_leak_commoncreed_files(self):
        """The Vesper pack must not return a CommonCreed filename."""
        for category in ("cut", "punch", "reveal", "tick"):
            for intensity in ("light", "heavy"):
                path = pick_sfx(
                    category, intensity, seed=100, pack="vesper_test",
                )
                # Every file resolves inside the Vesper tmp root.
                self.assertEqual(
                    path.parent, Path(self.tmp),
                    f"{category}/{intensity} leaked out of Vesper root: {path}",
                )

    def test_unknown_pack_raises(self):
        with self.assertRaises(KeyError):
            pick_sfx("punch", "light", seed=1, pack="no_such_pack_xyz")


if __name__ == "__main__":
    unittest.main(verbosity=2)
