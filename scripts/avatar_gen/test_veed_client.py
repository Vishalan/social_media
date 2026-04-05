"""
Unit tests for VeedFabricClient.

All HTTP calls are mocked — no live fal.ai requests.
"""

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from .base import AvatarClient, AvatarQualityError
from .veed_client import VeedFabricClient


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    return VeedFabricClient(
        fal_api_key="test-key",
        avatar_image_url="https://example.com/portrait.jpg",
        resolution="480p",
    )


# ─── Provider properties ──────────────────────────────────────────────────────

def test_is_avatar_client(client):
    assert isinstance(client, AvatarClient)


def test_needs_portrait_crop_is_false(client):
    assert client.needs_portrait_crop is False


def test_max_duration_s_is_none(client):
    assert client.max_duration_s is None


# ─── Submit payload ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_submit_sends_correct_payload(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "request_id": "req-abc",
        "status_url": "https://queue.fal.run/veed/fabric-1.0/requests/req-abc/status",
    }

    mock_post = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = mock_post
        mock_client_cls.return_value = mock_http

        request_id, status_url = await client._submit("https://example.com/audio.mp3")

    assert request_id == "req-abc"
    call_kwargs = mock_post.call_args
    body = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
    assert body["image_url"] == "https://example.com/portrait.jpg"
    assert body["audio_url"] == "https://example.com/audio.mp3"
    assert body["resolution"] == "480p"


@pytest.mark.asyncio
async def test_submit_raises_on_http_error(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = '{"detail": "Exhausted balance"}'

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_http

        with pytest.raises(AvatarQualityError, match="submission failed"):
            await client._submit("https://example.com/audio.mp3")


# ─── _extract_video_url ───────────────────────────────────────────────────────

def test_extract_video_url_nested_output(client):
    data = {"status": "COMPLETED", "output": {"video": {"url": "https://cdn/video.mp4"}}}
    assert client._extract_video_url(data) == "https://cdn/video.mp4"


def test_extract_video_url_nested_result(client):
    data = {"status": "COMPLETED", "result": {"video": {"url": "https://cdn/video.mp4"}}}
    assert client._extract_video_url(data) == "https://cdn/video.mp4"


def test_extract_video_url_flat(client):
    data = {"status": "COMPLETED", "video": {"url": "https://cdn/video.mp4"}}
    assert client._extract_video_url(data) == "https://cdn/video.mp4"


def test_extract_video_url_top_level_url(client):
    data = {"status": "COMPLETED", "url": "https://cdn/video.mp4"}
    assert client._extract_video_url(data) == "https://cdn/video.mp4"


def test_extract_video_url_returns_none_when_missing(client):
    assert client._extract_video_url({"status": "COMPLETED"}) is None


# ─── Validation ───────────────────────────────────────────────────────────────

def test_validate_raises_on_missing_file(client):
    with pytest.raises(AvatarQualityError, match="empty or missing"):
        client._validate("/nonexistent/path.mp4")


def test_validate_raises_on_zero_byte_file(client):
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        path = f.name
    try:
        with pytest.raises(AvatarQualityError, match="empty or missing"):
            client._validate(path)
    finally:
        os.unlink(path)


def test_validate_passes_on_nonempty_file(client):
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"\x00" * 100)
        path = f.name
    try:
        client._validate(path)  # should not raise
    finally:
        os.unlink(path)


# ─── Status: FAILED ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_poll_raises_on_failed_status(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "FAILED", "error": "Model crashed"}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)
        mock_http.get = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_http

        with pytest.raises(AvatarQualityError, match="generation failed"):
            await client._poll_until_complete("req-abc", "https://status.url")
