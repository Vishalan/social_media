"""Tests for :class:`CostLedger` (Unit 11)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from vesper_pipeline.cost_telemetry import (  # noqa: E402
    DEFAULT_CEILING_USD,
    CostLedger,
    CostStage,
)


class CostLedgerRecordTests(unittest.TestCase):
    def test_fresh_ledger_has_zero_total(self):
        ledger = CostLedger()
        self.assertEqual(ledger.total(), 0.0)
        self.assertEqual(ledger.ceiling_usd, DEFAULT_CEILING_USD)

    def test_record_sums_entries(self):
        ledger = CostLedger()
        ledger.record(CostStage.LLM_STORY, 0.20)
        ledger.record(CostStage.LLM_TIMELINE, 0.02)
        ledger.record(CostStage.CHATTERBOX, 0.0)
        self.assertAlmostEqual(ledger.total(), 0.22)

    def test_total_for_stage_isolates_category(self):
        ledger = CostLedger()
        ledger.record(CostStage.FLUX_FALLBACK, 0.04)
        ledger.record(CostStage.FLUX_FALLBACK, 0.04)
        ledger.record(CostStage.LLM_STORY, 0.15)
        self.assertAlmostEqual(ledger.total_for(CostStage.FLUX_FALLBACK), 0.08)
        self.assertAlmostEqual(ledger.total_for(CostStage.LLM_STORY), 0.15)


class CostLedgerTokenHelperTests(unittest.TestCase):
    def test_record_llm_tokens_computes_usd(self):
        ledger = CostLedger()
        # Sonnet 4.6 pricing (hypothetical): $3/Mtok in, $15/Mtok out.
        ledger.record_llm_tokens(
            CostStage.LLM_STORY,
            input_tokens=1000,
            output_tokens=500,
            input_price_per_mtok=3.0,
            output_price_per_mtok=15.0,
        )
        expected = (1000 / 1e6) * 3.0 + (500 / 1e6) * 15.0  # 0.003 + 0.0075
        self.assertAlmostEqual(ledger.total(), expected)


class CostLedgerFluxTests(unittest.TestCase):
    def test_flux_local_records_zero_cost_entry(self):
        ledger = CostLedger()
        ledger.record_flux_local(image_count=20, note="schnell")
        self.assertEqual(ledger.total(), 0.0)
        # But the entry is still present for telemetry.
        self.assertEqual(len(ledger.entries), 1)
        self.assertEqual(ledger.entries[0].stage, CostStage.FLUX_LOCAL)

    def test_flux_fallback_counts_as_cost(self):
        ledger = CostLedger()
        ledger.record_flux_fallback(per_image_usd=0.04, image_count=3)
        self.assertAlmostEqual(ledger.total(), 0.12)
        self.assertEqual(ledger.fallback_invocation_count(), 1)


class CostProjectionTests(unittest.TestCase):
    def test_project_accumulates_with_additional(self):
        ledger = CostLedger(ceiling_usd=0.75)
        ledger.record(CostStage.LLM_STORY, 0.30)
        snap = ledger.project(additional_usd=0.20)
        self.assertAlmostEqual(snap.total_usd, 0.50)
        self.assertFalse(snap.over_ceiling)

    def test_project_marks_over_ceiling_when_total_exceeds(self):
        ledger = CostLedger(ceiling_usd=0.50)
        ledger.record(CostStage.LLM_STORY, 0.40)
        snap = ledger.project(additional_usd=0.15)  # 0.55 > 0.50
        self.assertTrue(snap.over_ceiling)


class CostLedgerGatesTests(unittest.TestCase):
    def test_should_skip_i2v_when_adding_would_breach(self):
        ledger = CostLedger(ceiling_usd=0.50)
        ledger.record(CostStage.LLM_STORY, 0.35)
        ledger.record(CostStage.FLUX_FALLBACK, 0.12)
        # At 0.47 accumulated + a 0.05 I2V estimate = 0.52 > 0.50 → skip.
        self.assertTrue(ledger.should_skip_i2v(0.05))

    def test_should_skip_i2v_false_when_comfortable(self):
        ledger = CostLedger(ceiling_usd=0.75)
        ledger.record(CostStage.LLM_STORY, 0.20)
        self.assertFalse(ledger.should_skip_i2v(0.05))

    def test_should_abort_when_already_over_ceiling(self):
        ledger = CostLedger(ceiling_usd=0.25)
        ledger.record(CostStage.LLM_STORY, 0.30)
        self.assertTrue(ledger.should_abort())

    def test_should_abort_false_under_ceiling(self):
        ledger = CostLedger(ceiling_usd=0.75)
        ledger.record(CostStage.LLM_STORY, 0.20)
        ledger.record(CostStage.FLUX_FALLBACK, 0.04)
        self.assertFalse(ledger.should_abort())


class CostLedgerReportingTests(unittest.TestCase):
    def test_breakdown_groups_by_stage(self):
        ledger = CostLedger()
        ledger.record(CostStage.LLM_STORY, 0.20)
        ledger.record(CostStage.LLM_STORY, 0.05, note="retry")
        ledger.record(CostStage.FLUX_FALLBACK, 0.08)
        breakdown = ledger.breakdown()
        self.assertAlmostEqual(breakdown["llm_story"], 0.25)
        self.assertAlmostEqual(breakdown["flux_fallback"], 0.08)

    def test_fallback_invocation_count_counts_only_fallback_entries(self):
        ledger = CostLedger()
        ledger.record_flux_local(image_count=20)
        ledger.record_flux_fallback(per_image_usd=0.04)
        ledger.record_flux_fallback(per_image_usd=0.04)
        self.assertEqual(ledger.fallback_invocation_count(), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
