"""
B-roll type: browser_visit

Headless Playwright screenshot of the topic article URL, animated as
a smooth downward scroll via FFmpeg crop filter.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from playwright.async_api import async_playwright
from playwright.async_api import Error as PlaywrightError
from PIL import Image

from .base import BrollBase, BrollError

if TYPE_CHECKING:
    from pipeline import VideoJob

logger = logging.getLogger(__name__)

# Non-article URL fragments that cannot be scrolled as an article
_NON_ARTICLE_FRAGMENTS = (
    "youtube.com/watch",
    "youtu.be",
    "twitter.com/",
    "x.com/",
)

# Maximum screenshot height before Pillow crops (3× viewport height)
_VIEWPORT_HEIGHT = 720
_VIEWPORT_WIDTH = 1280
_MAX_SCREENSHOT_HEIGHT = _VIEWPORT_HEIGHT * 3  # 2160 px

# Minimum word count to consider a page non-paywalled
_MIN_WORD_COUNT = 200

# FFmpeg output dimensions
_OUTPUT_WIDTH = 1080
_OUTPUT_HEIGHT = 540


class BrowserVisitGenerator(BrollBase):
    """
    B-roll generator that screenshots a topic article URL and animates
    it as a smooth downward scroll via an FFmpeg crop filter.

    No external services required beyond a locally installed Playwright
    Chromium browser and FFmpeg on PATH.

    Raises:
        BrollError: If the URL is a non-article (video/social), the page
                    is paywalled, Playwright navigation fails, or FFmpeg
                    encoding fails.
    """

    def __init__(self) -> None:
        pass

    async def generate(
        self,
        job: "VideoJob",
        target_duration_s: float,
        output_path: str,
    ) -> str:
        """
        Generate a scrolling browser-visit b-roll clip.

        Args:
            job: VideoJob with ``topic["url"]`` and ``topic["title"]``.
            target_duration_s: Desired clip length in seconds.
            output_path: Local file path where the generated MP4 is saved.

        Returns:
            output_path on success.

        Raises:
            BrollError: On non-article URL, paywall, navigation failure,
                        or FFmpeg error.
        """
        url: str = job.topic.get("url", "")
        title: str = job.topic.get("title", "")

        # R8 — reject non-article URLs before touching the browser
        self._check_non_article(url)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Use a temp file for the intermediate screenshot PNG
        fd, tmp_png = tempfile.mkstemp(suffix=".png")
        os.close(fd)

        try:
            await self._screenshot(url, tmp_png)
            await self._ffmpeg_scroll(tmp_png, target_duration_s, output_path)
        finally:
            if os.path.exists(tmp_png):
                os.unlink(tmp_png)

        logger.info(
            "BrowserVisitGenerator: clip saved to %s (url=%s, duration=%.1fs)",
            output_path,
            url,
            target_duration_s,
        )
        return output_path

    # ─── Private helpers ──────────────────────────────────────────────────

    def _check_non_article(self, url: str) -> None:
        """Raise BrollError immediately for non-article URLs (R8)."""
        for fragment in _NON_ARTICLE_FRAGMENTS:
            if fragment in url:
                raise BrollError(f"non-article URL: {url!r} contains {fragment!r}")

    async def _screenshot(self, url: str, tmp_png: str) -> None:
        """Navigate to url and save a full-page screenshot to tmp_png.

        Raises:
            BrollError: On paywall detection (word count < 200) or
                        Playwright navigation failure.
        """
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(
                        viewport={"width": _VIEWPORT_WIDTH, "height": _VIEWPORT_HEIGHT}
                    )
                    await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=15000,
                    )

                    # R8 — paywall / login-wall detection
                    body_text: str = await page.inner_text("body")
                    word_count = len(body_text.split())
                    if word_count < _MIN_WORD_COUNT:
                        raise BrollError(
                            f"paywall or insufficient content: word count {word_count} < {_MIN_WORD_COUNT}"
                        )

                    await page.screenshot(path=tmp_png, full_page=True)
                finally:
                    await browser.close()
        except BrollError:
            raise
        except PlaywrightError as e:
            raise BrollError(f"playwright: {e}") from e

        # Crop over-tall screenshots with Pillow before passing to FFmpeg
        self._maybe_crop_png(tmp_png)

    def _maybe_crop_png(self, png_path: str) -> None:
        """If the PNG is taller than _MAX_SCREENSHOT_HEIGHT, crop it in place."""
        img = Image.open(png_path)
        width, height = img.size
        if height > _MAX_SCREENSHOT_HEIGHT:
            logger.debug(
                "BrowserVisitGenerator: cropping tall screenshot from %dpx to %dpx",
                height,
                _MAX_SCREENSHOT_HEIGHT,
            )
            img = img.crop((0, 0, width, _MAX_SCREENSHOT_HEIGHT))
            img.save(png_path)

    async def _ffmpeg_scroll(
        self,
        png_path: str,
        duration: float,
        output_path: str,
    ) -> None:
        """Encode the PNG screenshot as a scrolling MP4 via FFmpeg.

        Uses a ``crop`` filter with a time-varying ``y`` offset so the image
        smoothly scrolls downward over ``duration`` seconds.

        Raises:
            BrollError: If FFmpeg exits with a non-zero return code.
        """
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", png_path,
            "-t", str(duration),
            "-vf",
            (
                f"scale={_OUTPUT_WIDTH}:-1,"
                f"crop={_OUTPUT_WIDTH}:{_OUTPUT_HEIGHT}:0:'(ih-{_OUTPUT_HEIGHT})*t/{duration}'"
            ),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            output_path,
        ]
        logger.debug("BrowserVisitGenerator: ffmpeg cmd: %s", " ".join(cmd))

        try:
            await asyncio.to_thread(
                subprocess.run,
                cmd,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise BrollError(
                f"ffmpeg failed: {e.stderr.decode(errors='replace')}"
            ) from e
