"""Tests for :class:`PostizRateLedger` (Unit 12).

Uses an injectable clock so time-windowing logic is deterministic.
All tests run against a tmpdir ledger; no real fcntl contention beyond
the single-process path (multi-process contention is covered by the
code path but exercising it cleanly needs a separate process — out of
scope for unit tests).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_SIDECAR = Path(__file__).resolve().parent.parent
if str(_SIDECAR) not in sys.path:
    sys.path.insert(0, str(_SIDECAR))

from postiz_rate_ledger import (  # type: ignore
    POSTIZ_HOURLY_LIMIT,
    PostizRateBudgetExceeded,
    PostizRateLedger,
    WINDOW_S,
)


class _FakeClock:
    """Monotonic injectable clock. Starts at a non-zero epoch so log
    entries look realistic."""

    def __init__(self, start: float = 1_700_000_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def tick(self, seconds: float) -> None:
        self.t += seconds


class LedgerBasicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="postiz-ledger-")
        self.path = Path(self.tmp) / "budget.jsonl"
        self.clock = _FakeClock()
        self.ledger = PostizRateLedger(self.path, clock=self.clock)

    def tearDown(self) -> None:
        for p in Path(self.tmp).iterdir():
            p.unlink()
        Path(self.tmp).rmdir()

    def test_empty_ledger_has_zero_count(self):
        self.assertEqual(self.ledger.count_last_hour(), 0)
        self.assertEqual(self.ledger.remaining(), POSTIZ_HOURLY_LIMIT)

    def test_consume_increments_count(self):
        self.ledger.consume(channel_id="vesper", endpoint="publish_post")
        self.assertEqual(self.ledger.count_last_hour(), 1)
        self.assertEqual(self.ledger.remaining(), POSTIZ_HOURLY_LIMIT - 1)

    def test_ledger_file_is_mode_0600(self):
        self.ledger.consume(channel_id="vesper")
        mode = self.path.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600, f"ledger must be 0600; got {oct(mode)}")

    def test_consume_multiple_entries_counted(self):
        for _ in range(5):
            self.ledger.consume(channel_id="vesper")
        self.assertEqual(self.ledger.count_last_hour(), 5)

    def test_count_is_channel_scoped_when_requested(self):
        self.ledger.consume(channel_id="vesper", count=2)
        self.ledger.consume(channel_id="commoncreed", count=3)
        self.assertEqual(self.ledger.count_last_hour(), 5)
        self.assertEqual(self.ledger.count_last_hour(channel_id="vesper"), 2)
        self.assertEqual(
            self.ledger.count_last_hour(channel_id="commoncreed"),
            3,
        )


class LedgerWindowingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="postiz-win-")
        self.path = Path(self.tmp) / "budget.jsonl"
        self.clock = _FakeClock()
        self.ledger = PostizRateLedger(self.path, clock=self.clock)

    def tearDown(self) -> None:
        for p in Path(self.tmp).iterdir():
            p.unlink()
        Path(self.tmp).rmdir()

    def test_entries_older_than_window_are_excluded(self):
        # Consume at t=0
        self.ledger.consume(channel_id="vesper")
        # Move clock past the window
        self.clock.tick(WINDOW_S + 60)
        # That first entry is now stale.
        self.assertEqual(self.ledger.count_last_hour(), 0)
        self.assertEqual(self.ledger.remaining(), POSTIZ_HOURLY_LIMIT)

    def test_entry_exactly_at_window_boundary_counted(self):
        # Consume at t=0; tick forward by exactly WINDOW_S.
        self.ledger.consume(channel_id="vesper")
        self.clock.tick(WINDOW_S)
        # Boundary inclusive — entry ts is >= cutoff.
        self.assertEqual(self.ledger.count_last_hour(), 1)

    def test_mixed_old_and_new_entries_only_window_counts(self):
        # 3 old entries
        for _ in range(3):
            self.ledger.consume(channel_id="vesper")
        # Jump forward 2 hours — all stale
        self.clock.tick(2 * WINDOW_S)
        # 2 fresh entries
        for _ in range(2):
            self.ledger.consume(channel_id="vesper")
        self.assertEqual(self.ledger.count_last_hour(), 2)


class LedgerAssertAvailableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="postiz-assert-")
        self.path = Path(self.tmp) / "budget.jsonl"
        self.clock = _FakeClock()
        self.ledger = PostizRateLedger(
            self.path,
            clock=self.clock,
            hourly_limit=5,
        )

    def tearDown(self) -> None:
        for p in Path(self.tmp).iterdir():
            p.unlink()
        Path(self.tmp).rmdir()

    def test_assert_available_passes_when_budget_left(self):
        self.ledger.assert_available(3)
        # no exception — ok

    def test_assert_available_raises_when_budget_exhausted(self):
        for _ in range(5):
            self.ledger.consume(channel_id="vesper")
        with self.assertRaises(PostizRateBudgetExceeded):
            self.ledger.assert_available(1)

    def test_assert_available_raises_when_request_exceeds_remaining(self):
        for _ in range(3):
            self.ledger.consume(channel_id="vesper")
        # Only 2 left; asking for 5 must raise.
        with self.assertRaises(PostizRateBudgetExceeded):
            self.ledger.assert_available(5)


class LedgerCountKwargTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="postiz-count-")
        self.path = Path(self.tmp) / "budget.jsonl"
        self.clock = _FakeClock()
        self.ledger = PostizRateLedger(self.path, clock=self.clock)

    def tearDown(self) -> None:
        for p in Path(self.tmp).iterdir():
            p.unlink()
        Path(self.tmp).rmdir()

    def test_batched_consume_count_5(self):
        self.ledger.consume(channel_id="vesper", count=5)
        self.assertEqual(self.ledger.count_last_hour(), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
