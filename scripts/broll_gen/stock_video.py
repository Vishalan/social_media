"""
B-roll type: stock_video

Fetches cinematic clips from Pexels video API and encodes them into a
portrait-format (1080x1920) MP4 at 30 fps.  No external GPU needed — all
heavy lifting is done by the Pexels CDN and a local FFmpeg installation.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
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

_W = 1080
_H = 1920
_FPS = 30
_PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"


class StockVideoGenerator(BrollBase):
    """
    B-roll generator that fetches cinematic portrait video clips from Pexels.

    Searches the Pexels video API for clips relevant to the video topic,
    downloads up to 3 clips, scale-crops each to 1080x1920 for portrait
    format, trims them to equal durations, and xfade-concatenates them into
    a single MP4.  No GPU required.

    Example::

        gen = StockVideoGenerator(pexels_api_key=os.environ.get("PEXELS_API_KEY", ""))
        path = await gen.generate(job, target_duration_s=10.0, output_path="out/broll.mp4")
    """

    def __init__(self, pexels_api_key: str = "") -> None:
        self._pexels_key = pexels_api_key

    # ─── Public interface ──────────────────────────────────────────────────

    async def generate(
        self,
        job: "VideoJob",
        target_duration_s: float,
        output_path: str,
    ) -> str:
        """
        Fetch Pexels video clips and encode a portrait-format b-roll clip.

        Args:
            job: VideoJob containing the topic dict (must have a "title" key).
            target_duration_s: Desired clip length in seconds.
            output_path: Local file path where the generated MP4 will be saved.

        Returns:
            output_path on success.

        Raises:
            BrollError: If the API key is missing, no results are found,
                        a download fails, or FFmpeg encoding fails.
        """
        query = job.topic.get("title", "") + " technology"

        if not self._pexels_key:
            raise BrollError("PEXELS_API_KEY not configured")

        logger.info("StockVideo: searching Pexels for query=%r", query)
        clips = await self._fetch_video_clips(query)

        if len(clips) == 0:
            raise BrollError(f"no Pexels video results for: {query!r}")

        n_clips = min(3, len(clips))
        clips = clips[:n_clips]
        per_clip_s = target_duration_s / n_clips

        tmp_dir = Path(tempfile.mkdtemp(prefix="stockvid_"))
        try:
            # Download raw clips
            raw_paths: list[Path] = []
            for i, clip in enumerate(clips):
                raw_path = tmp_dir / f"clip_{i:02d}_raw.mp4"
                logger.debug("StockVideo: downloading clip %d/%d from %s", i + 1, n_clips, clip["url"])
                await self._download_clip(clip["url"], raw_path)
                raw_paths.append(raw_path)

            # FFmpeg-encode each raw clip: scale+crop to portrait, trim
            encoded_paths: list[Path] = []
            for i, raw_path in enumerate(raw_paths):
                encoded_path = tmp_dir / f"clip_{i:02d}_enc.mp4"
                cmd = [
                    FFMPEG, "-y",
                    "-i", str(raw_path),
                    "-vf",
                    f"scale={_W}:{_H}:force_original_aspect_ratio=increase,crop={_W}:{_H}",
                    "-t", str(per_clip_s),
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-r", str(_FPS),
                    str(encoded_path),
                ]
                try:
                    await asyncio.to_thread(
                        subprocess.run, cmd, check=True, capture_output=True
                    )
                except subprocess.CalledProcessError as exc:
                    stderr_snippet = exc.stderr.decode(errors="replace")[:500]
                    raise BrollError(f"ffmpeg encode failed for clip {i}: {stderr_snippet}") from exc
                encoded_paths.append(encoded_path)
                logger.debug("StockVideo: encoded clip %d -> %s", i, encoded_path)

            # Assemble final output
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            if n_clips == 1:
                shutil.copy2(encoded_paths[0], output_path)
            else:
                await self._xfade_concat(encoded_paths, per_clip_s, output_path)

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        logger.info("StockVideo: saved %s (%.1fs, %d clips)", output_path, target_duration_s, n_clips)
        return output_path

    # ─── Pexels API ────────────────────────────────────────────────────────

    async def _fetch_video_clips(self, query: str) -> list[dict]:
        """
        Search Pexels for portrait video clips matching query.

        Returns a list of dicts with keys: ``url``, ``width``, ``height``.
        Prefers HD MP4 files; falls back to SD MP4 if no HD is available.
        """
        params = {"query": query, "per_page": 5, "orientation": "portrait"}
        # Pexels video API uses the raw API key — NO "Bearer" prefix
        headers = {"Authorization": self._pexels_key}

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                response = await client.get(
                    _PEXELS_VIDEO_URL, params=params, headers=headers
                )
            except httpx.HTTPError as exc:
                raise BrollError(f"Pexels request failed: {exc}") from exc

            if response.status_code == 401:
                raise BrollError("Pexels API key invalid (401)")
            if response.status_code == 429:
                raise BrollError("Pexels rate limit exceeded (429)")
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise BrollError(f"Pexels HTTP error: {exc}") from exc

            data = response.json()

        results: list[dict] = []
        for video in data.get("videos", []):
            video_files = video.get("video_files", [])

            # Prefer HD MP4, fallback to SD MP4
            chosen = None
            for quality in ("hd", "sd"):
                for vf in video_files:
                    if vf.get("quality") == quality and vf.get("file_type") == "video/mp4":
                        chosen = vf
                        break
                if chosen:
                    break

            if chosen:
                results.append({
                    "url": chosen["link"],
                    "width": chosen.get("width", _W),
                    "height": chosen.get("height", _H),
                })

        if not results:
            logger.warning(
                "StockVideo: no portrait MP4 results from Pexels for query=%r", query
            )

        return results

    # ─── Download ──────────────────────────────────────────────────────────

    async def _download_clip(self, url: str, dest: Path) -> None:
        """Stream-download a video clip to dest."""
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            try:
                async with client.stream("GET", url) as response:
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        raise BrollError(f"clip download HTTP error: {exc}") from exc
                    with open(dest, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
            except httpx.HTTPError as exc:
                raise BrollError(f"clip download failed: {exc}") from exc

    # ─── FFmpeg concat ─────────────────────────────────────────────────────

    async def _xfade_concat(
        self,
        encoded_paths: list[Path],
        per_clip_s: float,
        output_path: str,
    ) -> None:
        """
        Concatenate clips with xfade transitions using FFmpeg complex filtergraph.

        For N clips, builds a chain:
          [0:v][1:v]xfade=...offset={per_clip_s-0.3}[v01];
          [v01][2:v]xfade=...[v02]; ...
        and maps the final label to the output.
        """
        n = len(encoded_paths)

        # Input flags
        inputs: list[str] = []
        for p in encoded_paths:
            inputs += ["-i", str(p)]

        # Build filtergraph
        filter_parts: list[str] = []
        prev_label = "0:v"
        for i in range(1, n):
            offset = max(0.05, per_clip_s * i - 0.3)
            if i < n - 1:
                out_label = f"v{i:02d}"
            else:
                out_label = f"vfinal"
            filter_parts.append(
                f"[{prev_label}][{i}:v]"
                f"xfade=transition=fade:duration=0.3:offset={offset:.3f}"
                f"[{out_label}]"
            )
            prev_label = out_label

        cmd = (
            [FFMPEG, "-y"]
            + inputs
            + [
                "-filter_complex", "; ".join(filter_parts),
                "-map", f"[{prev_label}]",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                output_path,
            ]
        )

        try:
            await asyncio.to_thread(
                subprocess.run, cmd, check=True, capture_output=True
            )
        except subprocess.CalledProcessError as exc:
            stderr_snippet = exc.stderr.decode(errors="replace")[:600]
            raise BrollError(f"ffmpeg xfade concat failed: {stderr_snippet}") from exc
