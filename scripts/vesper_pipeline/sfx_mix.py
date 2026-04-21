"""SFX mix stage — derive :class:`SfxEvent`s from a timeline and fold
them into the voice track via :func:`scripts.audio.sfx.mix_sfx_into_audio`.

The plan (Key Decision #10) mandates SFX as part of the non-optional
anti-slop polish: cuts between beats, punches on hero-I2V shots, ticks
at the tail of long silent beats. Without SFX the voice track plays
naked against the visuals and reads as amateur — the exact slop
pattern the plan's anti-slop lint exists to prevent.

Event derivation:
  * ``cut`` at each beat transition after the first (skip t=0). Light
    intensity by default; heavy when the previous beat was a hero I2V
    (we cut *out of* impact beats with weight).
  * ``punch`` at the start of each hero_i2v beat (heavy intensity).
  * No ``reveal`` or ``tick`` events in v1 — those need keyword-punch
    timestamps from engagement-v2 which live on CommonCreed and aren't
    yet plumbed through Vesper's timeline planner.

Failure posture: if the pack has no usable .wav files (pre-launch
sourcing step per the launch runbook), the underlying
``pick_sfx`` raises ``FileNotFoundError``. We catch this at the
stage boundary and continue with the raw voice; the pipeline logs
a WARNING so the launch-checklist gap is visible in ops output.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from still_gen._types import BeatMode, Timeline  # noqa: E402

logger = logging.getLogger(__name__)


# Minimum gap between consecutive SFX hits — avoid stacking cuts on top
# of a hero punch + the following cut within <0.3 s. The human ear
# reads anything closer as a mixing glitch.
_MIN_EVENT_GAP_S = 0.25


def derive_sfx_events(
    timeline: Timeline,
    *,
    keyword_punches: Optional[Sequence] = None,
) -> list:
    """Return a list of ``SfxEvent`` dicts keyed to timeline beats +
    (optionally) keyword punches.

    Typed loosely (``Any``) at the public boundary so tests can stub
    :mod:`scripts.audio.sfx` without importing ffmpeg-pinned deps.

    :param keyword_punches: Optional list of ``KeywordPunch``-like
        objects with a ``t_seconds`` attribute. Each emits a light
        ``reveal`` event at that timestamp — the "SFX-flash on
        keyword-punch" cue from plan Key Decision #10.
    """
    from audio.sfx import SfxEvent  # type: ignore

    events: list = []
    cumulative = 0.0
    for idx, beat in enumerate(timeline.beats):
        beat_start = cumulative

        # Punch on the *start* of a hero I2V beat — gives the hero shot
        # its sonic thump.
        if beat.mode == BeatMode.HERO_I2V and idx > 0:
            events.append(SfxEvent(
                t_seconds=round(beat_start, 3),
                category="punch",
                intensity="heavy",
            ))

        # Cut on the transition INTO this beat (skip the very first).
        if idx > 0:
            # Heavy-cut when we're transitioning *out of* a hero shot.
            prev = timeline.beats[idx - 1]
            intensity = "heavy" if prev.mode == BeatMode.HERO_I2V else "light"
            candidate = round(beat_start, 3)
            if not events or candidate - events[-1].t_seconds >= _MIN_EVENT_GAP_S:
                events.append(SfxEvent(
                    t_seconds=candidate,
                    category="cut",
                    intensity=intensity,
                ))

        cumulative += beat.duration_s

    # Keyword-punch reveals — dedup against the cut/punch timeline so
    # a punch that coincides with a hero entry doesn't stack. The
    # detector's own density cap already rate-limits these.
    if keyword_punches:
        existing = sorted(e.t_seconds for e in events)
        for kp in keyword_punches:
            t = round(float(getattr(kp, "t_seconds", 0.0)), 3)
            if _too_close(t, existing):
                continue
            events.append(SfxEvent(
                t_seconds=t, category="reveal", intensity="light",
            ))
            existing.append(t)
            existing.sort()
    return events


def _too_close(t: float, sorted_existing: List[float]) -> bool:
    """Return True if ``t`` is within ``_MIN_EVENT_GAP_S`` of any
    timestamp in the pre-sorted list (O(N) — N is small enough)."""
    for e in sorted_existing:
        if abs(t - e) < _MIN_EVENT_GAP_S:
            return True
    return False


# ─── Stage wrapper ─────────────────────────────────────────────────────────


@dataclass
class SfxMixStage:
    """Callable stage the orchestrator invokes between transcribe +
    plan_timeline. Mutates ``job.voice_path`` in place with the mixed
    audio path.

    Both the mixer and the event-deriver are injectable so tests run
    without the real ffmpeg-backed ``mix_sfx_into_audio``.
    """

    pack_name: str
    mixer: Optional[Callable[..., str]] = None
    event_deriver: Optional[Callable[[Timeline], list]] = None

    def run(self, *, job: Any, output_dir: str) -> bool:
        """Return ``True`` when mixing produced a new audio file; ``False``
        when the stage no-opped (no timeline, no voice, or pack absent).

        Never raises — mix failures log WARNING and leave the raw voice
        in place. Per Key Decision #10 the assembler CAN render without
        SFX (produces amateur-reading audio) but MUST NOT hard-fail the
        whole short over SFX errors.
        """
        timeline = getattr(job, "timeline", None)
        voice_path = getattr(job, "voice_path", None)
        if timeline is None or not voice_path:
            return False

        deriver = self.event_deriver or derive_sfx_events
        kwargs: dict = {}
        kp = getattr(job, "keyword_punches", None)
        if kp:
            kwargs["keyword_punches"] = kp
        events = deriver(timeline, **kwargs) if kwargs else deriver(timeline)
        if not events:
            logger.info("SfxMixStage: no events derived for job=%s",
                        getattr(job, "job_id", "?"))
            return False

        mixer = self.mixer or _default_mixer
        out_path = os.path.join(
            output_dir, f"{getattr(job, 'job_id', 'voice')}_mixed.mp3",
        )
        try:
            mixer(
                audio_path=voice_path,
                sfx_events=events,
                output_path=out_path,
                seed=_seed_from_job(job),
                pack=self.pack_name,
            )
        except FileNotFoundError as exc:
            logger.warning(
                "SfxMixStage: pack=%s missing .wav files (%s); "
                "continuing with raw voice. See "
                "docs/runbooks/vesper/vesper-launch-runbook.md.",
                self.pack_name, exc,
            )
            return False
        except Exception as exc:
            logger.warning(
                "SfxMixStage: mixer error for job=%s: %s; "
                "continuing with raw voice",
                getattr(job, "job_id", "?"), exc,
            )
            return False

        # Swap in the mixed audio. Raw voice stays on disk for debugging.
        job.voice_path = out_path
        logger.info(
            "SfxMixStage: wrote %s (%d events, pack=%s)",
            out_path, len(events), self.pack_name,
        )
        return True


def _default_mixer(**kwargs):
    """Lazy import so tests / packaging without ffmpeg don't pay the cost."""
    from audio.sfx import mix_sfx_into_audio  # type: ignore
    return mix_sfx_into_audio(**kwargs)


def _seed_from_job(job: Any) -> int:
    """Deterministic per-job seed so SFX picks are reproducible
    across retries of the same topic."""
    jid = getattr(job, "job_id", "") or ""
    return sum(ord(c) for c in jid) or 1


__all__ = ["SfxMixStage", "derive_sfx_events"]
