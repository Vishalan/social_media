"""Tests for PostizPoster and the make_poster factory."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from scripts.posting.postiz_poster import PostizPoster
from scripts.posting.social_poster import make_poster


# ---------- helpers ----------------------------------------------------------


def _make_response(status_code: int, json_body: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text or (json.dumps(json_body) if json_body is not None else "")
    resp.json.return_value = json_body or {}
    return resp


@pytest.fixture
def video_file(tmp_path: Path) -> Path:
    p = tmp_path / "video.mp4"
    p.write_bytes(b"fake-video-bytes")
    return p


@pytest.fixture
def thumb_file(tmp_path: Path) -> Path:
    p = tmp_path / "thumb.jpg"
    p.write_bytes(b"fake-jpeg-bytes")
    return p


@pytest.fixture
def poster() -> PostizPoster:
    return PostizPoster(base_url="http://postiz.local:5000", api_key="test-key")


# ---------- PostizPoster.post -------------------------------------------------


def test_happy_path_returns_json(poster, video_file, thumb_file):
    expected = {"id": "post-123", "status": "ok"}
    with patch("scripts.posting.postiz_poster.requests.post") as mock_post:
        mock_post.return_value = _make_response(200, expected)
        result = poster.post(
            video_path=video_file,
            caption="hello world",
            thumbnail_path=thumb_file,
            platforms=["youtube", "tiktok"],
        )
    assert result == expected
    assert mock_post.call_count == 1


def test_retries_on_500_then_succeeds(poster, video_file, thumb_file):
    expected = {"id": "post-9"}
    responses = [
        _make_response(500, text="boom1"),
        _make_response(500, text="boom2"),
        _make_response(200, expected),
    ]
    with patch("scripts.posting.postiz_poster.requests.post") as mock_post, patch(
        "scripts.posting.postiz_poster.time.sleep"
    ) as mock_sleep:
        mock_post.side_effect = responses
        result = poster.post(
            video_path=video_file,
            caption="cap",
            thumbnail_path=thumb_file,
            platforms=["x"],
        )
    assert result == expected
    assert mock_post.call_count == 3
    # Exponential backoff: 1s then 2s
    assert [c.args[0] for c in mock_sleep.call_args_list] == [1, 2]


def test_persistent_500_raises_after_3_attempts(poster, video_file, thumb_file):
    err_body = "internal kaboom"
    with patch("scripts.posting.postiz_poster.requests.post") as mock_post, patch(
        "scripts.posting.postiz_poster.time.sleep"
    ):
        mock_post.return_value = _make_response(500, text=err_body)
        with pytest.raises(requests.HTTPError) as exc_info:
            poster.post(
                video_path=video_file,
                caption="cap",
                thumbnail_path=thumb_file,
                platforms=["youtube"],
            )
    assert mock_post.call_count == 3
    assert err_body in str(exc_info.value)


def test_400_raises_immediately_no_retry(poster, video_file, thumb_file):
    err_body = "bad caption"
    with patch("scripts.posting.postiz_poster.requests.post") as mock_post, patch(
        "scripts.posting.postiz_poster.time.sleep"
    ) as mock_sleep:
        mock_post.return_value = _make_response(400, text=err_body)
        with pytest.raises(requests.HTTPError) as exc_info:
            poster.post(
                video_path=video_file,
                caption="cap",
                thumbnail_path=thumb_file,
                platforms=["youtube"],
            )
    assert mock_post.call_count == 1
    mock_sleep.assert_not_called()
    assert err_body in str(exc_info.value)


def test_thumbnail_none_raises_before_http(poster, video_file):
    with patch("scripts.posting.postiz_poster.requests.post") as mock_post:
        with pytest.raises(ValueError, match="thumbnail"):
            poster.post(
                video_path=video_file,
                caption="cap",
                thumbnail_path=None,
                platforms=["youtube"],
            )
    mock_post.assert_not_called()


def test_missing_video_raises_file_not_found(poster, tmp_path, thumb_file):
    missing = tmp_path / "nope.mp4"
    with patch("scripts.posting.postiz_poster.requests.post") as mock_post:
        with pytest.raises(FileNotFoundError):
            poster.post(
                video_path=missing,
                caption="cap",
                thumbnail_path=thumb_file,
                platforms=["youtube"],
            )
    mock_post.assert_not_called()


def test_multipart_payload_contains_video_caption_platforms(
    poster, video_file, thumb_file
):
    with patch("scripts.posting.postiz_poster.requests.post") as mock_post:
        mock_post.return_value = _make_response(200, {"ok": True})
        poster.post(
            video_path=video_file,
            caption="my caption",
            thumbnail_path=thumb_file,
            platforms=["youtube", "tiktok", "x"],
        )

    call = mock_post.call_args
    files = call.kwargs["files"]
    data = call.kwargs["data"]

    assert "video" in files
    assert "thumbnail" in files

    body = json.loads(data["payload"])
    assert body["caption"] == "my caption"
    platforms_in_body = [p["platform"] for p in body["platforms"]]
    assert platforms_in_body == ["youtube", "tiktok", "x"]

    # YouTube title is truncated to 100 chars (here it's short, but field present).
    yt = next(p for p in body["platforms"] if p["platform"] == "youtube")
    assert yt["title"] == "my caption"
    assert "thumbnail" in yt

    tt = next(p for p in body["platforms"] if p["platform"] == "tiktok")
    assert tt["videoCoverTimestampMs"] == 0

    x = next(p for p in body["platforms"] if p["platform"] == "x")
    assert x["text"] == "my caption"


# ---------- factory ----------------------------------------------------------


def test_factory_postiz_returns_postiz_poster(monkeypatch):
    monkeypatch.setenv("POSTING_BACKEND", "postiz")
    monkeypatch.setenv("POSTIZ_BASE_URL", "http://localhost:5000")
    monkeypatch.setenv("POSTIZ_API_KEY", "abc")
    p = make_poster()
    assert isinstance(p, PostizPoster)
    assert p.base_url == "http://localhost:5000"
    assert p.api_key == "abc"


def test_factory_postiz_missing_key_raises(monkeypatch):
    monkeypatch.setenv("POSTING_BACKEND", "postiz")
    monkeypatch.setenv("POSTIZ_BASE_URL", "http://localhost:5000")
    monkeypatch.delenv("POSTIZ_API_KEY", raising=False)
    with pytest.raises(ValueError, match="POSTIZ_API_KEY"):
        make_poster()


def test_factory_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("POSTING_BACKEND", "myspace")
    with pytest.raises(ValueError, match="myspace"):
        make_poster()
