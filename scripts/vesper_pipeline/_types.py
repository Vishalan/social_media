"""Vesper pipeline value types.

:class:`VesperJob` is the analogue of :class:`VideoJob` in the
CommonCreed pipeline — it carries the per-run state from topic
selection through publish + log. Unlike :class:`VideoJob` it has no
avatar fields (Vesper is faceless); unlike Reddit-content pipelines it
never carries post body text (:class:`TopicSignal`'s forbidden-fields
check enforces that at the source).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional


@dataclass
class VesperJob:
    """Per-run state for one Vesper short.

    Populated stage-by-stage. Missing fields at any stage imply the
    pipeline aborted before that stage — the orchestrator inspects
    the field pattern to decide whether to alert, retry, or skip.
    """

    # ─── Topic + script ───
    topic_title: str
    subreddit: str
    job_id: str
    topic_score: float = 0.0
    archetype_family: Optional[str] = None

    # ─── LLM-original script + mod filter ───
    story_script: Optional[str] = None
    story_word_count: int = 0
    story_sha256: Optional[str] = None            # content hash, not raw text (S7)

    # ─── Voice (chatterbox) ───
    voice_path: Optional[str] = None              # mp3/wav on disk
    voice_duration_s: float = 0.0
    # Word-level timings from faster-whisper: {word, start, end}
    caption_segments: List[dict] = field(default_factory=list)

    # ─── Timeline + visuals ───
    beat_count: int = 0
    # Populated by the timeline_planner stage when wired. Left Any so
    # this module doesn't force importing still_gen at type-check time.
    timeline: Optional[Any] = None
    still_paths: List[str] = field(default_factory=list)
    parallax_paths: List[str] = field(default_factory=list)
    i2v_paths: List[str] = field(default_factory=list)

    # ─── Assembly + thumbnail ───
    video_path: Optional[str] = None              # final MP4 ready for review
    thumbnail_path: Optional[str] = None

    # ─── Approval + publish ───
    telegram_message_id: Optional[int] = None
    approved: Optional[bool] = None               # None = not asked yet
    post_ids: List[str] = field(default_factory=list)
    posted_platforms: List[str] = field(default_factory=list)

    # ─── Bookkeeping ───
    created_at: datetime = field(default_factory=datetime.utcnow)
    failure_stage: Optional[str] = None           # non-None iff aborted
    failure_reason: Optional[str] = None


__all__ = ["VesperJob"]
