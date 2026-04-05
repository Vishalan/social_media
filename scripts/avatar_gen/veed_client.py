"""
VEED Fabric 1.0 avatar backend via fal.ai queue API.

Sends a portrait photo + audio URL to the fal.ai async queue and
downloads the resulting 9:16 MP4.

Required config keys:
    fal_api_key           — fal.ai API key (Authorization: Key header)
    veed_avatar_image_url — Public URL of the avatar portrait photo
    output_dir            — (optional) local directory for downloads; default "output/avatar"
    veed_resolution       — (optional) "480p" or "720p"; default "480p"

Notes:
    - Uses fal.ai async queue: POST returns request_id + status_url;
      poll status_url every 10 s; 15-minute timeout.
    - Native 9:16 output — no FFmpeg crop needed in VideoEditor.
    - Pricing: $0.08/s at 480p, $0.15/s at 720p (vs Kling $0.115/s).
"""

import asyncio
import logging
import os
import time
from typing import Optional

import httpx

from .base import AvatarClient, AvatarQualityError

logger = logging.getLogger(__name__)

_FAL_SUBMIT_URL = "https://queue.fal.run/veed/fabric-1.0"

_POLL_INTERVAL_S = 10
_TIMEOUT_S = 15 * 60  # 15 minutes


class VeedFabricClient(AvatarClient):
    """
    Avatar generation backend using VEED Fabric 1.0 via fal.ai.

    ~30% cheaper than Kling v2 Pro at 480p ($0.08/s vs $0.115/s).
    Same fal.ai async queue pattern as KlingAvatarClient.

    Example::

        client = VeedFabricClient(
            fal_api_key=os.environ["FAL_API_KEY"],
            avatar_image_url=os.environ["VEED_AVATAR_IMAGE_URL"],
        )
        path = await client.generate(audio_url, "output/avatar/clip.mp4")
    """

    def __init__(
        self,
        fal_api_key: str,
        avatar_image_url: str,
        resolution: str = "480p",
        output_dir: str = "output/avatar",
    ) -> None:
        self._fal_api_key = fal_api_key
        self._avatar_image_url = avatar_image_url
        self._resolution = resolution
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ─── Provider properties ───────────────────────────────────────────────

    @property
    def needs_portrait_crop(self) -> bool:
        """VEED Fabric outputs 9:16 natively — no crop needed."""
        return False

    @property
    def max_duration_s(self) -> Optional[float]:
        """VEED Fabric has no hard per-call duration cap."""
        return None

    # ─── Public interface ──────────────────────────────────────────────────

    async def generate(self, audio_url: str, output_path: str) -> str:
        """
        Generate a 9:16 avatar video lip-synced to the given audio URL.

        Args:
            audio_url: Publicly accessible URL of the ElevenLabs audio file.
            output_path: Local file path where the generated MP4 will be saved.

        Returns:
            output_path on success.

        Raises:
            AvatarQualityError: On fal.ai error, timeout, or empty output file.
        """
        logger.info("VEED Fabric: submitting avatar generation request")
        request_id, status_url = await self._submit(audio_url)
        logger.info("VEED Fabric: request_id=%s — polling for completion", request_id)
        video_url = await self._poll_until_complete(request_id, status_url)
        logger.info("VEED Fabric: video ready at %s — downloading", video_url)
        await self._download(video_url, output_path)
        self._validate(output_path)
        logger.info("VEED Fabric: avatar saved to %s", output_path)
        return output_path

    # ─── Private ──────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "Authorization": f"Key {self._fal_api_key}",
            "Content-Type": "application/json",
        }

    async def _submit(self, audio_url: str) -> tuple[str, str]:
        """POST to fal.ai queue and return (request_id, status_url)."""
        body = {
            "image_url": self._avatar_image_url,
            "audio_url": audio_url,
            "resolution": self._resolution,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _FAL_SUBMIT_URL,
                json=body,
                headers=self._headers(),
            )
            if resp.status_code not in (200, 201):
                raise AvatarQualityError(
                    f"VEED/fal.ai submission failed: HTTP {resp.status_code} — {resp.text}"
                )

            data = resp.json()
            request_id: Optional[str] = data.get("request_id")
            status_url: Optional[str] = data.get("status_url") or data.get("response_url")

            if not request_id:
                raise AvatarQualityError(
                    f"VEED/fal.ai response missing request_id: {data}"
                )
            if not status_url:
                status_url = (
                    f"https://queue.fal.run/veed/fabric-1.0"
                    f"/requests/{request_id}/status"
                )

            return request_id, status_url

    async def _poll_until_complete(self, request_id: str, status_url: str) -> str:
        """Poll fal.ai status URL until COMPLETED or timeout."""
        deadline = time.monotonic() + _TIMEOUT_S
        async with httpx.AsyncClient(timeout=15) as client:
            while time.monotonic() < deadline:
                resp = await client.get(status_url, headers=self._headers())
                # 200 = terminal (COMPLETED/FAILED), 202 = IN_PROGRESS (still running)
                if resp.status_code not in (200, 202):
                    raise AvatarQualityError(
                        f"VEED/fal.ai status check failed: HTTP {resp.status_code} — {resp.text}"
                    )

                data = resp.json()
                status: str = data.get("status", "")
                logger.debug("VEED Fabric: request_id=%s status=%s", request_id, status)

                if status == "COMPLETED":
                    # Status endpoint only has queue metadata; the actual output
                    # (video URL) lives at response_url — fetch it explicitly.
                    video_url = self._extract_video_url(data)
                    if not video_url:
                        response_url = data.get("response_url")
                        if response_url:
                            result_resp = await client.get(response_url, headers=self._headers())
                            video_url = self._extract_video_url(result_resp.json())
                    if not video_url:
                        raise AvatarQualityError(
                            f"VEED/fal.ai completed but video URL missing: {data}"
                        )
                    return video_url

                if status == "FAILED":
                    error_msg = data.get("error") or data.get("detail", "unknown error")
                    raise AvatarQualityError(
                        f"VEED/fal.ai generation failed (request_id={request_id}): {error_msg}"
                    )

                await asyncio.sleep(_POLL_INTERVAL_S)

        raise AvatarQualityError(
            f"VEED/fal.ai generation timed out after {_TIMEOUT_S // 60} minutes "
            f"(request_id={request_id})."
        )

    @staticmethod
    def _extract_video_url(data: dict) -> Optional[str]:
        """
        Extract the video URL from a fal.ai COMPLETED response.

        Tries common fal.ai result shapes:
          {"video": {"url": "..."}}
          {"output": {"video": {"url": "..."}}}
          {"result": {"video": {"url": "..."}}}
          {"url": "..."}  (flat shape some endpoints use)
        """
        # Try nested output/result wrappers first, then flat
        payload = data.get("output") or data.get("result") or data
        video = payload.get("video")
        if isinstance(video, dict):
            return video.get("url")
        if isinstance(video, str):
            return video
        # Some endpoints return a top-level "url" key
        return payload.get("url")

    async def _download(self, video_url: str, output_path: str) -> None:
        """Stream download of the completed video to output_path."""
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
            async with client.stream("GET", video_url) as resp:
                resp.raise_for_status()
                with open(output_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)

    def _validate(self, output_path: str) -> None:
        """Raise AvatarQualityError if the downloaded file is empty."""
        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            raise AvatarQualityError(
                f"VEED Fabric: downloaded file is empty or missing: {output_path}"
            )
