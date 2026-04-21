"""Tests for per-channel CPM rates (Unit 2b).

``ChannelProfile.cpm_rates`` lives on the profile so each channel owns
its revenue assumptions. :meth:`AnalyticsTracker.revenue_estimate`
accepts the dict via its ``cpm_rates=`` kwarg and falls back to
``_DEFAULT_CPM_RATES`` (unchanged CommonCreed-tuned values) when the
caller passes nothing.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure ``scripts/`` is on the path so ``analytics.*`` resolves.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from channels import load_channel_config
from analytics.tracker import AnalyticsTracker


class CommonCreedCpmRatesTests(unittest.TestCase):
    def test_commoncreed_profile_exposes_cpm_rates(self):
        profile = load_channel_config("commoncreed")
        self.assertIsInstance(profile.cpm_rates, dict)
        # Values carry over verbatim from the legacy module-level dict.
        self.assertEqual(profile.cpm_rates["youtube"], 4.50)
        self.assertEqual(profile.cpm_rates["tiktok"], 0.25)
        self.assertEqual(profile.cpm_rates["instagram"], 0.40)
        self.assertEqual(profile.cpm_rates["default"], 0.50)

    def test_revenue_estimate_uses_provided_cpm_rates(self):
        tmp = tempfile.mkdtemp(prefix="cpm-test-")
        db_path = os.path.join(tmp, "analytics.db")
        try:
            tracker = AnalyticsTracker(db_path=db_path)
            try:
                profile = load_channel_config("commoncreed")
                out = tracker.revenue_estimate(
                    views_by_platform={"youtube": 10_000, "tiktok": 100_000},
                    channel_id="commoncreed",
                    cpm_rates=profile.cpm_rates,
                )
                # YT: 10000/1000 * 4.50 = 45.00
                # TT: 100000/1000 * 0.25 = 25.00
                self.assertEqual(out["youtube"]["estimated_revenue"], 45.00)
                self.assertEqual(out["tiktok"]["estimated_revenue"], 25.00)
                self.assertEqual(out["total_estimated_revenue"], 70.00)
                self.assertEqual(out["channel_id"], "commoncreed")
            finally:
                tracker.close()
        finally:
            for p in Path(tmp).iterdir():
                p.unlink()
            Path(tmp).rmdir()

    def test_revenue_estimate_falls_back_to_defaults_when_no_cpm(self):
        """Caller that doesn't pass cpm_rates gets the tracker's
        module-level defaults — preserves legacy behavior for any caller
        that hasn't been migrated to profile-sourced CPM yet."""
        tmp = tempfile.mkdtemp(prefix="cpm-fallback-")
        db_path = os.path.join(tmp, "analytics.db")
        try:
            tracker = AnalyticsTracker(db_path=db_path)
            try:
                out = tracker.revenue_estimate(
                    views_by_platform={"youtube": 10_000},
                    channel_id="commoncreed",
                )
                self.assertEqual(out["youtube"]["cpm"], 4.50)
                self.assertEqual(out["youtube"]["estimated_revenue"], 45.00)
            finally:
                tracker.close()
        finally:
            for p in Path(tmp).iterdir():
                p.unlink()
            Path(tmp).rmdir()


if __name__ == "__main__":
    unittest.main(verbosity=2)
