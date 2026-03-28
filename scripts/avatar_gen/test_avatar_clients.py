"""
Unit tests for HeyGenAvatarClient, KlingAvatarClient, and make_avatar_client.

All HTTP calls are mocked via unittest.mock — no real network requests are made.

Run with:
    pytest scripts/avatar_gen/test_avatar_clients.py -v
"""

import asyncio
import itertools
import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

from scripts.avatar_gen.base import AvatarQualityError
from scripts.avatar_gen.factory import make_avatar_client
from scripts.avatar_gen.heygen_client import HeyGenAvatarClient
from scripts.avatar_gen.kling_client import KlingAvatarClient


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_httpx_response(status_code: int, json_data: dict) -> MagicMock:
    """Build a mock httpx Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    resp.raise_for_status = MagicMock()
    return resp


def _async_gen(chunks):
    """Return an async generator yielding the given bytes chunks."""
    async def _gen():
        for chunk in chunks:
            yield chunk
    return _gen()


# ─── HeyGen tests ─────────────────────────────────────────────────────────────

class TestHeyGenAvatarClientHappyPath:
    """HeyGen: successful 2-poll completion and file download."""

    @pytest.fixture
    def client(self, tmp_path):
        return HeyGenAvatarClient(
            api_key="test-key",
            avatar_id="avatar-123",
            output_dir=str(tmp_path / "avatar"),
        )

    @pytest.mark.asyncio
    async def test_generate_returns_output_path(self, client, tmp_path):
        output_path = str(tmp_path / "avatar" / "clip.mp4")

        # Submission response
        submit_resp = _make_httpx_response(200, {"data": {"video_id": "vid-001"}})

        # Poll: first call → processing, second call → completed
        poll_processing = _make_httpx_response(
            200, {"data": {"status": "processing"}}
        )
        poll_completed = _make_httpx_response(
            200,
            {"data": {"status": "completed", "video_url": "https://cdn.heygen.com/vid-001.mp4"}},
        )

        # Download mock: stream context manager
        download_resp = MagicMock()
        download_resp.__aenter__ = AsyncMock(return_value=download_resp)
        download_resp.__aexit__ = AsyncMock(return_value=False)
        download_resp.raise_for_status = MagicMock()
        download_resp.aiter_bytes = MagicMock(
            return_value=_async_gen([b"fake-video-data"])
        )

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=submit_resp)
        mock_client_instance.get = AsyncMock(
            side_effect=[poll_processing, poll_completed]
        )
        mock_client_instance.stream = MagicMock(return_value=download_resp)

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)

        with patch("scripts.avatar_gen.heygen_client.httpx.AsyncClient",
                   return_value=mock_async_client), \
             patch("scripts.avatar_gen.heygen_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.generate("https://audio.url/clip.mp3", output_path)

        assert result == output_path
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0


class TestHeyGenAvatarClientErrorStatus:
    """HeyGen: 'failed' status raises AvatarQualityError."""

    @pytest.fixture
    def client(self, tmp_path):
        return HeyGenAvatarClient(
            api_key="test-key",
            avatar_id="avatar-123",
            output_dir=str(tmp_path / "avatar"),
        )

    @pytest.mark.asyncio
    async def test_failed_status_raises(self, client, tmp_path):
        output_path = str(tmp_path / "avatar" / "clip.mp4")

        submit_resp = _make_httpx_response(200, {"data": {"video_id": "vid-002"}})
        poll_failed = _make_httpx_response(
            200, {"data": {"status": "failed", "error": "render error"}}
        )

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=submit_resp)
        mock_client_instance.get = AsyncMock(return_value=poll_failed)

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)

        with patch("scripts.avatar_gen.heygen_client.httpx.AsyncClient",
                   return_value=mock_async_client), \
             pytest.raises(AvatarQualityError, match="failed"):
            await client.generate("https://audio.url/clip.mp3", output_path)


class TestHeyGenAvatarClientTimeout:
    """HeyGen: timeout raises AvatarQualityError with descriptive message."""

    @pytest.fixture
    def client(self, tmp_path):
        return HeyGenAvatarClient(
            api_key="test-key",
            avatar_id="avatar-123",
            output_dir=str(tmp_path / "avatar"),
        )

    @pytest.mark.asyncio
    async def test_timeout_raises(self, client, tmp_path):
        output_path = str(tmp_path / "avatar" / "clip.mp4")

        submit_resp = _make_httpx_response(200, {"data": {"video_id": "vid-003"}})
        poll_processing = _make_httpx_response(200, {"data": {"status": "processing"}})

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=submit_resp)
        mock_client_instance.get = AsyncMock(return_value=poll_processing)

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)

        # Patching time.monotonic globally (asyncio.sleep also calls it internally).
        # First call sets the deadline; all subsequent calls return a past-deadline
        # value so the while loop never enters and timeout is raised immediately.
        _base = time.monotonic()
        _past = _base + 20 * 60 + 1  # _TIMEOUT_S = 20 * 60 in heygen_client
        monotonic_seq = itertools.chain([_base], itertools.repeat(_past))

        with patch("scripts.avatar_gen.heygen_client.httpx.AsyncClient",
                   return_value=mock_async_client), \
             patch("scripts.avatar_gen.heygen_client.time.monotonic",
                   side_effect=lambda: next(monotonic_seq)), \
             pytest.raises(AvatarQualityError, match="timed out"):
            await client.generate("https://audio.url/clip.mp3", output_path)


class TestHeyGenAvatarClientEmptyFile:
    """HeyGen: empty downloaded file raises AvatarQualityError."""

    @pytest.fixture
    def client(self, tmp_path):
        return HeyGenAvatarClient(
            api_key="test-key",
            avatar_id="avatar-123",
            output_dir=str(tmp_path / "avatar"),
        )

    @pytest.mark.asyncio
    async def test_empty_file_raises(self, client, tmp_path):
        output_path = str(tmp_path / "avatar" / "clip.mp4")

        submit_resp = _make_httpx_response(200, {"data": {"video_id": "vid-004"}})
        poll_completed = _make_httpx_response(
            200,
            {"data": {"status": "completed", "video_url": "https://cdn.heygen.com/vid-004.mp4"}},
        )

        # Download yields no bytes → empty file
        download_resp = MagicMock()
        download_resp.__aenter__ = AsyncMock(return_value=download_resp)
        download_resp.__aexit__ = AsyncMock(return_value=False)
        download_resp.raise_for_status = MagicMock()
        download_resp.aiter_bytes = MagicMock(return_value=_async_gen([]))

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=submit_resp)
        mock_client_instance.get = AsyncMock(return_value=poll_completed)
        mock_client_instance.stream = MagicMock(return_value=download_resp)

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)

        with patch("scripts.avatar_gen.heygen_client.httpx.AsyncClient",
                   return_value=mock_async_client), \
             patch("scripts.avatar_gen.heygen_client.asyncio.sleep", new_callable=AsyncMock), \
             pytest.raises(AvatarQualityError, match="empty"):
            await client.generate("https://audio.url/clip.mp3", output_path)


# ─── Kling tests ──────────────────────────────────────────────────────────────

class TestKlingAvatarClientHappyPath:
    """Kling: successful queue completion and file download."""

    @pytest.fixture
    def client(self, tmp_path):
        return KlingAvatarClient(
            fal_api_key="fal-key",
            avatar_image_url="https://example.com/avatar.jpg",
            output_dir=str(tmp_path / "avatar"),
        )

    @pytest.mark.asyncio
    async def test_generate_returns_output_path(self, client, tmp_path):
        output_path = str(tmp_path / "avatar" / "clip.mp4")

        submit_resp = _make_httpx_response(
            200,
            {
                "request_id": "req-001",
                "status_url": "https://queue.fal.run/.../requests/req-001/status",
            },
        )
        poll_in_queue = _make_httpx_response(200, {"status": "IN_QUEUE"})
        poll_completed = _make_httpx_response(
            200,
            {
                "status": "COMPLETED",
                "output": {"video": {"url": "https://cdn.fal.ai/req-001.mp4"}},
            },
        )

        download_resp = MagicMock()
        download_resp.__aenter__ = AsyncMock(return_value=download_resp)
        download_resp.__aexit__ = AsyncMock(return_value=False)
        download_resp.raise_for_status = MagicMock()
        download_resp.aiter_bytes = MagicMock(
            return_value=_async_gen([b"fake-kling-video"])
        )

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=submit_resp)
        mock_client_instance.get = AsyncMock(
            side_effect=[poll_in_queue, poll_completed]
        )
        mock_client_instance.stream = MagicMock(return_value=download_resp)

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)

        with patch("scripts.avatar_gen.kling_client.httpx.AsyncClient",
                   return_value=mock_async_client), \
             patch("scripts.avatar_gen.kling_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.generate("https://audio.url/clip.mp3", output_path)

        assert result == output_path
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0


class TestKlingAvatarClientFailed:
    """Kling: FAILED status raises AvatarQualityError."""

    @pytest.fixture
    def client(self, tmp_path):
        return KlingAvatarClient(
            fal_api_key="fal-key",
            avatar_image_url="https://example.com/avatar.jpg",
            output_dir=str(tmp_path / "avatar"),
        )

    @pytest.mark.asyncio
    async def test_failed_status_raises(self, client, tmp_path):
        output_path = str(tmp_path / "avatar" / "clip.mp4")

        submit_resp = _make_httpx_response(
            200,
            {
                "request_id": "req-002",
                "status_url": "https://queue.fal.run/.../requests/req-002/status",
            },
        )
        poll_failed = _make_httpx_response(
            200,
            {"status": "FAILED", "error": "model crash"},
        )

        mock_client_instance = AsyncMock()
        mock_client_instance.post = AsyncMock(return_value=submit_resp)
        mock_client_instance.get = AsyncMock(return_value=poll_failed)

        mock_async_client = MagicMock()
        mock_async_client.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_async_client.__aexit__ = AsyncMock(return_value=False)

        with patch("scripts.avatar_gen.kling_client.httpx.AsyncClient",
                   return_value=mock_async_client), \
             pytest.raises(AvatarQualityError, match="generation failed"):
            await client.generate("https://audio.url/clip.mp3", output_path)


# ─── Factory tests ─────────────────────────────────────────────────────────────

class TestMakeAvatarClient:
    """make_avatar_client routes to the correct backend."""

    def test_kling_provider_returns_kling_client(self, tmp_path):
        config = {
            "avatar_provider": "kling",
            "fal_api_key": "fal-key",
            "kling_avatar_image_url": "https://example.com/avatar.jpg",
            "output_dir": str(tmp_path / "avatar"),
        }
        client = make_avatar_client(config)
        assert isinstance(client, KlingAvatarClient)

    def test_heygen_provider_returns_heygen_client(self, tmp_path):
        config = {
            "avatar_provider": "heygen",
            "heygen_api_key": "hey-key",
            "heygen_avatar_id": "avatar-123",
            "output_dir": str(tmp_path / "avatar"),
        }
        client = make_avatar_client(config)
        assert isinstance(client, HeyGenAvatarClient)

    def test_unknown_provider_raises_value_error(self):
        config = {
            "avatar_provider": "dalle",
            "output_dir": "output/avatar",
        }
        with pytest.raises(ValueError, match="Unknown avatar_provider"):
            make_avatar_client(config)

    def test_default_provider_is_kling(self, tmp_path):
        """When avatar_provider is omitted, defaults to Kling."""
        config = {
            "fal_api_key": "fal-key",
            "kling_avatar_image_url": "https://example.com/avatar.jpg",
            "output_dir": str(tmp_path / "avatar"),
        }
        client = make_avatar_client(config)
        assert isinstance(client, KlingAvatarClient)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
