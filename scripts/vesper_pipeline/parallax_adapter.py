"""Parallax adapter — DepthAnythingV2 + DepthFlow via ComfyUI.

Mirrors :class:`LocalFluxClient`'s shape: takes a
:class:`ComfyUIClient` + :class:`GpuPlaneMutex`, acquires the server
mutex, submits a workflow that produces a 3-5 s MP4 from a still
input, downloads the output.

The ComfyUI workflow file
(``comfyui_workflows/depth_parallax.json``) is a server-side
deliverable. The adapter loads-by-path and fails cleanly when absent
so the pre-launch runbook catches the gap rather than the pipeline
crashing in production.

Workflow parameters substituted at runtime:
  * ``input_image`` — the still path (as uploaded to ComfyUI server)
  * ``duration_s`` — beat duration from the timeline planner
  * ``motion_mode`` — one of ``push_in_2d``, ``orbit_slight``,
    ``dolly_in_subtle`` (timeline planner emits one of these for
    STILL_PARALLAX beats)
  * ``output_fps`` — 30 by default
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from video_gen.gpu_mutex import (  # noqa: E402
    DEFAULT_ACQUIRE_TIMEOUT_S,
    GpuPlaneMutex,
)

logger = logging.getLogger(__name__)


DEFAULT_WORKFLOW_PATH = "comfyui_workflows/depth_parallax.json"
DEFAULT_OUTPUT_FPS = 30


class ParallaxGenerationError(RuntimeError):
    """Raised on ComfyUI submit / download failure. The pipeline's
    animate_still_beats() catches this and fails the stage; the
    orchestrator then continues with remaining beats or aborts."""


@dataclass
class VesperParallaxAdapter:
    """ComfyUI-backed DepthAnythingV2 + DepthFlow parallax."""

    comfyui_client: Any          # scripts.video_gen.comfyui_client.ComfyUIClient
    mutex: GpuPlaneMutex
    workflow_path: str = DEFAULT_WORKFLOW_PATH
    mutex_timeout_s: float = DEFAULT_ACQUIRE_TIMEOUT_S
    output_fps: int = DEFAULT_OUTPUT_FPS
    _workflow_cache: Optional[dict] = None

    async def animate(
        self,
        still_path: str,
        output_path: str,
        *,
        duration_s: float,
        motion_mode: str = "push_in_2d",
    ) -> str:
        """Animate ``still_path`` into a parallax MP4 at ``output_path``.

        The orchestrator's `_ParallaxBackend` Protocol calls with
        ``(still_path, output_path, duration_s=)``; we accept the extra
        ``motion_mode`` kwarg with a sensible default so the existing
        Protocol contract is still met.

        Raises:
          * :class:`GpuMutexAcquireTimeout` — caller degrades the beat
            to a static Ken Burns image per plan Unit 10 contingency.
          * :class:`ParallaxGenerationError` — ComfyUI submit/download
            failed; same degradation applies.
        """
        if not still_path:
            raise ParallaxGenerationError(
                "animate() called with empty still_path"
            )
        if not os.path.exists(still_path):
            raise ParallaxGenerationError(
                f"input still not found: {still_path}"
            )

        workflow = self._load_workflow()
        params = {
            "input_image": still_path,
            "duration_s": round(duration_s, 2),
            "motion_mode": motion_mode,
            "output_fps": self.output_fps,
            "seed": int(time.time_ns() % (2 ** 31)),
        }

        t0 = time.monotonic()
        with self.mutex.lock(
            caller="vesper.parallax",
            timeout_s=self.mutex_timeout_s,
        ):
            # GpuMutexAcquireTimeout bubbles up before this body runs.
            try:
                prompt_id = await self.comfyui_client.run_workflow(
                    workflow, params=params, wait_for_completion=True,
                )
            except Exception as exc:
                raise ParallaxGenerationError(
                    f"ComfyUI parallax submit/run failed: {exc}"
                ) from exc

            try:
                files = await self.comfyui_client.download_output(
                    prompt_id,
                    output_dir=os.path.dirname(output_path) or ".",
                    output_filename=os.path.basename(output_path),
                )
            except Exception as exc:
                raise ParallaxGenerationError(
                    f"parallax output download failed: {exc}"
                ) from exc

        if not files:
            raise ParallaxGenerationError(
                f"ComfyUI parallax produced no output files for "
                f"prompt_id={prompt_id}"
            )

        dur_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "VesperParallaxAdapter: %s → %s (%.0f ms, motion=%s)",
            still_path, files[0], dur_ms, motion_mode,
        )
        return files[0]

    def _load_workflow(self) -> dict:
        if self._workflow_cache is not None:
            return self._workflow_cache
        try:
            with open(self.workflow_path, "r", encoding="utf-8") as f:
                self._workflow_cache = json.load(f)
        except FileNotFoundError as exc:
            raise ParallaxGenerationError(
                f"Parallax workflow JSON not found at {self.workflow_path}. "
                "This file is a server-side deliverable; see "
                "docs/runbooks/vesper/vesper-launch-runbook.md"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ParallaxGenerationError(
                f"Parallax workflow JSON malformed: {exc}"
            ) from exc
        return self._workflow_cache


__all__ = [
    "ParallaxGenerationError",
    "VesperParallaxAdapter",
]
