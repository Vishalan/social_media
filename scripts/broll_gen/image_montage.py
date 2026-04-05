"""
B-roll type: image_montage

Fetches 4-6 topic-relevant images from Pexels → Bing → OG image fallback
and assembles a Ken Burns slideshow (zoompan + xfade cross-fade) via FFmpeg.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from .base import BrollBase, BrollError
from video_edit.video_editor import FFMPEG

if TYPE_CHECKING:
    from pipeline import VideoJob

logger = logging.getLogger(__name__)

_PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"
_BING_SEARCH_URL = "https://api.bing.microsoft.com/v7.0/images/search"


class ImageMontageGenerator(BrollBase):
    """
    B-roll generator that assembles a Ken Burns image slideshow.

    Fetches 4–6 landscape images from Pexels → Bing → OG image fallback,
    downloads them to a temp directory, and encodes a zoompan + xfade
    slideshow via FFmpeg.

    Both API keys default to empty string and are checked at runtime.
    If a key is absent or its request fails, that source is silently skipped.

    Example::

        gen = ImageMontageGenerator(
            pexels_api_key=os.environ.get("PEXELS_API_KEY", ""),
            bing_api_key=os.environ.get("BING_SEARCH_API_KEY", ""),
        )
        path = await gen.generate(job, target_duration_s=24.0, output_path="out/broll.mp4")
    """

    def __init__(
        self,
        pexels_api_key: str = "",
        bing_api_key: str = "",
    ) -> None:
        self._pexels_key = pexels_api_key
        self._bing_key = bing_api_key

    # ─── Public interface ──────────────────────────────────────────────────

    async def generate(
        self,
        job: "VideoJob",
        target_duration_s: float,
        output_path: str,
    ) -> str:
        """
        Generate a Ken Burns image montage for the given video job.

        Args:
            job: VideoJob containing topic and source URL context.
            target_duration_s: Desired clip length in seconds.
            output_path: Local file path where the generated MP4 will be saved.

        Returns:
            output_path on success.

        Raises:
            BrollError: If fewer than 2 images can be found or downloaded,
                        or if FFmpeg encoding fails.
        """
        query = job.topic["title"]
        topic_url = job.topic.get("url", "")

        logger.info("ImageMontage: fetching images for query=%r", query)
        image_urls = await self._fetch_images(query, topic_url)

        if len(image_urls) == 0:
            raise BrollError(
                f"no images found for query={query!r}"
            )
        # Duplicate a single image so the Ken Burns + xfade pipeline always
        # has at least 2 clips to work with (graceful degradation without API keys).
        if len(image_urls) == 1:
            image_urls = image_urls * 2

        tmp_dir = Path(tempfile.mkdtemp(prefix="image_montage_"))
        try:
            downloaded = await self._download_images(image_urls, tmp_dir)

            if len(downloaded) < 2:
                raise BrollError(
                    f"too few images downloaded for query={query!r} "
                    f"(got {len(downloaded)} of {len(image_urls)})"
                )

            logger.info(
                "ImageMontage: %d images ready — building Ken Burns slideshow "
                "(duration=%.1fs, output=%s)",
                len(downloaded),
                target_duration_s,
                output_path,
            )
            await self._encode(downloaded, target_duration_s, output_path)

        finally:
            # Clean up temp files regardless of success or failure
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

        return output_path

    # ─── Image fetching ────────────────────────────────────────────────────

    async def _fetch_images(self, query: str, topic_url: str) -> list[str]:
        """
        Collect image URLs from Pexels → Bing → OG image fallback.

        Returns up to 6 deduplicated URLs.  Any source that is unavailable
        (missing key, network error, HTTP error) is silently skipped.
        """
        urls: list[str] = []

        # 1. Pexels
        if self._pexels_key:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        _PEXELS_SEARCH_URL,
                        params={"query": query, "per_page": 6, "orientation": "landscape"},
                        headers={"Authorization": self._pexels_key},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    pexels_urls = [
                        p["src"]["landscape"] for p in data.get("photos", [])
                    ]
                    logger.debug("ImageMontage: Pexels returned %d URLs", len(pexels_urls))
                    urls.extend(pexels_urls)
            except httpx.HTTPError as exc:
                logger.debug("ImageMontage: Pexels request failed (%s) — skipping", exc)

        # 2. Bing Image Search
        if self._bing_key:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        _BING_SEARCH_URL,
                        params={"q": query, "count": 6, "aspect": "Wide"},
                        headers={"Ocp-Apim-Subscription-Key": self._bing_key},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    bing_urls = [v["contentUrl"] for v in data.get("value", [])]
                    logger.debug("ImageMontage: Bing returned %d URLs", len(bing_urls))
                    urls.extend(bing_urls)
            except httpx.HTTPError as exc:
                logger.debug("ImageMontage: Bing request failed (%s) — skipping", exc)

        # 3. OG image from topic article (last resort)
        if topic_url:
            try:
                async with httpx.AsyncClient(
                    timeout=10.0, follow_redirects=True
                ) as client:
                    resp = await client.get(topic_url)
                    resp.raise_for_status()
                    html = resp.text

                    # Collect all og:image and twitter:image URLs
                    og_urls = re.findall(
                        r'og:image["\s]+content=["\']([^"\']+)', html
                    )
                    og_urls += re.findall(
                        r'twitter:image["\s]+content=["\']([^"\']+)', html
                    )

                    for og_url in og_urls:
                        # Only accept if it looks like a real image URL
                        lower = og_url.lower()
                        if any(ext in lower for ext in ("jpg", "jpeg", "png", "webp")) or og_url.startswith("http"):
                            logger.debug(
                                "ImageMontage: OG image found at %s", og_url
                            )
                            urls.append(og_url)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "ImageMontage: OG image fetch failed (%s) — skipping", exc
                )

        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                deduped.append(u)

        return deduped[:6]

    # ─── Image download ────────────────────────────────────────────────────

    async def _download_images(
        self, image_urls: list[str], tmp_dir: Path
    ) -> list[Path]:
        """
        Download each URL to tmp_dir/img_NN.jpg.

        Images that fail to download (connection error, non-200) are skipped.
        Returns list of successfully downloaded file paths.
        """
        downloaded: list[Path] = []
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            for i, url in enumerate(image_urls):
                path = tmp_dir / f"img_{i:02d}.jpg"
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    path.write_bytes(resp.content)
                    downloaded.append(path)
                    logger.debug(
                        "ImageMontage: downloaded image %d/%d (%d bytes)",
                        i + 1,
                        len(image_urls),
                        len(resp.content),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "ImageMontage: failed to download image %d (%s) — skipping",
                        i,
                        exc,
                    )
        return downloaded

    # ─── FFmpeg encoding ───────────────────────────────────────────────────

    async def _encode(
        self,
        images: list[Path],
        target_duration_s: float,
        output_path: str,
    ) -> None:
        """
        Assemble a Ken Burns slideshow from the given images using FFmpeg.

        Each image is animated with a gentle zoom (zoompan) and clips are
        joined with a 0.5-second cross-fade (xfade).  The final MP4 is
        capped to target_duration_s.

        Raises:
            BrollError: If FFmpeg exits with a non-zero return code.
        """
        fps = 30
        per_clip_s = max(3.0, target_duration_s / len(images))

        # Build per-image filter chains
        filter_parts: list[str] = []
        for idx in range(len(images)):
            zoompan_d = int(fps * per_clip_s)
            filt = (
                f"[{idx}:v]"
                "scale=1920:1080:force_original_aspect_ratio=decrease,"
                "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
                f"zoompan=z='zoom+0.001':d={zoompan_d}:s=1920x1080,"
                "setpts=PTS-STARTPTS,"
                "scale=1080:960:force_original_aspect_ratio=decrease,"
                "pad=1080:960:(ow-iw)/2:(oh-ih)/2:black"
                f"[v{idx}]"
            )
            filter_parts.append(filt)

        # Build xfade chain
        # For N clips the chain is:
        #   [v0][v1]xfade@0[xf0]; [xf0][v2]xfade@1[xf1]; ...
        # offset for clip N (0-indexed transition) = N * per_clip_s - 0.5
        if len(images) == 1:
            # No xfade needed for a single image
            filter_parts.append("[v0]null[vout]")
        else:
            prev_label = "v0"
            for t_idx in range(1, len(images)):
                offset = t_idx * per_clip_s - 0.5
                out_label = f"xf{t_idx - 1}" if t_idx < len(images) - 1 else "vout"
                filt = (
                    f"[{prev_label}][v{t_idx}]"
                    f"xfade=transition=fade:duration=0.5:offset={offset:.3f}"
                    f"[{out_label}]"
                )
                filter_parts.append(filt)
                prev_label = out_label if t_idx < len(images) - 1 else "vout"

        filtergraph = "; ".join(filter_parts)

        # Build input arguments (loop each still image for per_clip_s + 1s)
        inputs: list[str] = []
        for img_path in images:
            inputs += ["-loop", "1", "-t", str(per_clip_s + 1), "-i", str(img_path)]

        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        cmd = (
            [FFMPEG, "-y"]
            + inputs
            + [
                "-filter_complex", filtergraph,
                "-map", "[vout]",
                "-t", str(target_duration_s),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                output_path,
            ]
        )

        logger.debug("ImageMontage: FFmpeg command: %s", " ".join(cmd))

        try:
            await asyncio.to_thread(
                subprocess.run, cmd, check=True, capture_output=True
            )
        except subprocess.CalledProcessError as exc:
            stderr_snippet = exc.stderr.decode(errors="replace")[:500]
            raise BrollError(f"ffmpeg failed: {stderr_snippet}") from exc

        logger.info("ImageMontage: encoded %s (%.1fs)", output_path, target_duration_s)
