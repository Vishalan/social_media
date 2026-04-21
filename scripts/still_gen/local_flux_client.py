"""Local Flux still generator — primary path per plan Key Decision #7.

Runs Flux on the server 3090 via the existing ComfyUI sidecar. Same
``generate(prompt, output_path, **opts) -> FluxResult`` contract as
:class:`scripts.still_gen.flux_client.FalFluxClient` so the router
(``flux_router.py``) can swap backends without branching logic at the
call site.

Two dependencies injected at construction:
  * a :class:`ComfyUIClient` (from ``scripts.video_gen.comfyui_client``)
    pointed at the server's ComfyUI endpoint
  * a :class:`GpuPlaneMutex` (from ``scripts.video_gen.gpu_mutex``)
    wrapping the server's Redis — acquired before every submit so we
    don't collide with chatterbox / parallax / I2V on the same GPU

The ComfyUI workflow file itself (``comfyui_workflows/flux_still.json``)
is a *hardware-side* deliverable — it has to be built once the 3090's
ComfyUI is up with Flux nodes + checkpoints installed. This module
loads it by path at generate-time; the tests stub the workflow.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from still_gen.flux_client import FluxGenerationError, FluxResult  # noqa: E402
from video_gen.gpu_mutex import (  # noqa: E402
    DEFAULT_ACQUIRE_TIMEOUT_S,
    GpuMutexAcquireTimeout,
    GpuPlaneMutex,
)

logger = logging.getLogger(__name__)


# Workflow placeholder names — the ComfyUI JSON uses `{{...}}` tokens
# that `ComfyUIClient._substitute_params` fills in.
_PH_PROMPT = "prompt"
_PH_NEGATIVE = "negative_prompt"
_PH_STEPS = "num_inference_steps"
_PH_GUIDANCE = "guidance_scale"
_PH_SEED = "seed"
_PH_WIDTH = "width"
_PH_HEIGHT = "height"


# fal.ai-style string → (width, height). The ComfyUI Flux workflow
# takes explicit W/H nodes so we pre-resolve here.
_IMAGE_SIZE_MAP: dict[str, tuple[int, int]] = {
    "portrait_16_9": (768, 1344),   # 9:16 shorts
    "portrait_4_3": (960, 1280),
    "square_hd": (1024, 1024),
    "landscape_16_9": (1344, 768),
    "landscape_4_3": (1280, 960),
}


class LocalFluxClient:
    """Local Flux generator via ComfyUI on the server 3090."""

    def __init__(
        self,
        comfyui_client,  # scripts.video_gen.comfyui_client.ComfyUIClient
        mutex: GpuPlaneMutex,
        *,
        workflow_path: str = "comfyui_workflows/flux_still.json",
        output_dir: str = "output/still",
        default_image_size: str = "portrait_16_9",
        default_num_inference_steps: int = 28,
        default_guidance_scale: float = 3.5,
        default_negative_prompt: str = (
            "text, watermark, logo, signature, caption, subtitle, "
            "oversaturated, cartoon, anime, low quality"
        ),
        mutex_timeout_s: float = DEFAULT_ACQUIRE_TIMEOUT_S,
    ) -> None:
        self._comfy = comfyui_client
        self._mutex = mutex
        self._workflow_path = workflow_path
        self._output_dir = output_dir
        self._default_image_size = default_image_size
        self._default_steps = default_num_inference_steps
        self._default_guidance = default_guidance_scale
        self._default_negative = default_negative_prompt
        self._mutex_timeout_s = mutex_timeout_s
        os.makedirs(output_dir, exist_ok=True)
        self._workflow_cache: Optional[dict] = None  # lazy-load once

    # ─── Public interface (mirrors FalFluxClient.generate) ─────────────────

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
        """Generate one still from ``prompt`` and save to ``output_path``.

        Acquires the server-side GPU mutex before submitting. On mutex
        timeout, raises :class:`GpuMutexAcquireTimeout` so the router can
        route to fal.ai. On ComfyUI failure, raises
        :class:`FluxGenerationError`.
        """
        size_name = image_size or self._default_image_size
        width, height = _resolve_size(size_name)
        steps = num_inference_steps or self._default_steps
        guidance = guidance_scale or self._default_guidance
        negative = negative_prompt or self._default_negative
        seed_val = seed if seed is not None else int(time.time_ns() % (2 ** 31))

        workflow = self._load_workflow()
        params = {
            _PH_PROMPT: prompt,
            _PH_NEGATIVE: negative,
            _PH_STEPS: steps,
            _PH_GUIDANCE: guidance,
            _PH_SEED: seed_val,
            _PH_WIDTH: width,
            _PH_HEIGHT: height,
        }

        t0 = time.monotonic()
        with self._mutex.lock(
            caller="vesper.flux.local",
            timeout_s=self._mutex_timeout_s,
        ):
            # GpuMutexAcquireTimeout bubbles out before this point; the
            # router catches it and falls back.
            try:
                prompt_id = await self._comfy.run_workflow(
                    workflow, params=params, wait_for_completion=True
                )
            except Exception as exc:
                raise FluxGenerationError(
                    f"Local Flux ComfyUI submit/run failed: {exc}"
                ) from exc

            try:
                files = await self._comfy.download_output(
                    prompt_id,
                    output_dir=os.path.dirname(output_path) or ".",
                    output_filename=os.path.basename(output_path),
                )
            except Exception as exc:
                raise FluxGenerationError(
                    f"Local Flux output download failed: {exc}"
                ) from exc

        if not files:
            raise FluxGenerationError(
                f"Local Flux produced no output files for prompt_id={prompt_id}"
            )

        local_path = files[0]
        dur_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "LocalFlux: generated %dx%d to %s in %.0f ms",
            width, height, local_path, dur_ms,
        )
        return FluxResult(
            local_path=local_path,
            remote_url=f"comfyui://{prompt_id}",  # no public URL; stable-ish handle
            width=width,
            height=height,
            duration_ms=dur_ms,
        )

    # ─── Helpers ───────────────────────────────────────────────────────────

    def _load_workflow(self) -> dict:
        if self._workflow_cache is not None:
            return self._workflow_cache
        try:
            with open(self._workflow_path, "r", encoding="utf-8") as f:
                self._workflow_cache = json.load(f)
        except FileNotFoundError as exc:
            raise FluxGenerationError(
                f"Local Flux workflow JSON not found at {self._workflow_path}. "
                "This file is a server-side deliverable; until it exists, "
                "flux_router falls back to fal.ai."
            ) from exc
        except json.JSONDecodeError as exc:
            raise FluxGenerationError(
                f"Local Flux workflow JSON malformed: {exc}"
            ) from exc
        return self._workflow_cache


def _resolve_size(size_name: str) -> tuple[int, int]:
    """Translate a fal.ai-style size string into explicit (W, H).

    Unknown names default to 9:16 shorts dimensions so Vesper's primary
    output aspect is preserved on config typos."""
    return _IMAGE_SIZE_MAP.get(size_name, _IMAGE_SIZE_MAP["portrait_16_9"])


__all__ = ["LocalFluxClient"]
