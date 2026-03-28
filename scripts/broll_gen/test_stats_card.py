"""
Tests for StatsCardGenerator.

All external I/O (Claude API, subprocess/FFmpeg, PIL file saves) is mocked
so the tests run without network access, GPU, or a real FFmpeg binary.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broll_gen.base import BrollError
from broll_gen.stats_card import StatsCardGenerator


# ---------------------------------------------------------------------------
# Minimal VideoJob stub
# ---------------------------------------------------------------------------

@dataclass
class _VideoJob:
    """Minimal VideoJob stand-in for unit tests."""
    topic: dict = field(default_factory=lambda: {"title": "Test Topic"})
    script: dict = field(
        default_factory=lambda: {
            "script": (
                "AI models are now 3x faster than last year. "
                "The cost dropped by 50%. Market cap reached $20B."
            )
        }
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_THREE_STATS_JSON = json.dumps({
    "stats": [
        {"value": "3x faster", "label": "Speed improvement"},
        {"value": "50% cheaper", "label": "Cost reduction"},
        {"value": "$20B", "label": "Market cap"},
    ]
})

_ONE_STAT_JSON = json.dumps({
    "stats": [
        {"value": "only one", "label": "stat"},
    ]
})


def _make_mock_client(response_text: str) -> MagicMock:
    """Build a mock AsyncAnthropic client that returns response_text."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=response_text)]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    return mock_client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_happy_path_returns_output_path(tmp_path):
    """Claude returns 3 valid stats → generator returns output_path."""
    mock_client = _make_mock_client(_THREE_STATS_JSON)
    generator = StatsCardGenerator(mock_client)

    output_path = str(tmp_path / "broll.mp4")
    job = _VideoJob()

    with (
        patch("broll_gen.stats_card.subprocess.run") as mock_run,
        patch("broll_gen.stats_card._render_frame") as mock_render,
        patch("shutil.rmtree"),
    ):
        # _render_frame must return a real PIL Image so .save() works
        from PIL import Image
        mock_render.side_effect = lambda stats, total: Image.new(
            "RGB", (1080, 540), color=(18, 18, 25)
        )
        mock_run.return_value = MagicMock(returncode=0)

        result = await generator.generate(job, target_duration_s=9.0, output_path=output_path)

    assert result == output_path
    mock_client.messages.create.assert_awaited_once()
    mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_insufficient_stats_raises():
    """Claude returns only 1 stat → BrollError raised before FFmpeg is called."""
    mock_client = _make_mock_client(_ONE_STAT_JSON)
    generator = StatsCardGenerator(mock_client)
    job = _VideoJob()

    with (
        patch("broll_gen.stats_card.subprocess.run") as mock_run,
        patch("shutil.rmtree"),
    ):
        with pytest.raises(BrollError, match="insufficient stats"):
            await generator.generate(job, target_duration_s=9.0, output_path="/tmp/out.mp4")

    mock_run.assert_not_called()


@pytest.mark.asyncio
async def test_ffmpeg_error_raises(tmp_path):
    """Claude returns 3 stats but FFmpeg fails → BrollError wrapping ffmpeg failure."""
    mock_client = _make_mock_client(_THREE_STATS_JSON)
    generator = StatsCardGenerator(mock_client)

    output_path = str(tmp_path / "broll.mp4")
    job = _VideoJob()

    ffmpeg_error = subprocess.CalledProcessError(
        returncode=1, cmd="ffmpeg", stderr=b"error: codec not found"
    )

    with (
        patch("broll_gen.stats_card.subprocess.run", side_effect=ffmpeg_error),
        patch("broll_gen.stats_card._render_frame") as mock_render,
        patch("shutil.rmtree"),
    ):
        from PIL import Image
        mock_render.side_effect = lambda stats, total: Image.new(
            "RGB", (1080, 540), color=(18, 18, 25)
        )

        with pytest.raises(BrollError, match="ffmpeg failed"):
            await generator.generate(job, target_duration_s=9.0, output_path=output_path)
