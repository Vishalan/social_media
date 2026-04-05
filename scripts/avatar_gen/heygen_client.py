"""
HeyGen Avatar IV backend for avatar video generation.

Sends audio to HeyGen's REST API and downloads the resulting MP4.

Required config keys:
    heygen_api_key   — HeyGen API key (X-Api-Key header)
    heygen_avatar_id — Avatar ID obtained from setup_heygen_avatar.py
    output_dir       — (optional) local directory for downloads; default "output/avatar"

Notes:
    - Tries /v2/video/av4/generate first (dedicated Avatar IV endpoint).
      Falls back to /v2/video/generate with use_avatar_iv_model=true on 404.
    - Generates at 1920x1080 (landscape). VideoEditor crops to 9:16 via FFmpeg.
    - Polls /v1/video_status.get every 10 s; raises AvatarQualityError after
      20 minutes (requires HeyGen Pro plan for priority queue).
"""

import asyncio
import logging
import os
import time
from typing import Optional

import httpx

from .base import AvatarClient, AvatarQualityError

logger = logging.getLogger(__name__)

_HEYGEN_BASE = "https://api.heygen.com"
_AV4_GENERATE_URL = f"{_HEYGEN_BASE}/v2/video/av4/generate"
_V2_GENERATE_URL = f"{_HEYGEN_BASE}/v2/video/generate"
_STATUS_URL = f"{_HEYGEN_BASE}/v1/video_status.get"

_POLL_INTERVAL_S = 10
_TIMEOUT_S = 20 * 60  # 20 minutes


class HeyGenAvatarClient(AvatarClient):
    """
    Avatar generation backend using HeyGen Avatar IV.

    Example::

        client = HeyGenAvatarClient(
            api_key=os.environ["HEYGEN_API_KEY"],
            avatar_id=os.environ["HEYGEN_AVATAR_ID"],
        )
        path = await client.generate(audio_url, "output/avatar/clip.mp4")
    """

    def __init__(
        self,
        api_key: str,
        avatar_id: str,
        output_dir: str = "output/avatar",
    ) -> None:
        self._api_key = api_key
        self._avatar_id = avatar_id
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ─── Provider properties ───────────────────────────────────────────────

    @property
    def needs_portrait_crop(self) -> bool:
        """HeyGen generates 1920×1080 landscape — VideoEditor must crop to 9:16."""
        return True

    @property
    def max_duration_s(self):
        """HeyGen has no hard per-call duration cap."""
        return None

    # ─── Public interface ──────────────────────────────────────────────────

    async def generate(self, audio_url: str, output_path: str) -> str:
        """
        Generate an avatar video lip-synced to the given audio URL.

        Args:
            audio_url: Publicly accessible URL of the ElevenLabs audio file.
            output_path: Local file path where the generated MP4 will be saved.

        Returns:
            output_path on success.

        Raises:
            AvatarQualityError: On HeyGen error, timeout, or empty output file.
        """
        logger.info("HeyGen: starting avatar generation (avatar_id=%s)", self._avatar_id)
        video_id = await self._submit(audio_url)
        logger.info("HeyGen: video_id=%s — polling for completion", video_id)
        video_url = await self._poll_until_complete(video_id)
        logger.info("HeyGen: video ready at %s — downloading", video_url)
        await self._download(video_url, output_path)
        self._validate(output_path)
        logger.info("HeyGen: avatar saved to %s", output_path)
        return output_path

    # ─── Private ──────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            "X-Api-Key": self._api_key,
            "Content-Type": "application/json",
        }

    def _build_body(self, audio_url: str) -> dict:
        return {
            "avatar_id": self._avatar_id,
            "voice": {
                "type": "audio",
                "audio_url": audio_url,
            },
            "dimension": {
                "width": 1920,
                "height": 1080,
            },
        }

    async def _submit(self, audio_url: str) -> str:
        """POST to av4 endpoint; fall back to v2/generate on 404."""
        body = self._build_body(audio_url)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _AV4_GENERATE_URL,
                json=body,
                headers=self._headers(),
            )
            if resp.status_code == 404:
                logger.debug(
                    "HeyGen: av4 endpoint returned 404 — falling back to v2/video/generate"
                )
                body["use_avatar_iv_model"] = True
                resp = await client.post(
                    _V2_GENERATE_URL,
                    json=body,
                    headers=self._headers(),
                )

            if resp.status_code not in (200, 201):
                raise AvatarQualityError(
                    f"HeyGen generation request failed: HTTP {resp.status_code} — {resp.text}"
                )

            data = resp.json()
            video_id: Optional[str] = (
                data.get("data", {}).get("video_id")
                or data.get("video_id")
            )
            if not video_id:
                raise AvatarQualityError(
                    f"HeyGen response missing video_id: {data}"
                )
            return video_id

    async def _poll_until_complete(self, video_id: str) -> str:
        """Poll HeyGen status endpoint until completed or timeout."""
        deadline = time.monotonic() + _TIMEOUT_S
        async with httpx.AsyncClient(timeout=15) as client:
            while time.monotonic() < deadline:
                resp = await client.get(
                    _STATUS_URL,
                    params={"video_id": video_id},
                    headers=self._headers(),
                )
                if resp.status_code != 200:
                    raise AvatarQualityError(
                        f"HeyGen status check failed: HTTP {resp.status_code} — {resp.text}"
                    )

                data = resp.json()
                status: str = (
                    data.get("data", {}).get("status")
                    or data.get("status", "")
                )
                logger.debug("HeyGen: video_id=%s status=%s", video_id, status)

                if status == "completed":
                    video_url: Optional[str] = (
                        data.get("data", {}).get("video_url")
                        or data.get("video_url")
                    )
                    if not video_url:
                        raise AvatarQualityError(
                            f"HeyGen completed but video_url missing: {data}"
                        )
                    return video_url

                if status == "failed":
                    error_msg = (
                        data.get("data", {}).get("error")
                        or data.get("error", "unknown error")
                    )
                    raise AvatarQualityError(
                        f"HeyGen generation failed (video_id={video_id}): {error_msg}"
                    )

                await asyncio.sleep(_POLL_INTERVAL_S)

        raise AvatarQualityError(
            f"HeyGen generation timed out after {_TIMEOUT_S // 60} minutes "
            f"(video_id={video_id}). Ensure your HeyGen plan has priority queue access."
        )

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
                f"HeyGen: downloaded file is empty or missing: {output_path}"
            )
