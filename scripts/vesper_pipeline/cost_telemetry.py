"""Per-short cost ledger (plan Unit 11).

Accumulates estimated dollar spend across LLM tokens, Flux images, and
any fal.ai fallback invocations during one pipeline run. Used for:

  1. **Pre-assembly abort.** After the Flux stage but before MoviePy
     assembly (the expensive stage), if projected total breaches the
     per-short ceiling we skip hero I2V and fall back to all-parallax.
     If even that projects over, abort the whole run with an alert
     rather than burn further budget.
  2. **Daily report telemetry.** Orchestrator snapshots the final
     ledger into ``AnalyticsTracker`` so the operator can see per-short
     cost trends + fallback-invocation rate at a glance.

Cost model (per plan Key Decision #7 after flipping Flux to local):

  * LLM tokens — dominant. Opus/Sonnet story (~$0.15-0.30) +
    Haiku timeline (~$0.01-0.03) + Haiku mod filter (~$0.005-0.01).
  * Flux local = ~$0 (power-only, not modeled).
  * Flux fal.ai fallback — only when invoked. Priced per variant.
  * I2V local = ~$0 (same reasoning).

Ceiling is caller-configurable. Default is $0.75 matching the plan's
post-GPU-consolidation projection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)

# Plan Key Decision #7 + Unit 11 cost telemetry — default ceiling after
# flipping Flux primary path to local 3090 (drops Flux cost to ~$0).
DEFAULT_CEILING_USD = 0.75


class CostStage(str, Enum):
    """Named spend categories. Kept as an enum so telemetry is typed
    and typos at log-write time fail fast."""

    LLM_STORY = "llm_story"
    LLM_TIMELINE = "llm_timeline"
    LLM_MOD_FILTER = "llm_mod_filter"
    FLUX_LOCAL = "flux_local"         # always $0 — present for symmetry
    FLUX_FALLBACK = "flux_fallback"   # fal.ai per-image
    CHATTERBOX = "chatterbox"         # $0 local
    PARALLAX = "parallax"             # $0 local
    I2V = "i2v"                       # $0 local
    OTHER = "other"


@dataclass
class CostEntry:
    stage: CostStage
    amount_usd: float
    note: str = ""


@dataclass
class CostProjection:
    """Snapshot view used by the pre-assembly gate."""

    accumulated_usd: float
    projected_additional_usd: float
    ceiling_usd: float

    @property
    def total_usd(self) -> float:
        return self.accumulated_usd + self.projected_additional_usd

    @property
    def over_ceiling(self) -> bool:
        return self.total_usd > self.ceiling_usd


@dataclass
class CostLedger:
    """Stateful per-run accumulator.

    Not thread-safe — one instance per pipeline run. The orchestrator
    drops the ledger onto the :class:`VesperJob` at run-start.
    """

    ceiling_usd: float = DEFAULT_CEILING_USD
    entries: List[CostEntry] = field(default_factory=list)

    # ─── Recording ─────────────────────────────────────────────────────────

    def record(
        self,
        stage: CostStage,
        amount_usd: float,
        *,
        note: str = "",
    ) -> None:
        """Append a spend entry. ``amount_usd`` may be 0 — recording
        zero-cost stages still gives the daily report visibility."""
        self.entries.append(CostEntry(
            stage=stage, amount_usd=amount_usd, note=note,
        ))

    def record_llm_tokens(
        self,
        stage: CostStage,
        *,
        input_tokens: int,
        output_tokens: int,
        input_price_per_mtok: float,
        output_price_per_mtok: float,
        note: str = "",
    ) -> None:
        """Convenience — cost from token counts + per-model pricing.

        :param input_price_per_mtok: Dollars per million input tokens.
        :param output_price_per_mtok: Dollars per million output tokens.
        """
        cost = (
            (input_tokens / 1_000_000.0) * input_price_per_mtok
            + (output_tokens / 1_000_000.0) * output_price_per_mtok
        )
        self.record(stage, cost, note=note)

    def record_flux_fallback(
        self,
        *,
        per_image_usd: float,
        image_count: int = 1,
        note: str = "",
    ) -> None:
        """Record a fal.ai fallback invocation. Local Flux hits
        :meth:`record_flux_local` (zero-cost) for symmetry."""
        self.record(
            CostStage.FLUX_FALLBACK,
            per_image_usd * image_count,
            note=note,
        )

    def record_flux_local(self, *, image_count: int = 1, note: str = "") -> None:
        self.record(CostStage.FLUX_LOCAL, 0.0, note=f"{image_count} img; {note}")

    # ─── Read / project ────────────────────────────────────────────────────

    def total(self) -> float:
        return sum(e.amount_usd for e in self.entries)

    def total_for(self, stage: CostStage) -> float:
        return sum(e.amount_usd for e in self.entries if e.stage == stage)

    def project(self, additional_usd: float = 0.0) -> CostProjection:
        """Snapshot the ledger for the pre-assembly gate.

        :param additional_usd: Estimated remaining spend — usually the
            projected cost of I2V fallback if it's about to run, or 0
            when the caller is just inspecting where things stand.
        """
        return CostProjection(
            accumulated_usd=self.total(),
            projected_additional_usd=additional_usd,
            ceiling_usd=self.ceiling_usd,
        )

    def should_skip_i2v(self, i2v_projected_usd: float) -> bool:
        """Per plan: if adding I2V would breach the ceiling, skip it
        and fall back to all-parallax instead."""
        return self.project(i2v_projected_usd).over_ceiling

    def should_abort(self) -> bool:
        """Per plan: if accumulated spend alone already breaches the
        ceiling, the run aborts with an alert — don't spend further on
        MoviePy + Postiz."""
        return self.project(0.0).over_ceiling

    # ─── Reporting ─────────────────────────────────────────────────────────

    def breakdown(self) -> dict[str, float]:
        """Dict of stage → total USD for the daily report."""
        out: dict[str, float] = {}
        for e in self.entries:
            out[e.stage.value] = out.get(e.stage.value, 0.0) + e.amount_usd
        return out

    def fallback_invocation_count(self) -> int:
        return sum(1 for e in self.entries if e.stage == CostStage.FLUX_FALLBACK)


__all__ = [
    "CostEntry",
    "CostLedger",
    "CostProjection",
    "CostStage",
    "DEFAULT_CEILING_USD",
]
