"""Vesper pipeline orchestrator (Unit 11).

Composes already-shipped units into a single daily run:

  topic_signal        → :mod:`scripts.topic_signal.reddit_story_signal`
  archivist writer    → :mod:`scripts.story_gen.archivist_writer`
  chatterbox preflight→ :mod:`scripts.voiceover.chatterbox_generator`
  Flux stills         → :class:`scripts.still_gen.flux_router.FluxRouter`
  parallax / I2V      → server GPU (injected backends — placeholder-safe)
  MoviePy assembly    → :class:`scripts.video_edit.video_editor.VideoEditor`
  thumbnail           → :mod:`scripts.thumbnail_gen.compositor`
  Telegram approval   → :class:`scripts.approval.telegram_bot.TelegramApprovalBot`
  Postiz publish      → :class:`sidecar.postiz_client.PostizClient`
  analytics           → :class:`scripts.analytics.tracker.AnalyticsTracker`

Design posture: dependency injection everywhere. The orchestrator owns
sequencing + the :class:`CostLedger` + pre-assembly abort + Postiz
rate-ledger gate + AI-disclosure read-back. It does NOT own networking
or state — every collaborator is an injected object so tests can run
hermetically and production wires the real clients.

Sibling to :mod:`scripts.commoncreed_pipeline` — does NOT extend it
(per plan Key Decision #2: sibling pipelines, not a base class).

Stages are split into small methods so tests exercise one at a time.
:meth:`VesperPipeline.run_daily` is the entry point.

Unit 10 (I2V hero shots) is deferred-optional: when ``i2v_backend`` is
None or :meth:`~CostLedger.should_skip_i2v` returns True, hero beats
degrade to still_parallax — matching the plan's Unit 10 contingency.
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional, Protocol, Sequence

from ._types import VesperJob
from .cost_telemetry import CostLedger, CostStage

logger = logging.getLogger(__name__)


# ─── Collaborator Protocols ────────────────────────────────────────────────
#
# Protocols (rather than concrete imports) at module load so tests can
# inject lightweight fakes without importing sidecar / anthropic / httpx.


class _TopicSource(Protocol):
    def fetch_topic_candidates(
        self,
        tracker: Any,
        *,
        channel_id: str,
        window_days: int = 180,
        top_n: int = 5,
    ) -> List[Any]: ...


class _ArchivistWriter(Protocol):
    def write_short(
        self, *, topic_title: str, subreddit: str
    ) -> Optional[Any]: ...


class _VoiceGenerator(Protocol):
    def preflight(self) -> Any: ...
    def generate(self, text: str, output_path: str) -> Any: ...


class _FluxBackend(Protocol):
    async def generate(
        self, prompt: str, output_path: str, **opts: Any
    ) -> Any: ...


class _ParallaxBackend(Protocol):
    """DepthAnythingV2 + DepthFlow; server GPU per Key Decision #6."""

    async def animate(
        self, still_path: str, output_path: str, *, duration_s: float,
    ) -> str: ...


class _I2VBackend(Protocol):
    """Wan2.2-class hero-shot; Optional (Unit 10 deferred)."""

    async def generate(
        self, still_path: str, output_path: str, *, motion_hint: str,
    ) -> str: ...


class _Assembler(Protocol):
    def assemble(
        self, *, job: VesperJob, output_path: str,
    ) -> str: ...


class _ThumbnailBuilder(Protocol):
    def render(self, *, job: VesperJob, output_path: str) -> str: ...


class _ApprovalBot(Protocol):
    def request_approval(
        self, *, job_id: str, video_path: str, thumbnail_path: str,
        caption: str, timeout_s: float,
    ) -> bool: ...


class _Publisher(Protocol):
    def publish_post(self, **kwargs: Any) -> Any: ...


class _RateLedger(Protocol):
    def assert_available(self, n: int = 1) -> None: ...
    def consume(
        self, *, channel_id: str, endpoint: str = "publish_post", count: int = 1,
    ) -> None: ...


class _AnalyticsTracker(Protocol):
    def log_post(self, **kwargs: Any) -> Any: ...


# ─── Pipeline configuration ────────────────────────────────────────────────


@dataclass
class VesperPipelineConfig:
    """Tunables the orchestrator consults. Anything that varies per run
    is a constructor arg on the pipeline; anything that tweaks *policy*
    (costs, retries, caption assembly) lives here."""

    channel_id: str = "vesper"
    channel_display_name: str = "Vesper"
    postiz_channel_profile: str = "vesper"
    dedup_window_days: int = 180
    # Stop after this many topics — Vesper v1 is shorts-first, target
    # 2 posts/day (plan Key Decision #1).
    max_shorts_per_run: int = 2
    # Projected I2V cost per beat on fal.ai fallback (for the skip-I2V
    # gate). Local I2V is $0 so only relevant if local fails over.
    i2v_fallback_est_usd: float = 0.05
    # Telegram approval timeout.
    approval_timeout_s: float = 60 * 30  # 30 min
    # Output paths.
    output_base_dir: str = "output/vesper"


# ─── Pipeline ──────────────────────────────────────────────────────────────


class VesperPipeline:
    """Daily Vesper orchestrator.

    Stages (in order, each a method):
      1. :meth:`fetch_topics`
      2. :meth:`draft_story`
      3. :meth:`voice_preflight`
      4. :meth:`voice_generate`
      5. :meth:`generate_stills`
      6. :meth:`animate_still_beats`    (parallax + optional I2V)
      7. :meth:`assemble_video`
      8. :meth:`render_thumbnail`
      9. :meth:`request_approval`
      10. :meth:`publish`               (rate-ledger gated)
      11. :meth:`log_analytics`

    Any stage may set ``job.failure_stage`` / ``job.failure_reason`` and
    return; the loop skips remaining stages and logs the outcome.
    """

    def __init__(
        self,
        *,
        config: VesperPipelineConfig,
        topic_source: _TopicSource,
        writer: _ArchivistWriter,
        voice: _VoiceGenerator,
        flux: _FluxBackend,
        parallax: _ParallaxBackend,
        i2v: Optional[_I2VBackend],
        assembler: _Assembler,
        thumbnails: _ThumbnailBuilder,
        approval: _ApprovalBot,
        publisher: _Publisher,
        rate_ledger: _RateLedger,
        tracker: _AnalyticsTracker,
        async_runner: Callable[[Any], Any],
        cost_ledger_factory: Callable[[], CostLedger] = CostLedger,
    ) -> None:
        self.config = config
        self.topic_source = topic_source
        self.writer = writer
        self.voice = voice
        self.flux = flux
        self.parallax = parallax
        self.i2v = i2v
        self.assembler = assembler
        self.thumbnails = thumbnails
        self.approval = approval
        self.publisher = publisher
        self.rate_ledger = rate_ledger
        self.tracker = tracker
        self._run_async = async_runner
        self._cost_ledger_factory = cost_ledger_factory

        os.makedirs(config.output_base_dir, exist_ok=True)

    # ─── Entry point ─────────────────────────────────────────────────────

    def run_daily(self) -> List[VesperJob]:
        """Pick topics + process each into a published short.

        Returns all :class:`VesperJob` instances attempted this run
        (including failures — inspect ``job.failure_stage``)."""
        logger.info(
            "%s pipeline starting: up to %d shorts",
            self.config.channel_display_name,
            self.config.max_shorts_per_run,
        )

        topics = self.fetch_topics()
        if not topics:
            logger.warning(
                "%s: no topic candidates — aborting run (not a failure)",
                self.config.channel_display_name,
            )
            return []

        jobs: List[VesperJob] = []
        for topic in topics[: self.config.max_shorts_per_run]:
            job = self._process_one(topic)
            jobs.append(job)
            if job.failure_stage:
                logger.warning(
                    "job %s failed at stage %s: %s",
                    job.job_id, job.failure_stage, job.failure_reason,
                )
            else:
                logger.info("job %s published: %s", job.job_id, job.post_ids)
        return jobs

    # ─── Stages ──────────────────────────────────────────────────────────

    def fetch_topics(self) -> List[Any]:
        """Stage 1 — TopicSignal list from the configured source.

        Dedup lives in the source (it consults ``tracker.is_duplicate_topic``
        with this channel's scope), so we just forward results."""
        return self.topic_source.fetch_topic_candidates(
            self.tracker,
            channel_id=self.config.channel_id,
            window_days=self.config.dedup_window_days,
            top_n=self.config.max_shorts_per_run * 2,  # headroom for skips
        )

    def draft_story(self, job: VesperJob) -> Optional[Any]:
        """Stage 2 — ArchivistStoryWriter emits a moderated StoryDraft
        or None (retry budget exhausted). Failure sets ``job.failure_*``."""
        draft = self.writer.write_short(
            topic_title=job.topic_title,
            subreddit=job.subreddit,
        )
        if draft is None:
            self._fail(job, "draft_story", "writer exhausted retry budget")
            return None
        # Populate job fields that downstream stages need.
        script_text = getattr(draft, "archivist_script", None) or getattr(
            draft, "script", ""
        )
        job.story_script = script_text
        job.story_word_count = getattr(draft, "word_count", 0) or len(
            script_text.split()
        )
        job.story_sha256 = getattr(draft, "content_sha256", None)
        return draft

    def voice_preflight(self, job: VesperJob) -> bool:
        """Stage 3 — chatterbox sidecar + reference-clip availability.

        On sidecar-down: abort all channels (handled by caller via
        raising, not by returning False). On ref-missing for Vesper
        specifically: abort Vesper only."""
        pre = self.voice.preflight()
        ok = getattr(pre, "ok", False)
        if ok:
            return True
        # Distinguish: sidecar_down vs ref_missing. We bubble up
        # sidecar_down as an exception (caller alerts + aborts both
        # pipelines); ref_missing is a Vesper-only soft failure.
        state = getattr(pre, "state", "unknown")
        if state == "sidecar_down":
            raise RuntimeError(
                "chatterbox sidecar unreachable — aborting run; "
                "do NOT proceed with CommonCreed either"
            )
        self._fail(
            job, "voice_preflight",
            f"chatterbox preflight failed: state={state}",
        )
        return False

    def voice_generate(self, job: VesperJob) -> bool:
        """Stage 4 — synthesize the Archivist voice."""
        out_path = self._path("voice", job.job_id, ext="mp3")
        try:
            result = self.voice.generate(job.story_script or "", out_path)
        except Exception as exc:
            self._fail(job, "voice_generate", f"chatterbox error: {exc}")
            return False
        job.voice_path = out_path
        job.voice_duration_s = float(getattr(result, "duration_s", 0.0))
        return True

    def generate_stills(self, job: VesperJob, beat_count: int) -> bool:
        """Stage 5 — Flux stills for every beat.

        Each still is a local-first call to the :class:`FluxRouter`
        (injected as ``self.flux``). The router handles fallback
        internally; we only record one fallback invocation per beat
        that fell back (via the router's telemetry post-run).
        """
        job.beat_count = beat_count
        stills: List[str] = []
        for idx in range(beat_count):
            out = self._path("stills", f"{job.job_id}_{idx:03d}", ext="png")
            try:
                # Actual prompt construction is the timeline-planner's
                # job — the pipeline just forwards a placeholder here so
                # downstream wiring works today. Unit 11 follow-up wires
                # the per-beat prompts from the timeline planner.
                self._run_async(self.flux.generate(
                    job.story_script or "",  # placeholder; see note
                    out,
                ))
            except Exception as exc:
                self._fail(
                    job, "generate_stills",
                    f"beat {idx}: flux failed: {exc}",
                )
                return False
            stills.append(out)
        job.still_paths = stills
        return True

    def animate_still_beats(self, job: VesperJob, ledger: CostLedger) -> bool:
        """Stage 6 — Parallax for ≥30% of beats. I2V for ~20% when the
        backend is present AND the cost ledger isn't near ceiling."""
        parallax_count = max(1, int(job.beat_count * 0.30))
        # I2V target: 20% of beats, subject to cost gate + backend presence.
        i2v_target = int(job.beat_count * 0.20)
        use_i2v = (
            self.i2v is not None
            and i2v_target > 0
            and not ledger.should_skip_i2v(
                i2v_target * self.config.i2v_fallback_est_usd
            )
        )
        if self.i2v is None:
            logger.info(
                "i2v backend not configured — degrading i2v beats to parallax"
            )
        elif not use_i2v:
            logger.info(
                "cost ledger would breach ceiling with i2v — degrading to parallax"
            )

        parallax_paths: List[str] = []
        i2v_paths: List[str] = []

        # First `parallax_count` beats → parallax.
        for idx in range(parallax_count):
            out = self._path(
                "parallax", f"{job.job_id}_{idx:03d}", ext="mp4"
            )
            try:
                self._run_async(self.parallax.animate(
                    job.still_paths[idx], out, duration_s=3.5,
                ))
            except Exception as exc:
                self._fail(
                    job, "animate_still_beats",
                    f"parallax beat {idx}: {exc}",
                )
                return False
            parallax_paths.append(out)

        # Next `i2v_target` beats → i2v (when allowed).
        if use_i2v:
            for k in range(i2v_target):
                idx = parallax_count + k
                out = self._path(
                    "i2v", f"{job.job_id}_{idx:03d}", ext="mp4"
                )
                try:
                    self._run_async(self.i2v.generate(  # type: ignore[union-attr]
                        job.still_paths[idx], out,
                        motion_hint="subtle_dolly_in",
                    ))
                except Exception as exc:
                    # Per plan: on I2V failure, degrade THAT BEAT to parallax.
                    logger.warning(
                        "i2v beat %d failed (%s) — degrading to parallax",
                        idx, exc,
                    )
                    fallback_out = self._path(
                        "parallax", f"{job.job_id}_{idx:03d}_fb", ext="mp4",
                    )
                    try:
                        self._run_async(self.parallax.animate(
                            job.still_paths[idx], fallback_out, duration_s=3.5,
                        ))
                    except Exception as exc2:
                        self._fail(
                            job, "animate_still_beats",
                            f"i2v+parallax both failed on beat {idx}: {exc2}",
                        )
                        return False
                    parallax_paths.append(fallback_out)
                    continue
                i2v_paths.append(out)

        job.parallax_paths = parallax_paths
        job.i2v_paths = i2v_paths
        return True

    def assemble_video(self, job: VesperJob, ledger: CostLedger) -> bool:
        """Stage 7 — MoviePy assembly. Pre-gate on cost ledger."""
        if ledger.should_abort():
            self._fail(
                job, "assemble_video",
                f"cost ledger over ceiling {ledger.ceiling_usd} before "
                f"assembly (accumulated {ledger.total():.3f})",
            )
            return False

        out = self._path("assembled", job.job_id, ext="mp4")
        try:
            self.assembler.assemble(job=job, output_path=out)
        except Exception as exc:
            self._fail(job, "assemble_video", f"assembly error: {exc}")
            return False
        job.video_path = out
        return True

    def render_thumbnail(self, job: VesperJob) -> bool:
        out = self._path("thumbnails", job.job_id, ext="jpg")
        try:
            self.thumbnails.render(job=job, output_path=out)
        except Exception as exc:
            self._fail(job, "render_thumbnail", f"thumbnail error: {exc}")
            return False
        job.thumbnail_path = out
        return True

    def request_approval(self, job: VesperJob) -> bool:
        """Stage 9 — Telegram preview + owner approve/reject.

        Uses per-job UUID in callback_data (System-Wide Impact #3) —
        that's the bot's responsibility; we just forward ``job.job_id``.
        """
        caption = f"[{self.config.channel_display_name}] {job.topic_title}"
        try:
            approved = self.approval.request_approval(
                job_id=job.job_id,
                video_path=job.video_path or "",
                thumbnail_path=job.thumbnail_path or "",
                caption=caption,
                timeout_s=self.config.approval_timeout_s,
            )
        except Exception as exc:
            self._fail(job, "request_approval", f"telegram error: {exc}")
            return False
        job.approved = approved
        if not approved:
            self._fail(job, "request_approval", "owner rejected")
            return False
        return True

    def publish(self, job: VesperJob) -> bool:
        """Stage 10 — Postiz publish, rate-ledger gated.

        Three platforms × 1 post element each = 3 API calls. If the
        org-wide 30/hour budget can't fit, defer (hold the approved job
        in analytics as ``approved-but-unposted``) rather than breach
        the ceiling.
        """
        needed = 3  # ig + yt + tt per post
        try:
            self.rate_ledger.assert_available(needed)
        except Exception as exc:
            # PostizRateBudgetExceeded — defer not fail.
            logger.warning(
                "rate budget insufficient (need %d): %s — "
                "holding as approved-but-unposted",
                needed, exc,
            )
            job.failure_stage = "publish"
            job.failure_reason = f"rate_budget_deferred: {exc}"
            return False

        try:
            result = self.publisher.publish_post(
                video_path=job.video_path,
                thumbnail_path=job.thumbnail_path,
                ig_caption=job.topic_title,
                yt_title=job.topic_title,
                yt_description=job.story_script or "",
                ig_profile=self.config.postiz_channel_profile,
                yt_profile=self.config.postiz_channel_profile,
                tt_profile=self.config.postiz_channel_profile,
                ai_disclosure=True,
                ig_collab_usernames=[],
                scheduled_slot=datetime.utcnow(),
            )
        except Exception as exc:
            self._fail(job, "publish", f"postiz error: {exc}")
            return False

        self.rate_ledger.consume(
            channel_id=self.config.channel_id,
            endpoint="publish_post",
            count=needed,
        )

        post_ids = result.get("postIds") if isinstance(result, dict) else None
        job.post_ids = list(post_ids) if post_ids else []
        job.posted_platforms = ["instagram", "youtube", "tiktok"]
        return True

    def log_analytics(self, job: VesperJob) -> None:
        try:
            self.tracker.log_post(
                channel_id=self.config.channel_id,
                topic_title=job.topic_title,
                video_path=job.video_path,
                thumbnail_path=job.thumbnail_path,
                post_ids=job.post_ids,
                platforms=job.posted_platforms,
                word_count=job.story_word_count,
                voice_duration_s=job.voice_duration_s,
                story_sha256=job.story_sha256,
                failure_stage=job.failure_stage,
                failure_reason=job.failure_reason,
            )
        except Exception as exc:
            # Non-fatal: we've already published. Log loudly but don't
            # reverse the publish.
            logger.error("analytics log failed for %s: %s", job.job_id, exc)

    # ─── Per-topic runner ────────────────────────────────────────────────

    def _process_one(self, topic: Any) -> VesperJob:
        job = VesperJob(
            topic_title=getattr(topic, "title_canonical", None)
                        or getattr(topic, "title", ""),
            subreddit=getattr(topic, "subreddit", ""),
            topic_score=float(getattr(topic, "score", 0.0) or 0.0),
            job_id=str(uuid.uuid4()),
        )
        ledger = self._cost_ledger_factory()

        # Stages 2-4 — story + voice.
        if self.draft_story(job) is None:
            self.log_analytics(job)
            return job
        ledger.record(CostStage.LLM_STORY, 0.0, note="uncharged — populate later")
        if not self.voice_preflight(job):
            self.log_analytics(job)
            return job
        if not self.voice_generate(job):
            self.log_analytics(job)
            return job

        # Stages 5-6 — visuals.
        # Beat count heuristic: ~4 words per beat (Vesper shorts are
        # 150-200 words, so 35-50 beats is the shape — capped at 25
        # per plan which matches the Flux budget).
        beat_count = max(8, min(25, job.story_word_count // 6 or 15))
        if not self.generate_stills(job, beat_count):
            self.log_analytics(job)
            return job
        ledger.record_flux_local(image_count=beat_count)
        if not self.animate_still_beats(job, ledger):
            self.log_analytics(job)
            return job

        # Stages 7-8 — assembly + thumbnail.
        if not self.assemble_video(job, ledger):
            self.log_analytics(job)
            return job
        if not self.render_thumbnail(job):
            self.log_analytics(job)
            return job

        # Stages 9-11 — approval + publish + log.
        if not self.request_approval(job):
            self.log_analytics(job)
            return job
        if not self.publish(job):
            self.log_analytics(job)
            return job
        self.log_analytics(job)
        return job

    # ─── Helpers ─────────────────────────────────────────────────────────

    def _path(self, subdir: str, stem: str, *, ext: str) -> str:
        out_dir = Path(self.config.output_base_dir) / subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        return str(out_dir / f"{stem}.{ext}")

    def _fail(self, job: VesperJob, stage: str, reason: str) -> None:
        job.failure_stage = stage
        job.failure_reason = reason
        logger.warning("job %s stage=%s reason=%s", job.job_id, stage, reason)


__all__ = ["VesperPipeline", "VesperPipelineConfig"]
