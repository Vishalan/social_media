"""Flux dispatcher — local 3090 primary, fal.ai fallback.

Orchestrator code (``scripts/vesper_pipeline.py``) calls this single
``generate()`` entry point rather than branching between local and
remote. The router picks a backend per call:

  1. Try :class:`LocalFluxClient` first.
  2. On :class:`GpuMutexAcquireTimeout` (server-side GPU saturated)
     or :class:`FluxGenerationError` (ComfyUI error / workflow missing),
     fall back to :class:`FalFluxClient`.
  3. If the fal.ai fallback also fails (or isn't configured), surface
     the original failure so the pipeline can log + degrade the beat.

Telemetry: every call increments counters the caller can snapshot for
the daily report. Sustained fallback-invocation >10% signals chronic
local-GPU contention — per plan Risks, Unit 11/13 revisit the queue
model if we see that in production.

The router is stateful only in the sense that it holds counters. It's
cheap to instantiate per-pipeline-run.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from still_gen.flux_client import FluxGenerationError, FluxResult  # noqa: E402
from video_gen.gpu_mutex import GpuMutexAcquireTimeout  # noqa: E402

logger = logging.getLogger(__name__)


class FluxBackend(Protocol):
    """Duck-typed interface both LocalFluxClient and FalFluxClient satisfy."""

    async def generate(
        self,
        prompt: str,
        output_path: str,
        *,
        image_size: Optional[str] = None,
        num_inference_steps: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        seed: Optional[int] = None,
        negative_prompt: Optional[str] = None,
    ) -> FluxResult: ...


@dataclass
class FluxRouterTelemetry:
    """Per-run counters. Snapshotted by the orchestrator for the daily
    report; not persisted by the router itself."""

    calls: int = 0
    local_success: int = 0
    fallback_invocations: int = 0
    fallback_success: int = 0
    total_failures: int = 0
    failure_reasons: list[str] = field(default_factory=list)

    def fallback_rate(self) -> float:
        return self.fallback_invocations / self.calls if self.calls else 0.0


class FluxRouter:
    """Dispatcher: try local first, fall back to fal.ai on mutex
    timeout or ComfyUI error."""

    def __init__(
        self,
        local: FluxBackend,
        *,
        fallback: Optional[FluxBackend] = None,
    ) -> None:
        self._local = local
        self._fallback = fallback
        self.telemetry = FluxRouterTelemetry()

    async def generate(
        self,
        prompt: str,
        output_path: str,
        *,
        image_size: Optional[str] = None,
        num_inference_steps: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        seed: Optional[int] = None,
        negative_prompt: Optional[str] = None,
    ) -> FluxResult:
        self.telemetry.calls += 1
        opts = dict(
            image_size=image_size,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            seed=seed,
            negative_prompt=negative_prompt,
        )

        # ── Attempt 1: local 3090 ──────────────────────────────────────────
        try:
            result = await self._local.generate(prompt, output_path, **opts)
            self.telemetry.local_success += 1
            return result
        except GpuMutexAcquireTimeout as exc:
            local_failure = f"mutex_timeout: {exc}"
            logger.warning("Flux local → fal.ai fallback (mutex timeout): %s", exc)
        except FluxGenerationError as exc:
            local_failure = f"comfyui_error: {exc}"
            logger.warning("Flux local → fal.ai fallback (ComfyUI error): %s", exc)
        except Exception as exc:  # pragma: no cover — unexpected local failure
            local_failure = f"unexpected: {exc}"
            logger.exception("Flux local → fal.ai fallback (unexpected)")

        # ── Attempt 2: fal.ai fallback ─────────────────────────────────────
        self.telemetry.fallback_invocations += 1
        if self._fallback is None:
            self.telemetry.total_failures += 1
            self.telemetry.failure_reasons.append(
                f"{local_failure}; no fallback configured"
            )
            raise FluxGenerationError(
                f"Local Flux failed ({local_failure}) and no fal.ai "
                "fallback configured. Configure FAL_API_KEY or ensure "
                "the local ComfyUI workflow is reachable."
            )

        try:
            result = await self._fallback.generate(prompt, output_path, **opts)
            self.telemetry.fallback_success += 1
            return result
        except Exception as fb_exc:
            self.telemetry.total_failures += 1
            reason = f"{local_failure}; fallback: {fb_exc}"
            self.telemetry.failure_reasons.append(reason)
            raise FluxGenerationError(
                f"Both Flux paths failed. Local={local_failure}. "
                f"Fallback={fb_exc}"
            ) from fb_exc


__all__ = ["FluxBackend", "FluxRouter", "FluxRouterTelemetry"]
