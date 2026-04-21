"""Types for the still-timeline planner + anti-slop lint.

A :class:`Timeline` is a sequence of :class:`Beat` entries the
orchestrator uses to render the visual track. Each beat carries:

  * ``mode`` — how the beat is rendered (still + Ken Burns, still +
    parallax, or hero I2V clip)
  * ``motion_hint`` — which camera move the renderer applies
  * ``duration_s`` — on-screen duration
  * ``shot_class`` — interior/exterior/establishing/close_up/insert/
    character; drives overlay-pack routing per Security Posture / plan
    design notes
  * ``prompt`` — Flux still prompt (populated for still modes;
    ignored for hero_i2v which uses its own prompt template in Unit 10)

The timeline lives up-front of both Flux generation (needs the
prompts) and the orchestrator's render loop. Anti-slop lint runs
between timeline planning and rendering so a bad shape never hits
the expensive render stage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Literal, Optional, Sequence


class BeatMode(str, Enum):
    """How the visual layer renders a single beat."""

    STILL_KENBURNS = "still_kenburns"   # ~50% of beats — gentle pan/zoom
    STILL_PARALLAX = "still_parallax"   # ≥30% of beats — Depth V2 + DepthFlow
    HERO_I2V = "hero_i2v"               # ~20% of beats — local I2V clip


ShotClass = Literal[
    "interior",
    "exterior",
    "establishing",
    "close_up",
    "insert",
    "character",
]


CameraMove = Literal[
    # Ken Burns primitives (matches existing zoompan expressions)
    "push_in",
    "pull_back",
    "slow_pan_left",
    "slow_pan_right",
    # Parallax moves
    "push_in_2d",
    "orbit_slight",
    "dolly_in_subtle",
    # I2V motion hints
    "subtle_dolly_in",
    "slow_pan",
    "breathing_mist",
    "shadow_movement",
    "face_stare",
]


@dataclass(frozen=True)
class Beat:
    mode: BeatMode
    motion_hint: CameraMove
    duration_s: float
    shot_class: ShotClass
    # Flux prompt — required for STILL_* modes. Leave empty for HERO_I2V
    # (Unit 10's I2V workflow has its own motion-prompt template).
    prompt: str = ""
    # Optional free-form tag from the story planner (e.g. "hook", "climax").
    tag: str = ""

    def is_still(self) -> bool:
        return self.mode in (BeatMode.STILL_KENBURNS, BeatMode.STILL_PARALLAX)


@dataclass(frozen=True)
class Timeline:
    """An ordered sequence of beats describing a short's visual track."""

    beats: Sequence[Beat]

    @property
    def total_duration_s(self) -> float:
        return sum(b.duration_s for b in self.beats)

    @property
    def count(self) -> int:
        return len(self.beats)

    def mode_counts(self) -> dict[BeatMode, int]:
        counts = {m: 0 for m in BeatMode}
        for b in self.beats:
            counts[b.mode] += 1
        return counts

    def parallax_ratio(self) -> float:
        if not self.beats:
            return 0.0
        return self.mode_counts()[BeatMode.STILL_PARALLAX] / self.count

    def hero_i2v_ratio(self) -> float:
        if not self.beats:
            return 0.0
        return self.mode_counts()[BeatMode.HERO_I2V] / self.count
