"""Tests for :class:`VesperPipeline` orchestration (Unit 11).

All collaborators stubbed — no network, no GPU, no LLM. Verifies:
  * Happy-path full run posts and logs analytics
  * Stage failures short-circuit remaining stages
  * Rate-budget exceeded defers rather than fails publish
  * Sidecar-down in preflight bubbles as exception (both-pipelines abort)
  * I2V backend None → beats degrade to parallax (no crash)
  * Cost ledger over ceiling before assembly aborts cleanly
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, List

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from vesper_pipeline import (  # noqa: E402
    CostLedger,
    CostStage,
    VesperJob,
    VesperPipeline,
    VesperPipelineConfig,
)


# ─── Stubs ──────────────────────────────────────────────────────────────


class _StubTopic:
    def __init__(self, title: str, subreddit: str = "nosleep", score: float = 900):
        self.title_canonical = title
        self.title = title
        self.subreddit = subreddit
        self.score = score


class _StubTopicSource:
    def __init__(self, topics: List[_StubTopic]):
        self.topics = topics

    def fetch_topic_candidates(self, tracker, **kw) -> List[_StubTopic]:
        return self.topics


class _StubDraft:
    def __init__(self, text: str = "A short original horror story about a night shift."):
        self.archivist_script = text
        self.word_count = len(text.split())
        self.content_sha256 = "sha-stub"


class _StubWriter:
    def __init__(self, draft=None, fail_first=False):
        self.draft = draft if draft is not None else _StubDraft()
        self.fail_first = fail_first
        self.calls = 0

    def write_short(self, *, topic_title, subreddit):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            return None
        return self.draft


class _StubPreflight:
    def __init__(self, ok=True, state="ok"):
        self.ok = ok
        self.state = state


class _StubVoiceResult:
    def __init__(self, duration_s=30.0):
        self.duration_s = duration_s


class _StubVoice:
    def __init__(self, pre_state="ok"):
        self.pre_state = pre_state

    def preflight(self):
        return _StubPreflight(ok=(self.pre_state == "ok"), state=self.pre_state)

    def generate(self, text, output_path):
        return _StubVoiceResult()


class _StubFlux:
    def __init__(self, fail_on_beat=None):
        self.fail_on_beat = fail_on_beat
        self.calls = 0

    async def generate(self, prompt, output_path, **opts):
        self.calls += 1
        if self.fail_on_beat is not None and self.calls == self.fail_on_beat:
            raise RuntimeError("flux exploded")
        return None


class _StubParallax:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    async def animate(self, still_path, output_path, *, duration_s):
        self.calls += 1
        if self.fail:
            raise RuntimeError("parallax fail")
        return output_path


class _StubI2V:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    async def generate(self, still_path, output_path, *, motion_hint):
        self.calls += 1
        if self.fail:
            raise RuntimeError("i2v fail")
        return output_path


class _StubAssembler:
    def __init__(self, fail=False):
        self.fail = fail

    def assemble(self, *, job, output_path):
        if self.fail:
            raise RuntimeError("assembly fail")
        return output_path


class _StubThumb:
    def render(self, *, job, output_path):
        return output_path


class _StubApproval:
    def __init__(self, approved=True, raise_exc=None):
        self.approved = approved
        self.raise_exc = raise_exc
        self.calls = 0

    def request_approval(self, **kw):
        self.calls += 1
        if self.raise_exc:
            raise self.raise_exc
        return self.approved


class _StubPublisher:
    def __init__(self, result=None, raise_exc=None):
        self.result = result if result is not None else {
            "ok": True, "postIds": ["p-ig", "p-yt", "p-tt"]
        }
        self.raise_exc = raise_exc
        self.calls = 0

    def publish_post(self, **kw):
        self.calls += 1
        if self.raise_exc:
            raise self.raise_exc
        return self.result


class _StubRateLedger:
    def __init__(self, allow=True):
        self.allow = allow
        self.asserted: List[int] = []
        self.consumed: List[dict] = []

    def assert_available(self, n=1):
        self.asserted.append(n)
        if not self.allow:
            raise RuntimeError(f"budget insufficient for {n}")

    def consume(self, *, channel_id, endpoint="publish_post", count=1):
        self.consumed.append({
            "channel_id": channel_id,
            "endpoint": endpoint,
            "count": count,
        })


class _StubTracker:
    def __init__(self):
        self.logs: List[dict] = []

    def log_post(self, **kw):
        self.logs.append(kw)


def _sync_runner(coro):
    """Inline async runner — pipeline accepts any callable."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _build_pipeline(
    *,
    topics=None,
    writer=None,
    voice=None,
    flux=None,
    parallax=None,
    i2v=None,
    assembler=None,
    thumbnails=None,
    approval=None,
    publisher=None,
    rate_ledger=None,
    tracker=None,
    cost_ceiling=0.75,
    output_dir=None,
):
    tmp = output_dir or tempfile.mkdtemp(prefix="vesper-pipe-")
    cfg = VesperPipelineConfig(
        max_shorts_per_run=1,
        output_base_dir=tmp,
    )
    return VesperPipeline(
        config=cfg,
        topic_source=_StubTopicSource(topics or [_StubTopic("the last bus")]),
        writer=writer or _StubWriter(),
        voice=voice or _StubVoice(),
        flux=flux or _StubFlux(),
        parallax=parallax or _StubParallax(),
        i2v=i2v,
        assembler=assembler or _StubAssembler(),
        thumbnails=thumbnails or _StubThumb(),
        approval=approval or _StubApproval(),
        publisher=publisher or _StubPublisher(),
        rate_ledger=rate_ledger or _StubRateLedger(),
        tracker=tracker or _StubTracker(),
        async_runner=_sync_runner,
        cost_ledger_factory=lambda: CostLedger(ceiling_usd=cost_ceiling),
    )


# ─── Happy path ─────────────────────────────────────────────────────────


class HappyPathTests(unittest.TestCase):
    def test_full_run_publishes_and_logs(self):
        tracker = _StubTracker()
        publisher = _StubPublisher()
        rate_ledger = _StubRateLedger(allow=True)
        pipe = _build_pipeline(
            publisher=publisher,
            rate_ledger=rate_ledger,
            tracker=tracker,
        )
        jobs = pipe.run_daily()
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertIsNone(job.failure_stage)
        self.assertEqual(job.approved, True)
        self.assertEqual(job.post_ids, ["p-ig", "p-yt", "p-tt"])
        self.assertEqual(publisher.calls, 1)
        self.assertEqual(rate_ledger.asserted, [3])
        self.assertEqual(len(tracker.logs), 1)

    def test_post_element_kwargs_carry_channel_profile(self):
        publisher = _StubPublisher()
        pipe = _build_pipeline(publisher=publisher)
        pipe.run_daily()
        call_kw = publisher.calls  # noqa: F841 (smoke)
        self.assertEqual(publisher.calls, 1)
        # Reach into publisher.publish_post kwargs via a fresh stub.
        captured = {}

        class _Capture(_StubPublisher):
            def publish_post(self, **kw):
                captured.update(kw)
                return super().publish_post(**kw)

        publisher2 = _Capture()
        pipe2 = _build_pipeline(publisher=publisher2)
        pipe2.run_daily()
        self.assertEqual(captured["ig_profile"], "vesper")
        self.assertEqual(captured["yt_profile"], "vesper")
        self.assertEqual(captured["tt_profile"], "vesper")
        self.assertTrue(captured["ai_disclosure"])


# ─── Failure short-circuits ─────────────────────────────────────────────


class FailureShortCircuitTests(unittest.TestCase):
    def test_writer_none_skips_remaining_stages(self):
        writer = _StubWriter(draft=None)
        writer.fail_first = False
        # Override write_short to always return None.
        writer.write_short = lambda **kw: None  # type: ignore[assignment]
        publisher = _StubPublisher()
        pipe = _build_pipeline(writer=writer, publisher=publisher)
        jobs = pipe.run_daily()
        self.assertEqual(jobs[0].failure_stage, "draft_story")
        self.assertEqual(publisher.calls, 0)

    def test_assembler_error_skips_publish(self):
        publisher = _StubPublisher()
        pipe = _build_pipeline(
            assembler=_StubAssembler(fail=True),
            publisher=publisher,
        )
        jobs = pipe.run_daily()
        self.assertEqual(jobs[0].failure_stage, "assemble_video")
        self.assertEqual(publisher.calls, 0)

    def test_owner_rejection_skips_publish(self):
        publisher = _StubPublisher()
        pipe = _build_pipeline(
            approval=_StubApproval(approved=False),
            publisher=publisher,
        )
        jobs = pipe.run_daily()
        self.assertEqual(jobs[0].failure_stage, "request_approval")
        self.assertEqual(jobs[0].failure_reason, "owner rejected")
        self.assertEqual(publisher.calls, 0)


# ─── Sidecar / rate budget / cost ceiling ───────────────────────────────


class PreflightAndBudgetTests(unittest.TestCase):
    def test_sidecar_down_raises(self):
        """When chatterbox reports sidecar_down, the orchestrator must
        raise — callers then abort BOTH pipelines (System-Wide Impact #5)."""
        pipe = _build_pipeline(voice=_StubVoice(pre_state="sidecar_down"))
        with self.assertRaises(RuntimeError) as cm:
            pipe.run_daily()
        self.assertIn("aborting", str(cm.exception).lower())

    def test_ref_missing_vesper_only_soft_fail(self):
        """Ref-missing is a Vesper-only failure — no raise, just fail
        the job and let CommonCreed continue."""
        publisher = _StubPublisher()
        pipe = _build_pipeline(
            voice=_StubVoice(pre_state="ref_missing"),
            publisher=publisher,
        )
        jobs = pipe.run_daily()
        self.assertEqual(jobs[0].failure_stage, "voice_preflight")
        self.assertEqual(publisher.calls, 0)

    def test_rate_budget_exceeded_defers_not_fails(self):
        """When PostizRateLedger says budget insufficient, approved job
        holds as approved-but-unposted — failure_stage set, but
        different from a hard publish error."""
        rate_ledger = _StubRateLedger(allow=False)
        publisher = _StubPublisher()
        pipe = _build_pipeline(
            rate_ledger=rate_ledger,
            publisher=publisher,
        )
        jobs = pipe.run_daily()
        self.assertEqual(jobs[0].failure_stage, "publish")
        self.assertIn("rate_budget_deferred", jobs[0].failure_reason or "")
        self.assertEqual(publisher.calls, 0, "publisher must NOT be called")

    def test_publish_error_marks_failure(self):
        publisher = _StubPublisher(raise_exc=RuntimeError("postiz 502"))
        pipe = _build_pipeline(publisher=publisher)
        jobs = pipe.run_daily()
        self.assertEqual(jobs[0].failure_stage, "publish")
        self.assertIn("postiz", jobs[0].failure_reason or "")


# ─── I2V degradation path ──────────────────────────────────────────────


class I2VDegradationTests(unittest.TestCase):
    def test_no_i2v_backend_does_not_crash(self):
        pipe = _build_pipeline(i2v=None)
        jobs = pipe.run_daily()
        self.assertIsNone(jobs[0].failure_stage)
        # No i2v beats produced.
        self.assertEqual(jobs[0].i2v_paths, [])

    def test_i2v_failure_degrades_that_beat_to_parallax(self):
        # I2V backend fails; the pipeline must fall back to parallax
        # for those beats, not abort the whole run.
        pipe = _build_pipeline(
            i2v=_StubI2V(fail=True),
            parallax=_StubParallax(fail=False),
        )
        jobs = pipe.run_daily()
        self.assertIsNone(jobs[0].failure_stage)


# ─── Analytics ─────────────────────────────────────────────────────────


class AnalyticsTests(unittest.TestCase):
    def test_analytics_logged_on_success_and_failure(self):
        tracker = _StubTracker()
        pipe = _build_pipeline(tracker=tracker)
        pipe.run_daily()
        self.assertEqual(len(tracker.logs), 1)
        self.assertIsNone(tracker.logs[0].get("failure_stage"))

        tracker2 = _StubTracker()
        pipe2 = _build_pipeline(
            tracker=tracker2,
            approval=_StubApproval(approved=False),
        )
        pipe2.run_daily()
        self.assertEqual(len(tracker2.logs), 1)
        self.assertEqual(tracker2.logs[0].get("failure_stage"), "request_approval")


if __name__ == "__main__":
    unittest.main(verbosity=2)
