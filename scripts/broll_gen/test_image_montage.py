"""
Tests for ImageMontageGenerator.

Covers:
    1. test_pexels_happy_path         — Pexels key present, returns 4 photos, FFmpeg succeeds
    2. test_no_keys_falls_through_to_og_image — no API keys, OG image found in HTML
    3. test_all_sources_fail_raises   — all httpx calls raise HTTPError → BrollError("no images found")
    4. test_minimum_two_images_required — only 1 URL found, 1 downloaded → BrollError("too few images")
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from broll_gen.base import BrollError
from broll_gen.image_montage import ImageMontageGenerator


# ─── Minimal VideoJob stub ─────────────────────────────────────────────────────

@dataclass
class _VideoJob:
    topic: str
    url: str = ""
    script: str = ""
    broll_path: str = ""
    broll_type: str = ""
    needs_gpu_broll: bool = False


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _make_pexels_response(n: int = 4) -> dict:
    """Return a Pexels-style search JSON with n photos."""
    return {
        "photos": [
            {
                "id": i,
                "src": {
                    "landscape": f"https://images.pexels.com/photos/{i}/pexels-photo-{i}.jpeg",
                    "original": f"https://images.pexels.com/photos/{i}/original.jpg",
                },
            }
            for i in range(1, n + 1)
        ]
    }


def _fake_image_bytes() -> bytes:
    """Minimal 1×1 white JPEG bytes (valid enough for write_bytes)."""
    # Smallest valid JPEG
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f"
        b"\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xda\x00\x08\x01\x01"
        b"\x00\x00?\x00\xfb\xff\xd9"
    )


# ─── Mock httpx.AsyncClient context manager factory ───────────────────────────

class _MockResponse:
    """Configurable fake httpx.Response."""

    def __init__(self, json_data=None, content: bytes = b"", status_code: int = 200, text: str = ""):
        self._json = json_data
        self.content = content
        self.status_code = status_code
        self._text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=MagicMock(),
                response=MagicMock(status_code=self.status_code),
            )

    def json(self):
        return self._json

    @property
    def text(self):
        return self._text


def _make_client_mock(responses: list[_MockResponse]):
    """
    Build an AsyncMock that acts as `httpx.AsyncClient` context manager.

    Each successive call to `client.get(...)` returns the next response
    in the `responses` list (cycling if exhausted).
    """
    call_count = [0]

    async def _get(*args, **kwargs):
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        return responses[idx]

    client_instance = MagicMock()
    client_instance.get = _get
    client_instance.__aenter__ = AsyncMock(return_value=client_instance)
    client_instance.__aexit__ = AsyncMock(return_value=False)

    client_class = MagicMock(return_value=client_instance)
    return client_class, client_instance


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestPexelsHappyPath:
    """Pexels key present; 4 photos returned; FFmpeg succeeds → output path returned."""

    def test_pexels_happy_path(self, tmp_path):
        output_path = str(tmp_path / "out.mp4")
        job = _VideoJob(topic="artificial intelligence", url="https://example.com/article")

        pexels_resp = _MockResponse(json_data=_make_pexels_response(4))
        img_resp = _MockResponse(content=_fake_image_bytes())

        # All responses after the first (pexels search) are image downloads
        responses = [pexels_resp] + [img_resp] * 4

        mock_client_cls, _ = _make_client_mock(responses)

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with (
            patch("broll_gen.image_montage.httpx.AsyncClient", mock_client_cls),
            patch("broll_gen.image_montage.subprocess.run", return_value=mock_proc),
        ):
            gen = ImageMontageGenerator(pexels_api_key="test-pexels-key")
            result = asyncio.run(gen.generate(job, target_duration_s=20.0, output_path=output_path))

        assert result == output_path


class TestNoKeysFallsThroughToOgImage:
    """No API keys set; OG image found in article HTML; then download + FFmpeg succeed."""

    def test_no_keys_falls_through_to_og_image(self, tmp_path):
        output_path = str(tmp_path / "out.mp4")
        # HTML contains both og:image and twitter:image → 2 distinct URLs extracted
        og_html = (
            '<html><head>'
            '<meta property="og:image" content="https://example.com/img1.jpg">'
            '<meta name="twitter:image" content="https://example.com/img2.jpg">'
            '</head></html>'
        )

        # Response sequence (all use the same patched AsyncClient):
        #   [0] article HTML fetch (OG image extraction)
        #   [1] download img1.jpg
        #   [2] download img2.jpg
        html_resp = _MockResponse(text=og_html, content=og_html.encode())
        img_resp = _MockResponse(content=_fake_image_bytes())
        responses = [html_resp, img_resp, img_resp]

        mock_client_cls, _ = _make_client_mock(responses)

        mock_proc = MagicMock()
        mock_proc.returncode = 0

        job = _VideoJob(
            topic="AI breakthrough",
            url="https://example.com/ai-article",
        )

        with (
            patch("broll_gen.image_montage.httpx.AsyncClient", mock_client_cls),
            patch("broll_gen.image_montage.subprocess.run", return_value=mock_proc),
        ):
            gen = ImageMontageGenerator()  # no API keys
            result = asyncio.run(
                gen.generate(job, target_duration_s=12.0, output_path=output_path)
            )

        assert result == output_path


class TestAllSourcesFailRaises:
    """All httpx calls raise HTTPError → BrollError raised before any download attempt."""

    def test_all_sources_fail_raises(self, tmp_path):
        output_path = str(tmp_path / "out.mp4")
        job = _VideoJob(topic="quantum computing", url="https://example.com/article")

        async def _raising_get(*args, **kwargs):
            raise httpx.HTTPError("connection failed")

        client_instance = MagicMock()
        client_instance.get = _raising_get
        client_instance.__aenter__ = AsyncMock(return_value=client_instance)
        client_instance.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls = MagicMock(return_value=client_instance)

        with patch("broll_gen.image_montage.httpx.AsyncClient", mock_client_cls):
            gen = ImageMontageGenerator(
                pexels_api_key="key-present",
                bing_api_key="key-present",
            )
            with pytest.raises(BrollError, match="no images found"):
                asyncio.run(gen.generate(job, target_duration_s=20.0, output_path=output_path))


class TestMinimumTwoImagesRequired:
    """2 URLs found but only 1 downloads successfully → BrollError("too few images") raised."""

    def test_minimum_two_images_required(self, tmp_path):
        output_path = str(tmp_path / "out.mp4")
        # No article URL → OG fallback skipped; no Bing key; Pexels returns 2 photos
        # so the URL-count guard (< 2) is cleared.  The second download then fails,
        # leaving only 1 downloaded image → "too few images downloaded" error.
        job = _VideoJob(topic="robotics", url="")

        pexels_two = _MockResponse(
            json_data={
                "photos": [
                    {"id": 1, "src": {"landscape": "https://images.pexels.com/photos/1/img.jpg"}},
                    {"id": 2, "src": {"landscape": "https://images.pexels.com/photos/2/img.jpg"}},
                ]
            }
        )
        img_ok = _MockResponse(content=_fake_image_bytes())
        img_fail = _MockResponse(content=b"", status_code=404)  # will raise on raise_for_status

        # Sequence: [0] Pexels search → [1] download img 1 (ok) → [2] download img 2 (fail)
        responses = [pexels_two, img_ok, img_fail]
        mock_client_cls, _ = _make_client_mock(responses)

        with patch("broll_gen.image_montage.httpx.AsyncClient", mock_client_cls):
            gen = ImageMontageGenerator(pexels_api_key="test-key")
            with pytest.raises(BrollError, match="too few images"):
                asyncio.run(gen.generate(job, target_duration_s=20.0, output_path=output_path))
