"""Tests for BrowserVisitGenerator."""

from __future__ import annotations

import os
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broll_gen.browser_visit import BrowserVisitGenerator
from broll_gen.base import BrollError


class _MockJob:
    topic = {"url": "https://techcrunch.com/article", "title": "test"}
    script = {}


class _YouTubeJob:
    topic = {"url": "https://youtube.com/watch?v=abc", "title": "test"}
    script = {}


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_playwright_mock(body_text: str = "", screenshot_side_effect=None):
    """Return a nested async-context-manager mock for async_playwright()."""
    page_mock = AsyncMock()
    page_mock.goto = AsyncMock(return_value=None)
    page_mock.inner_text = AsyncMock(return_value=body_text)
    if screenshot_side_effect:
        page_mock.screenshot = AsyncMock(side_effect=screenshot_side_effect)
    else:
        page_mock.screenshot = AsyncMock(return_value=None)

    browser_mock = AsyncMock()
    browser_mock.new_page = AsyncMock(return_value=page_mock)
    browser_mock.close = AsyncMock(return_value=None)

    chromium_mock = MagicMock()
    chromium_mock.launch = AsyncMock(return_value=browser_mock)

    playwright_instance = AsyncMock()
    playwright_instance.chromium = chromium_mock
    playwright_instance.__aenter__ = AsyncMock(return_value=playwright_instance)
    playwright_instance.__aexit__ = AsyncMock(return_value=False)

    return playwright_instance, page_mock


def _long_body_text() -> str:
    """Return a string with 250+ words."""
    return " ".join(["word"] * 250)


# ─── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_article_url_raises():
    """Non-article URLs (YouTube) must raise BrollError before any browser launch."""
    gen = BrowserVisitGenerator()
    with patch("broll_gen.browser_visit.async_playwright") as mock_ap:
        # async_playwright should never be called
        with pytest.raises(BrollError, match="non-article URL"):
            await gen.generate(_YouTubeJob(), target_duration_s=5.0, output_path="/tmp/out.mp4")
        mock_ap.assert_not_called()


@pytest.mark.asyncio
async def test_paywall_raises():
    """A page with < 200 words in the body must raise BrollError with 'paywall'."""
    gen = BrowserVisitGenerator()
    playwright_instance, _ = _make_playwright_mock(body_text="short")

    with patch("broll_gen.browser_visit.async_playwright", return_value=playwright_instance):
        with pytest.raises(BrollError, match="paywall"):
            await gen.generate(_MockJob(), target_duration_s=5.0, output_path="/tmp/out.mp4")


@pytest.mark.asyncio
async def test_happy_path_returns_output_path(tmp_path):
    """Happy path: mocked Playwright + FFmpeg should return the output path."""
    output_path = str(tmp_path / "broll.mp4")
    gen = BrowserVisitGenerator()

    playwright_instance, page_mock = _make_playwright_mock(body_text=_long_body_text())

    # Make screenshot write a minimal valid PNG so Pillow can open it
    def _write_png(path, **kwargs):
        from PIL import Image
        img = Image.new("RGB", (1280, 900), color=(255, 255, 255))
        img.save(path)

    page_mock.screenshot = AsyncMock(
        side_effect=lambda **kwargs: _write_png(kwargs["path"])
    )

    ffmpeg_result = MagicMock()
    ffmpeg_result.returncode = 0

    with patch("broll_gen.browser_visit.async_playwright", return_value=playwright_instance):
        with patch("broll_gen.browser_visit.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.return_value = ffmpeg_result
            result = await gen.generate(_MockJob(), target_duration_s=5.0, output_path=output_path)

    assert result == output_path
    # Verify FFmpeg was invoked through asyncio.to_thread
    mock_thread.assert_called_once()
    call_args = mock_thread.call_args
    # First positional arg is subprocess.run; second is the cmd list
    assert call_args.args[0] is subprocess.run
    ffmpeg_cmd: list = call_args.args[1]
    assert "ffmpeg" in ffmpeg_cmd
    assert output_path in ffmpeg_cmd
