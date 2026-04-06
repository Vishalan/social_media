"""
PostizPoster — thumbnail-aware posting backend for self-hosted Postiz API.

Posts video + thumbnail to YouTube, Instagram, TikTok, and X via Postiz's
public REST API. Designed as a drop-in alternative to the Ayrshare-based
SocialPoster for the thumbnail-engine pipeline.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

POSTIZ_POSTS_PATH = "/public/v1/posts"

# Per-platform caption length caps (only enforced where Postiz/upstream require it)
YOUTUBE_TITLE_MAX = 100


class PostizPoster:
    """Post video + thumbnail to multiple platforms via the Postiz API."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        """
        Initialize the Postiz poster.

        Args:
            base_url: Base URL of the self-hosted Postiz instance
                (e.g. ``http://synology.local:5000``).
            api_key: Postiz API key.
            timeout: HTTP request timeout in seconds.
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _build_platform_payload(
        self,
        platforms: list[str],
        caption: str,
        thumbnail_path: Path | None,
    ) -> list[dict[str, Any]]:
        """Build the per-platform settings list embedded in the JSON body."""
        payload: list[dict[str, Any]] = []
        for platform in platforms:
            if platform == "youtube":
                payload.append(
                    {
                        "platform": "youtube",
                        "title": caption[:YOUTUBE_TITLE_MAX],
                        # The thumbnail is uploaded as a separate multipart field;
                        # Postiz references it by filename here.
                        "thumbnail": thumbnail_path.name if thumbnail_path else None,
                    }
                )
            elif platform == "instagram":
                payload.append(
                    {
                        "platform": "instagram",
                        "caption": caption,
                        # TODO verify field name — Postiz docs are ambiguous on
                        # whether this should be coverUrl, cover, or thumbnail.
                        "coverUrl": thumbnail_path.name if thumbnail_path else None,
                    }
                )
            elif platform == "tiktok":
                payload.append(
                    {
                        "platform": "tiktok",
                        "caption": caption,
                        # TikTok API does not accept arbitrary cover images;
                        # only a frame timestamp from the video. See
                        # docs/brainstorms/2026-04-06-thumbnail-engine-requirements.md
                        # and reference_tiktok_cover_limit memory.
                        "videoCoverTimestampMs": 0,
                    }
                )
            elif platform == "x":
                payload.append({"platform": "x", "text": caption})
            else:
                raise ValueError(f"Unsupported platform for PostizPoster: {platform}")
        return payload

    def post(
        self,
        video_path: Path,
        caption: str,
        thumbnail_path: Path | None,
        platforms: list[str],
    ) -> dict:
        """
        Post a video (with thumbnail) to one or more platforms via Postiz.

        Args:
            video_path: Path to the rendered video file.
            caption: Caption / title text. Will be truncated per-platform.
            thumbnail_path: Path to the thumbnail image. Required — pass an
                explicit thumbnail; this backend is the thumbnail-aware
                variant.
            platforms: Subset of {"youtube", "instagram", "tiktok", "x"}.

        Returns:
            Parsed JSON response from Postiz on success.

        Raises:
            ValueError: If ``thumbnail_path`` is None.
            FileNotFoundError: If ``video_path`` does not exist.
            requests.HTTPError: For 4xx responses (raised immediately) or
                persistent 5xx responses (after retries).
        """
        if thumbnail_path is None:
            raise ValueError(
                "PostizPoster requires a thumbnail_path; this backend is "
                "the thumbnail-aware variant."
            )

        video_path = Path(video_path)
        thumbnail_path = Path(thumbnail_path)

        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        url = f"{self.base_url}{POSTIZ_POSTS_PATH}"
        # TODO verify auth scheme — Postiz docs use the raw API key as the
        # Authorization header value by default; "Bearer <key>" is a fallback
        # to confirm at integration time.
        headers = {"Authorization": self.api_key}

        platform_payload = self._build_platform_payload(
            platforms, caption, thumbnail_path
        )
        body = {"caption": caption, "platforms": platform_payload}

        max_attempts = 3  # 1 initial + 2 retries
        backoff_seconds = [1, 2]

        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            # Re-open files on each attempt — file handles are consumed.
            with open(video_path, "rb") as vf, open(thumbnail_path, "rb") as tf:
                files = {
                    "video": (video_path.name, vf, "video/mp4"),
                    "thumbnail": (thumbnail_path.name, tf, "image/jpeg"),
                }
                data = {"payload": json.dumps(body)}

                logger.info(
                    "Postiz POST %s (attempt %d/%d) platforms=%s",
                    url,
                    attempt + 1,
                    max_attempts,
                    platforms,
                )
                try:
                    response = requests.post(
                        url,
                        headers=headers,
                        files=files,
                        data=data,
                        timeout=self.timeout,
                    )
                except requests.RequestException as exc:
                    last_exc = exc
                    logger.warning("Postiz request error: %s", exc)
                    if attempt < max_attempts - 1:
                        time.sleep(backoff_seconds[attempt])
                        continue
                    raise

            status = response.status_code
            if 200 <= status < 300:
                return response.json()

            body_text = response.text
            if 400 <= status < 500:
                # Client error — do not retry.
                raise requests.HTTPError(
                    f"Postiz client error {status}: {body_text}",
                    response=response,
                )

            # 5xx — retry with backoff
            logger.warning(
                "Postiz server error %d on attempt %d/%d: %s",
                status,
                attempt + 1,
                max_attempts,
                body_text,
            )
            if attempt < max_attempts - 1:
                time.sleep(backoff_seconds[attempt])
                continue

            raise requests.HTTPError(
                f"Postiz server error {status} after {max_attempts} attempts: {body_text}",
                response=response,
            )

        # Defensive — should be unreachable
        if last_exc:
            raise last_exc
        raise RuntimeError("PostizPoster.post exited retry loop unexpectedly")
