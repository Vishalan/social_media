"""fal.ai Flux text-to-image client.

Stateless HTTP client matching the pattern in
``scripts/avatar_gen/veed_client.py``: async queue submit → poll →
fetch result → download. Two differences from the avatar clients:

1. Flux returns ``images[0].url`` rather than ``video.url``.
2. No audio_url / image_url inputs — it's pure text-to-image.

The Flux variant (schnell / dev / pro-v1.1) is selected at construction
time. Unit 9 implementation benchmarks the three during pre-launch and
locks the per-beat-class choice in ``channels/vesper.py::VISUAL`` —
for now the client accepts any endpoint string, so callers pin via config.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class FluxGenerationError(RuntimeError):
    """Raised on fal.ai submission / poll / download failure."""


_POLL_INTERVAL_S = 4.0       # Flux is faster than video; poll more often
_TIMEOUT_S = 5 * 60          # 5-minute hard ceiling per still


@dataclass(frozen=True)
class FluxResult:
    local_path: str
    remote_url: str
    width: int
    height: int
    duration_ms: float


class FalFluxClient:
    """fal.ai Flux text-to-image client.

    Endpoint is passed as a string so callers can pin a specific variant
    (``"fal-ai/flux/schnell"`` cheapest, ``"fal-ai/flux-pro/v1.1"`` best
    quality). Image size, inference steps, and guidance scale are also
    caller-supplied so the Vesper visual_style config (Unit 5) drives
    the exact generation knobs.
    """

    def __init__(
        self,
        fal_api_key: str,
        endpoint: str = "fal-ai/flux/dev",
        *,
        output_dir: str = "output/still",
        default_image_size: str = "portrait_16_9",
        default_num_inference_steps: int = 28,
        default_guidance_scale: float = 3.5,
        default_negative_prompt: str = (
            "text, watermark, logo, signature, caption, subtitle, "
            "oversaturated, cartoon, anime, low quality"
        ),
    ) -> None:
        if not fal_api_key:
            raise ValueError("FalFluxClient requires a fal_api_key")
        self._fal_api_key = fal_api_key
        self._endpoint = endpoint.strip("/")
        self._output_dir = output_dir
        self._default_image_size = default_image_size
        self._default_steps = default_num_inference_steps
        self._default_guidance = default_guidance_scale
        self._default_negative = default_negative_prompt
        os.makedirs(output_dir, exist_ok=True)

    # ─── Public interface ──────────────────────────────────────────────────

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

        Raises :class:`FluxGenerationError` on failure.
        """
        t0 = time.monotonic()
        request_id, status_url = await self._submit(
            prompt=prompt,
            image_size=image_size or self._default_image_size,
            num_inference_steps=num_inference_steps or self._default_steps,
            guidance_scale=guidance_scale or self._default_guidance,
            seed=seed,
            negative_prompt=negative_prompt or self._default_negative,
        )
        logger.info("Flux: request_id=%s — polling", request_id)
        url, width, height = await self._poll_until_complete(request_id, status_url)
        await self._download(url, output_path)
        dur_ms = (time.monotonic() - t0) * 1000
        logger.info(
            "Flux: generated %dx%d to %s in %.0f ms",
            width, height, output_path, dur_ms,
        )
        return FluxResult(
            local_path=output_path,
            remote_url=url,
            width=width,
            height=height,
            duration_ms=dur_ms,
        )

    # ─── Private HTTP plumbing ─────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Key {self._fal_api_key}",
            "Content-Type": "application/json",
        }

    def _submit_url(self) -> str:
        return f"https://queue.fal.run/{self._endpoint}"

    async def _submit(
        self,
        *,
        prompt: str,
        image_size: str,
        num_inference_steps: int,
        guidance_scale: float,
        seed: Optional[int],
        negative_prompt: str,
    ) -> tuple[str, str]:
        body: dict = {
            "prompt": prompt,
            "image_size": image_size,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "negative_prompt": negative_prompt,
            "num_images": 1,
            "enable_safety_checker": True,
        }
        if seed is not None:
            body["seed"] = seed

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self._submit_url(), json=body, headers=self._headers()
            )
            if resp.status_code not in (200, 201):
                raise FluxGenerationError(
                    f"Flux submission failed: HTTP {resp.status_code} — {resp.text[:500]}"
                )
            data = resp.json()
            request_id = data.get("request_id")
            status_url = data.get("status_url") or data.get("response_url")
            if not request_id:
                raise FluxGenerationError(
                    f"Flux response missing request_id: {data!r}"
                )
            if not status_url:
                status_url = (
                    f"https://queue.fal.run/{self._endpoint}"
                    f"/requests/{request_id}/status"
                )
            return request_id, status_url

    async def _poll_until_complete(
        self, request_id: str, status_url: str
    ) -> tuple[str, int, int]:
        """Poll until COMPLETED; return ``(image_url, width, height)``."""
        deadline = time.monotonic() + _TIMEOUT_S
        async with httpx.AsyncClient(timeout=15) as client:
            while time.monotonic() < deadline:
                resp = await client.get(status_url, headers=self._headers())
                if resp.status_code not in (200, 202):
                    raise FluxGenerationError(
                        f"Flux status check failed: HTTP {resp.status_code} — {resp.text[:300]}"
                    )
                data = resp.json()
                status = data.get("status", "")
                if status == "COMPLETED":
                    url_wh = self._extract_image_url(data)
                    if url_wh is None:
                        # Flat status responses sometimes carry only queue
                        # metadata; fetch the response body explicitly.
                        response_url = data.get("response_url")
                        if response_url:
                            r2 = await client.get(response_url, headers=self._headers())
                            url_wh = self._extract_image_url(r2.json())
                    if url_wh is None:
                        raise FluxGenerationError(
                            f"Flux completed but no image URL in response: {data!r}"
                        )
                    return url_wh
                if status == "FAILED":
                    err = data.get("error") or data.get("detail", "unknown")
                    raise FluxGenerationError(
                        f"Flux generation failed (request_id={request_id}): {err}"
                    )
                await asyncio.sleep(_POLL_INTERVAL_S)
        raise FluxGenerationError(
            f"Flux generation timed out after {_TIMEOUT_S // 60} min "
            f"(request_id={request_id})"
        )

    @staticmethod
    def _extract_image_url(data: dict) -> Optional[tuple[str, int, int]]:
        """Pull the first image URL + dimensions out of a fal.ai response."""
        payload = data.get("output") or data.get("result") or data
        images = payload.get("images") or []
        if not images:
            # Some variants use a flat ``image`` object.
            single = payload.get("image")
            if isinstance(single, dict) and single.get("url"):
                return (
                    single["url"],
                    int(single.get("width") or 0),
                    int(single.get("height") or 0),
                )
            return None
        first = images[0]
        if not isinstance(first, dict) or not first.get("url"):
            return None
        return (
            first["url"],
            int(first.get("width") or 0),
            int(first.get("height") or 0),
        )

    async def _download(self, url: str, output_path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(output_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)


__all__ = ["FalFluxClient", "FluxGenerationError", "FluxResult"]
