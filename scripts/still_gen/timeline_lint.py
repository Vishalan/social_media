"""Anti-slop timeline validator (plan R7 + Key Decision 10).

Runs between timeline planning and rendering so a bad timeline never
eats the Flux + I2V render budget. Rules:

  L1. Duration variance — no more than ``max_consecutive_same_duration``
      consecutive beats at the same duration (±``duration_tolerance_s``).
  L2. Parallax ratio — at least ``min_parallax_ratio`` of beats use
      STILL_PARALLAX (gives the 80% still-based beats real depth).
  L3. Hero I2V ratio — at least ``min_hero_i2v_ratio`` of beats are
      HERO_I2V when hero_i2v is enabled (0 when Unit 10 is deferred).
  L4. Move diversity — at least ``min_move_types`` distinct
      ``motion_hint`` values across the timeline.
  L5. Non-Ken-Burns move — at least one beat uses a non-Ken-Burns
      camera move (parallax push_in_2d / orbit_slight / I2V motion
      hint) so the short doesn't read as a pure slideshow.
  L6. Total-duration sanity — timeline total between
      ``min_total_s`` and ``max_total_s``.

Rules are deterministic and unit-testable — lint runs as a pure
function on the :class:`Timeline` + a :class:`LintPolicy`. Violations
are collected into a :class:`LintReport`; callers decide whether
violations trigger regeneration (default) or soft-warn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Set

from ._types import Beat, BeatMode, Timeline


# Ken Burns primitives — treated as "slideshow" moves for L5.
_KEN_BURNS_MOVES = {
    "push_in",
    "pull_back",
    "slow_pan_left",
    "slow_pan_right",
}


@dataclass(frozen=True)
class LintPolicy:
    min_parallax_ratio: float = 0.30
    min_hero_i2v_ratio: float = 0.20
    hero_i2v_enabled: bool = True          # Unit 10 may defer → False
    max_consecutive_same_duration: int = 3
    duration_tolerance_s: float = 0.15
    min_move_types: int = 3
    min_total_s: float = 45.0
    max_total_s: float = 95.0              # 60-90 s short + buffer


@dataclass(frozen=True)
class LintViolation:
    rule: str            # "L1" .. "L6"
    detail: str


@dataclass(frozen=True)
class LintReport:
    violations: List[LintViolation] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations

    def summary(self) -> str:
        if self.ok:
            return "ok"
        return "; ".join(f"{v.rule}: {v.detail}" for v in self.violations)


def _durations_cluster(
    timeline: Timeline,
    tolerance_s: float,
) -> List[List[int]]:
    """Group consecutive beats at the *same* duration (±tolerance_s).

    Clustering anchor is the **first** beat in the cluster — not the
    previous beat — so a monotone drift like ``3.0, 3.1, 3.2, 3.3`` at
    0.15 s tolerance correctly reads as varying durations rather than
    one big cluster. Only genuinely-identical runs (``3.0, 3.0, 3.0``)
    form a single cluster.
    """
    clusters: List[List[int]] = []
    current: List[int] = []
    anchor: float = -1.0
    for i, b in enumerate(timeline.beats):
        if not current:
            current.append(i)
            anchor = b.duration_s
        elif abs(b.duration_s - anchor) <= tolerance_s:
            current.append(i)
        else:
            clusters.append(current)
            current = [i]
            anchor = b.duration_s
    if current:
        clusters.append(current)
    return clusters


def lint_timeline(timeline: Timeline, policy: LintPolicy = LintPolicy()) -> LintReport:
    """Return a :class:`LintReport` for ``timeline`` under ``policy``."""
    violations: List[LintViolation] = []

    if timeline.count == 0:
        return LintReport([LintViolation("L6", "timeline has zero beats")])

    # ── L1: duration variance ──────────────────────────────────────────────
    clusters = _durations_cluster(timeline, policy.duration_tolerance_s)
    for cluster in clusters:
        if len(cluster) > policy.max_consecutive_same_duration:
            violations.append(LintViolation(
                "L1",
                f"{len(cluster)} consecutive beats at ~same duration "
                f"(indices {cluster[0]}..{cluster[-1]})",
            ))
            break  # one L1 report is enough

    # ── L2: parallax ratio ─────────────────────────────────────────────────
    ratio = timeline.parallax_ratio()
    if ratio < policy.min_parallax_ratio:
        violations.append(LintViolation(
            "L2",
            f"parallax ratio {ratio:.0%} < required {policy.min_parallax_ratio:.0%}",
        ))

    # ── L3: hero I2V ratio (only when hero_i2v is enabled) ─────────────────
    if policy.hero_i2v_enabled:
        hero_ratio = timeline.hero_i2v_ratio()
        if hero_ratio < policy.min_hero_i2v_ratio:
            violations.append(LintViolation(
                "L3",
                f"hero I2V ratio {hero_ratio:.0%} < required "
                f"{policy.min_hero_i2v_ratio:.0%}",
            ))
    else:
        # When Unit 10 defers, assert the timeline does NOT contain any
        # hero_i2v beats — renderer would fail on them.
        if timeline.hero_i2v_ratio() > 0:
            violations.append(LintViolation(
                "L3",
                "hero_i2v beats present but hero_i2v_enabled=False",
            ))

    # ── L4: move diversity ─────────────────────────────────────────────────
    moves: Set[str] = {b.motion_hint for b in timeline.beats}
    if len(moves) < policy.min_move_types:
        violations.append(LintViolation(
            "L4",
            f"only {len(moves)} distinct camera moves "
            f"({sorted(moves)}); need ≥ {policy.min_move_types}",
        ))

    # ── L5: at least one non-Ken-Burns move ─────────────────────────────────
    non_kb = [b for b in timeline.beats if b.motion_hint not in _KEN_BURNS_MOVES]
    if not non_kb:
        violations.append(LintViolation(
            "L5",
            "no non-Ken-Burns moves (reads as slideshow)",
        ))

    # ── L6: total duration sanity ──────────────────────────────────────────
    total = timeline.total_duration_s
    if total < policy.min_total_s:
        violations.append(LintViolation(
            "L6",
            f"total duration {total:.1f}s < min {policy.min_total_s}s",
        ))
    elif total > policy.max_total_s:
        violations.append(LintViolation(
            "L6",
            f"total duration {total:.1f}s > max {policy.max_total_s}s",
        ))

    return LintReport(violations)


__all__ = ["LintPolicy", "LintReport", "LintViolation", "lint_timeline"]
