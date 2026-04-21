"""Tests for :class:`FalFluxClient` (Unit 9).

Mocks ``httpx.AsyncClient`` so no live fal.ai requests are made.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from still_gen.flux_client import (
    FalFluxClient,
    FluxGenerationError,
    FluxResult,
)


class _MockAsyncResponse:
    def __init__(self, *, status_code: int = 200, json_body=None, content: bytes = b""):
        self.status_code = status_code
        self._json = json_body or {}
        self._content = content
        self.text = str(json_body) if json_body else ""

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=None, response=MagicMock(status_code=self.status_code),
            )


class _MockStream:
    """Mimics httpx.AsyncClient.stream() async context manager."""

    def __init__(self, content: bytes):
        self._content = content

    async def __aenter__(self):
        resp = _MockAsyncResponse(content=self._content)

        async def _aiter(chunk_size: int = 65536):
            for i in range(0, len(self._content), chunk_size):
                yield self._content[i:i + chunk_size]

        resp.aiter_bytes = _aiter
        return resp

    async def __aexit__(self, *args):
        return False


def _make_async_client_mock(handlers: dict):
    """Build an ``httpx.AsyncClient``-shaped context manager whose methods
    dispatch to ``handlers[(method, url_contains)]``."""

    async def _handle(method: str, url: str, json_body=None):
        for (m, pattern), value in handlers.items():
            if m == method and pattern in url:
                if callable(value):
                    return value(url=url, json_body=json_body)
                return value
        raise AssertionError(f"no mock for {method} {url}")

    async_client = MagicMock()

    async def _post(url, json=None, headers=None):
        return await _handle("POST", url, json_body=json)

    async def _get(url, headers=None):
        return await _handle("GET", url)

    def _stream(method, url):
        for (m, pattern), value in handlers.items():
            if m == method and pattern in url:
                if isinstance(value, bytes):
                    return _MockStream(value)
        raise AssertionError(f"no stream mock for {method} {url}")

    async_client.post = AsyncMock(side_effect=_post)
    async_client.get = AsyncMock(side_effect=_get)
    async_client.stream = _stream

    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=async_client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return lambda *a, **kw: cm


class FluxClientConstructionTests(unittest.TestCase):
    def test_empty_api_key_rejected(self):
        with self.assertRaises(ValueError):
            FalFluxClient(fal_api_key="", endpoint="fal-ai/flux/dev")


class FluxClientHappyPathTests(unittest.TestCase):
    def test_generate_submit_poll_download(self):
        tmp = tempfile.mkdtemp(prefix="flux-test-")
        out = os.path.join(tmp, "still.png")

        submit_resp = _MockAsyncResponse(
            status_code=200,
            json_body={
                "request_id": "req-123",
                "status_url": "https://queue.fal.run/test/requests/req-123/status",
            },
        )
        status_resp_completed = _MockAsyncResponse(
            status_code=200,
            json_body={
                "status": "COMPLETED",
                "images": [{"url": "https://fal.cdn/image-123.png", "width": 1080, "height": 1920}],
            },
        )
        handlers = {
            ("POST", "queue.fal.run"): submit_resp,
            ("GET", "/status"): status_resp_completed,
            ("GET", "/image-123.png"): b"\x89PNG\r\n\x1a\n" + b"\x00" * 128,
        }
        factory = _make_async_client_mock(handlers)

        with patch("still_gen.flux_client.httpx.AsyncClient", factory):
            client = FalFluxClient(
                fal_api_key="test-key",
                endpoint="fal-ai/flux/dev",
                output_dir=tmp,
            )
            result = asyncio.run(client.generate(
                prompt="test prompt", output_path=out,
            ))

        self.assertIsInstance(result, FluxResult)
        self.assertTrue(Path(out).exists())
        self.assertGreater(Path(out).stat().st_size, 0)
        self.assertEqual(result.width, 1080)
        self.assertEqual(result.height, 1920)


class FluxClientErrorPathsTests(unittest.TestCase):
    def test_submit_non_2xx_raises(self):
        submit_resp = _MockAsyncResponse(status_code=500, json_body={"error": "fal down"})
        handlers = {("POST", "queue.fal.run"): submit_resp}
        factory = _make_async_client_mock(handlers)

        with patch("still_gen.flux_client.httpx.AsyncClient", factory):
            client = FalFluxClient(fal_api_key="test", endpoint="fal-ai/flux/dev")
            with self.assertRaises(FluxGenerationError):
                asyncio.run(client.generate(prompt="x", output_path="/tmp/x.png"))

    def test_failed_status_raises(self):
        submit_resp = _MockAsyncResponse(
            status_code=200,
            json_body={"request_id": "r", "status_url": "https://queue.fal.run/status"},
        )
        failed_resp = _MockAsyncResponse(
            status_code=200,
            json_body={"status": "FAILED", "error": "nsfw trigger"},
        )
        handlers = {
            ("POST", "queue.fal.run"): submit_resp,
            ("GET", "/status"): failed_resp,
        }
        factory = _make_async_client_mock(handlers)

        with patch("still_gen.flux_client.httpx.AsyncClient", factory):
            client = FalFluxClient(fal_api_key="test", endpoint="fal-ai/flux/dev")
            with self.assertRaises(FluxGenerationError) as ctx:
                asyncio.run(client.generate(prompt="x", output_path="/tmp/x.png"))
            self.assertIn("nsfw trigger", str(ctx.exception))


class FluxClientExtractImageUrlTests(unittest.TestCase):
    """Multiple fal.ai response shapes are supported."""

    def test_images_array_shape(self):
        url_wh = FalFluxClient._extract_image_url(
            {"images": [{"url": "https://x", "width": 10, "height": 20}]}
        )
        self.assertEqual(url_wh, ("https://x", 10, 20))

    def test_output_wrapped_shape(self):
        url_wh = FalFluxClient._extract_image_url(
            {"output": {"images": [{"url": "https://y", "width": 5, "height": 8}]}}
        )
        self.assertEqual(url_wh, ("https://y", 5, 8))

    def test_flat_image_shape(self):
        url_wh = FalFluxClient._extract_image_url(
            {"image": {"url": "https://z", "width": 3, "height": 4}}
        )
        self.assertEqual(url_wh, ("https://z", 3, 4))

    def test_empty_returns_none(self):
        self.assertIsNone(FalFluxClient._extract_image_url({"images": []}))
        self.assertIsNone(FalFluxClient._extract_image_url({}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
