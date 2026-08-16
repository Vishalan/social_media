"""LatentSync avatar backend — local lip-sync over the owner's real footage.

Replaces the metered VEED/fal.ai path. Measured on the RTX 3090, 2026-08-16:
5 s of 480x854 @25fps in 105 s warm, peak 16.6 GB VRAM inside the job
subprocess. That is ~21 s of compute per second of video, so a 60 s short is
roughly 21 minutes — against $4.80-9.00 per short on VEED.

What makes this backend different from the hosted ones
------------------------------------------------------
It lip-syncs over EXISTING footage rather than generating a person from a
still. The head motion, blinks, gestures and framing all come from the driving
clip; only the mouth region is regenerated. Consequences the caller must know:

* Identity cannot drift, because identity was never generated.
* Gestures are a filming decision, not a model capability.
* A driving clip is REQUIRED, and its duration must match the audio.

Talks to the ``commoncreed_latentsync`` service over HTTP, mirroring how the
pipeline already talks to Chatterbox. The service runs each job in a
subprocess so VRAM is fully released between calls.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

import httpx

from .base import AvatarClient, AvatarQualityError

logger = logging.getLogger(__name__)

_DEFAULT_ENDPOINT = "http://commoncreed_latentsync:7778"

# A 60s short is ~21 min warm; a cold first call also pays the ~5 GB weight
# download. 90 minutes gives room for both without masking a genuine hang.
_DEFAULT_TIMEOUT_S = 5400.0


class LatentSyncClient(AvatarClient):
    """Local avatar generation via the LatentSync sidecar service."""

    def __init__(
        self,
        endpoint: str = _DEFAULT_ENDPOINT,
        *,
        default_clip: str = "clip_07.mp4",
        inference_steps: int = 20,
        guidance_scale: float = 1.5,
        seed: int = 1247,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._default_clip = default_clip
        self._steps = inference_steps
        self._guidance = guidance_scale
        self._seed = seed
        self._timeout = timeout_s

    # --- capability flags -------------------------------------------------
    @property
    def needs_portrait_crop(self) -> bool:
        # Output inherits the driving clip's geometry. The gesture library is
        # cut to 480x854, already portrait, so no crop is needed.
        return False

    @property
    def max_duration_s(self) -> Optional[float]:
        # No hard cap in the model. The practical ceiling is the driving
        # footage: the library holds 59.25 s of usable frontal material, so a
        # longer render needs a longer clip, not a different call.
        return None

    @property
    def accepts_local_audio(self) -> bool:
        return True

    @property
    def needs_driving_video(self) -> bool:
        return True

    # --- hosted-style entry point (unsupported) ---------------------------
    async def generate(self, audio_url: str, output_path: str) -> str:
        raise NotImplementedError(
            "LatentSyncClient runs locally and takes a file path, not a public "
            "URL. Call generate_local(audio_path, output_path, driving_video=...) "
            "instead — check `accepts_local_audio` first."
        )

    # --- local entry point ------------------------------------------------
    async def generate_local(
        self,
        audio_path: str,
        output_path: str,
        *,
        driving_video: Optional[str] = None,
    ) -> str:
        clip = driving_video or self._default_clip
        payload: dict[str, Any] = {
            "audio_path": audio_path,
            "output_filename": Path(output_path).name,
            "inference_steps": self._steps,
            "guidance_scale": self._guidance,
            "seed": self._seed,
        }
        # A bare filename means "from the gesture library"; anything with a
        # separator is an explicit path the service can already see.
        if "/" in clip or "\\" in clip:
            payload["video_path"] = clip
        else:
            payload["clip"] = clip

        logger.info(
            "LatentSync: clip=%s audio=%s steps=%d",
            clip, Path(audio_path).name, self._steps,
        )

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(f"{self._endpoint}/lipsync", json=payload)
        except httpx.TimeoutException as exc:
            raise AvatarQualityError(
                f"LatentSync timed out after {self._timeout:.0f}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise AvatarQualityError(f"LatentSync unreachable: {exc}") from exc

        if resp.status_code != 200:
            detail = _detail(resp)
            raise AvatarQualityError(
                f"LatentSync returned {resp.status_code}: {detail}"
            )

        data = resp.json()
        produced = data.get("output_path")
        if not produced:
            raise AvatarQualityError("LatentSync response had no output_path")

        duration = float(data.get("video_duration_s") or 0.0)
        if duration <= 0.0:
            raise AvatarQualityError(
                f"LatentSync produced an unreadable or empty video: {produced}"
            )

        logger.info(
            "LatentSync OK — %s (%.2fs video, %.1fs generation)",
            produced, duration, float(data.get("generation_ms", 0)) / 1000.0,
        )
        return produced

    async def list_clips(self) -> dict:
        """Return the gesture-clip library and its motion manifest."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{self._endpoint}/clips/list")
            resp.raise_for_status()
            return resp.json()

    async def transcribe(self, audio_path: str, model: str = "large-v3") -> dict:
        """Word-level transcription on the GPU.

        Lives here because the LatentSync service is the only component with a
        GPU — the sidecar that runs the pipeline has none, which is why the
        pipeline's own transcription is pinned to base/cpu/int8.
        """
        async with httpx.AsyncClient(timeout=1800.0) as client:
            resp = await client.post(
                f"{self._endpoint}/transcribe",
                json={"audio_path": audio_path, "model": model},
            )
            if resp.status_code != 200:
                raise RuntimeError(f"transcribe failed: {_detail(resp)}")
            return resp.json()


def _detail(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("detail", resp.text))[:500]
    except (json.JSONDecodeError, ValueError):
        return resp.text[:500]
