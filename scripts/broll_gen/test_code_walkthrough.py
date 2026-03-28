"""
Tests for CodeWalkthroughGenerator.

All external I/O (Claude, Pygments ImageFormatter, subprocess/ffmpeg) is mocked
so the suite runs without API keys, a GPU, or ffmpeg installed.
"""

from __future__ import annotations

import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broll_gen.base import BrollError
from broll_gen.code_walkthrough import CodeWalkthroughGenerator


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_SAMPLE_CODE = (
    "def hello():\n"
    "    print('hello')\n"
    "\n"
    "def goodbye():\n"
    "    print('goodbye')\n"
    "\n"
    "def greet(name):\n"
    "    print(f'Hello, {name}!')\n"
    "\n"
    "greet('world')\n"
)


def _make_mock_client(code_text: str = _SAMPLE_CODE) -> MagicMock:
    """Return a mock AsyncAnthropic client whose messages.create resolves to code_text."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=code_text)]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    return mock_client


def _make_video_job(title: str = "Python async patterns") -> MagicMock:
    """Return a minimal VideoJob-like object."""
    job = MagicMock()
    job.topic = {"title": title, "summary": "A look at async/await patterns in Python."}
    return job


# ---------------------------------------------------------------------------
# Test 1: happy path — returns output_path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_happy_path_returns_output_path(tmp_path):
    """Mock Claude + ImageFormatter + subprocess; assert output_path returned."""
    output_path = str(tmp_path / "out.mp4")
    job = _make_video_job()
    mock_client = _make_mock_client(_SAMPLE_CODE)

    # Patch ImageFormatter so it returns dummy PNG bytes without PIL/fonts
    fake_png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # minimal fake PNG header

    with patch("broll_gen.code_walkthrough.ImageFormatter") as MockFormatter, \
         patch("broll_gen.code_walkthrough.highlight", return_value=fake_png_bytes), \
         patch("broll_gen.code_walkthrough.subprocess.run") as mock_run:

        # ImageFormatter() instance — not used directly (highlight is mocked)
        MockFormatter.return_value = MagicMock()
        mock_run.return_value = MagicMock(returncode=0)

        gen = CodeWalkthroughGenerator(mock_client)
        result = await gen.generate(job, target_duration_s=10.0, output_path=output_path)

    assert result == output_path
    mock_client.messages.create.assert_awaited_once()
    mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# Test 2: empty Claude response → BrollError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_code_raises():
    """When Claude returns an empty string, BrollError must be raised."""
    job = _make_video_job()
    mock_client = _make_mock_client(code_text="")

    fake_png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    with patch("broll_gen.code_walkthrough.ImageFormatter"), \
         patch("broll_gen.code_walkthrough.highlight", return_value=fake_png_bytes), \
         patch("broll_gen.code_walkthrough.subprocess.run"):

        gen = CodeWalkthroughGenerator(mock_client)
        with pytest.raises(BrollError, match="empty code"):
            await gen.generate(job, target_duration_s=10.0, output_path="/tmp/out.mp4")


# ---------------------------------------------------------------------------
# Test 3: ffmpeg failure → BrollError("ffmpeg failed")
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ffmpeg_error_raises():
    """When subprocess.run raises CalledProcessError, BrollError('ffmpeg failed') is raised."""
    job = _make_video_job()
    mock_client = _make_mock_client(_SAMPLE_CODE)

    fake_png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    ffmpeg_error = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ffmpeg"],
        stderr=b"Error: codec not found",
    )

    with patch("broll_gen.code_walkthrough.ImageFormatter") as MockFormatter, \
         patch("broll_gen.code_walkthrough.highlight", return_value=fake_png_bytes), \
         patch("broll_gen.code_walkthrough.subprocess.run", side_effect=ffmpeg_error):

        MockFormatter.return_value = MagicMock()

        gen = CodeWalkthroughGenerator(mock_client)
        with pytest.raises(BrollError, match="ffmpeg failed"):
            await gen.generate(job, target_duration_s=10.0, output_path="/tmp/out.mp4")
