"""Tests for :class:`RapidUnpublisher` (Unit 11 — /takedown command)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from vesper_pipeline.rapid_unpublish import (  # noqa: E402
    RapidUnpublisher,
    TakedownError,
    TakedownResult,
)


class _StubPostiz:
    def __init__(self, fail_on: List[str] | None = None):
        self.fail_on = set(fail_on or [])
        self.calls: List[str] = []

    def delete_post(self, post_id):
        self.calls.append(post_id)
        if post_id in self.fail_on:
            raise RuntimeError(f"platform refused deletion of {post_id}")
        return {"ok": True, "deleted": post_id}


class _StubTracker:
    def __init__(self, post_ids_for: dict[str, List[str]] | None = None):
        self.post_ids_for = post_ids_for or {}
        self.recorded: List[dict] = []

    def get_post_ids_for_short(self, *, job_id):
        return list(self.post_ids_for.get(job_id, []))

    def record_takedown(self, *, job_id, reason, platforms, failed_platforms):
        self.recorded.append({
            "job_id": job_id,
            "reason": reason,
            "platforms": list(platforms),
            "failed_platforms": list(failed_platforms),
        })


OWNER_ID = 4242


class OwnerAuthTests(unittest.TestCase):
    def test_non_owner_rejected(self):
        postiz = _StubPostiz()
        tracker = _StubTracker(post_ids_for={"job-1": ["p-ig", "p-yt", "p-tt"]})
        unpublisher = RapidUnpublisher(
            postiz=postiz, tracker=tracker, owner_user_id=OWNER_ID,
        )
        with self.assertRaises(TakedownError) as cm:
            unpublisher.handle(
                requester_user_id=9999,
                job_id="job-1",
                reason="dmca",
            )
        self.assertIn("only the configured owner", str(cm.exception))
        # Must NOT have called delete_post
        self.assertEqual(postiz.calls, [])
        # Must NOT have recorded a takedown
        self.assertEqual(tracker.recorded, [])

    def test_owner_accepted(self):
        postiz = _StubPostiz()
        tracker = _StubTracker(post_ids_for={"job-1": ["p-ig"]})
        unpublisher = RapidUnpublisher(
            postiz=postiz, tracker=tracker, owner_user_id=OWNER_ID,
        )
        result = unpublisher.handle(
            requester_user_id=OWNER_ID,
            job_id="job-1",
            reason="dmca",
        )
        self.assertTrue(result.ok)


class MissingJobTests(unittest.TestCase):
    def test_unknown_job_raises(self):
        postiz = _StubPostiz()
        tracker = _StubTracker(post_ids_for={})
        unpublisher = RapidUnpublisher(
            postiz=postiz, tracker=tracker, owner_user_id=OWNER_ID,
        )
        with self.assertRaises(TakedownError) as cm:
            unpublisher.handle(
                requester_user_id=OWNER_ID,
                job_id="not-a-job",
                reason="bad quality",
            )
        self.assertIn("no post_ids recorded", str(cm.exception))
        self.assertEqual(postiz.calls, [])


class HappyPathTests(unittest.TestCase):
    def test_three_platforms_deleted(self):
        postiz = _StubPostiz()
        tracker = _StubTracker(post_ids_for={
            "job-1": ["p-ig", "p-yt", "p-tt"],
        })
        unpublisher = RapidUnpublisher(
            postiz=postiz, tracker=tracker, owner_user_id=OWNER_ID,
        )
        result = unpublisher.handle(
            requester_user_id=OWNER_ID,
            job_id="job-1",
            reason="dmca claim from source",
        )
        self.assertTrue(result.ok)
        self.assertEqual(sorted(result.deleted), ["p-ig", "p-tt", "p-yt"])
        self.assertEqual(result.failed, [])
        self.assertEqual(sorted(postiz.calls), ["p-ig", "p-tt", "p-yt"])
        # Tracker sees the takedown with correct platforms + reason.
        self.assertEqual(len(tracker.recorded), 1)
        rec = tracker.recorded[0]
        self.assertEqual(rec["job_id"], "job-1")
        self.assertEqual(rec["reason"], "dmca claim from source")
        self.assertEqual(sorted(rec["platforms"]), ["p-ig", "p-tt", "p-yt"])
        self.assertEqual(rec["failed_platforms"], [])


class PartialFailureTests(unittest.TestCase):
    def test_one_platform_fails_others_succeed(self):
        postiz = _StubPostiz(fail_on=["p-tt"])
        tracker = _StubTracker(post_ids_for={
            "job-1": ["p-ig", "p-yt", "p-tt"],
        })
        unpublisher = RapidUnpublisher(
            postiz=postiz, tracker=tracker, owner_user_id=OWNER_ID,
        )
        result = unpublisher.handle(
            requester_user_id=OWNER_ID,
            job_id="job-1",
            reason="quality recall",
        )
        self.assertFalse(result.ok)
        self.assertEqual(sorted(result.deleted), ["p-ig", "p-yt"])
        self.assertEqual(result.failed, ["p-tt"])
        self.assertEqual(len(result.failure_reasons), 1)
        self.assertIn("p-tt", result.failure_reasons[0])
        # Analytics still records — owner needs visibility.
        self.assertEqual(len(tracker.recorded), 1)
        self.assertEqual(tracker.recorded[0]["failed_platforms"], ["p-tt"])

    def test_summary_string_lists_failures(self):
        postiz = _StubPostiz(fail_on=["p-yt"])
        tracker = _StubTracker(post_ids_for={"job-2": ["p-ig", "p-yt"]})
        unpublisher = RapidUnpublisher(
            postiz=postiz, tracker=tracker, owner_user_id=OWNER_ID,
        )
        result = unpublisher.handle(
            requester_user_id=OWNER_ID,
            job_id="job-2",
            reason="bad mod miss",
        )
        summary = result.summary()
        self.assertIn("PARTIAL", summary)
        self.assertIn("p-ig", summary)
        self.assertIn("p-yt", summary)


class TrackerFailureTests(unittest.TestCase):
    def test_tracker_record_failure_does_not_crash_handle(self):
        """If the tracker can't record (e.g., DB down), the delete calls
        have already gone out — we can't roll them back. Log the error
        but return the result so the owner sees what succeeded."""
        postiz = _StubPostiz()
        tracker = _StubTracker(post_ids_for={"job-1": ["p-ig"]})
        tracker.record_takedown = MagicMock(  # type: ignore[assignment]
            side_effect=RuntimeError("analytics db down")
        )
        unpublisher = RapidUnpublisher(
            postiz=postiz, tracker=tracker, owner_user_id=OWNER_ID,
        )
        result = unpublisher.handle(
            requester_user_id=OWNER_ID,
            job_id="job-1",
            reason="test",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.deleted, ["p-ig"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
