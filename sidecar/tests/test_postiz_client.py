"""Unit 7 — PostizClient tests. All HTTP mocked."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar.postiz_client import PostizClient, make_client_from_settings  # noqa: E402


@pytest.fixture
def files(tmp_path):
    v = tmp_path / "v.mp4"
    v.write_bytes(b"video-bytes")
    t = tmp_path / "t.jpg"
    t.write_bytes(b"thumb-bytes")
    return str(v), str(t)


def _mock_response(status, json_payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json = MagicMock(return_value=json_payload or {})
    return r


def test_publish_post_happy_path(files):
    v, t = files
    client = PostizClient("http://postiz", "key123")
    resp = _mock_response(200, {"posts": [{"platform": "instagram", "id": "ig_1"}]})
    with patch("sidecar.postiz_client.requests.post", return_value=resp) as p:
        out = client.publish_post(
            video_path=v,
            thumbnail_path=t,
            ig_caption="hello",
            yt_title="title",
            yt_description="desc",
            ig_collab_usernames=["vishalan.ai"],
            scheduled_slot=datetime(2026, 4, 6, 19, 0),
        )
    assert out["posts"][0]["id"] == "ig_1"
    p.assert_called_once()
    args, kwargs = p.call_args
    assert kwargs["headers"]["Authorization"] == "key123"


def test_publish_post_4xx_raises_immediately(files):
    v, t = files
    client = PostizClient("http://postiz", "key")
    resp = _mock_response(400, text="bad req")
    with patch("sidecar.postiz_client.requests.post", return_value=resp) as p:
        with pytest.raises(requests.HTTPError):
            client.publish_post(
                v, t, "c", "y", "d", [], datetime(2026, 4, 6)
            )
    assert p.call_count == 1


def test_publish_post_5xx_retries_then_raises(files):
    v, t = files
    client = PostizClient("http://postiz", "key")
    resp = _mock_response(503, text="down")
    with patch("sidecar.postiz_client.requests.post", return_value=resp) as p, \
            patch("sidecar.postiz_client.time.sleep"):
        with pytest.raises(requests.HTTPError):
            client.publish_post(v, t, "c", "y", "d", [], datetime(2026, 4, 6))
    assert p.call_count == 3


def test_publish_post_5xx_then_success(files):
    v, t = files
    client = PostizClient("http://postiz", "key")
    bad = _mock_response(500, text="oops")
    good = _mock_response(200, {"ok": True})
    with patch(
        "sidecar.postiz_client.requests.post", side_effect=[bad, good]
    ) as p, patch("sidecar.postiz_client.time.sleep"):
        out = client.publish_post(v, t, "c", "y", "d", [], datetime(2026, 4, 6))
    assert out == {"ok": True}
    assert p.call_count == 2


def test_publish_post_network_exception_retries(files):
    v, t = files
    client = PostizClient("http://postiz", "key")
    with patch(
        "sidecar.postiz_client.requests.post",
        side_effect=requests.ConnectionError("dead"),
    ) as p, patch("sidecar.postiz_client.time.sleep"):
        with pytest.raises(requests.ConnectionError):
            client.publish_post(v, t, "c", "y", "d", [], datetime(2026, 4, 6))
    assert p.call_count == 3


def test_get_account_tokens_admin_api_success():
    client = PostizClient("http://postiz", "key")
    payload = [
        {"id": "abc", "platform": "instagram", "token": "tk", "providerIdentifier": "iguid"},
        {"id": "def", "platform": "youtube", "token": "yt"},
    ]
    resp = _mock_response(200, payload)
    with patch("sidecar.postiz_client.requests.get", return_value=resp):
        out = client.get_account_tokens()
    assert out["instagram"]["abc"]["access_token"] == "tk"
    assert out["instagram"]["abc"]["user_id"] == "iguid"


def test_get_account_tokens_falls_back_when_admin_api_4xx(monkeypatch):
    client = PostizClient("http://postiz", "key")
    resp = _mock_response(404, text="nope")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with patch("sidecar.postiz_client.requests.get", return_value=resp):
        out = client.get_account_tokens()
    # No DB url -> empty
    assert out == {"instagram": {}}


def test_get_account_tokens_postgres_fallback(monkeypatch):
    client = PostizClient("http://postiz", "key")
    monkeypatch.setenv("DATABASE_URL", "postgres://fake")
    resp = _mock_response(500, text="boom")

    fake_psyco = MagicMock()
    fake_conn = MagicMock()
    fake_cursor = MagicMock()
    fake_cursor.fetchall.return_value = [("id1", "tok1", "uid1")]
    fake_conn.cursor.return_value = fake_cursor
    fake_psyco.connect.return_value = fake_conn

    import sys as _sys
    monkeypatch.setitem(_sys.modules, "psycopg2", fake_psyco)

    with patch("sidecar.postiz_client.requests.get", return_value=resp):
        out = client.get_account_tokens()
    assert out["instagram"]["id1"]["access_token"] == "tok1"
    assert out["instagram"]["id1"]["user_id"] == "uid1"


def test_make_client_from_settings():
    import types

    s = types.SimpleNamespace(POSTIZ_BASE_URL="http://x", POSTIZ_API_KEY="k")
    c = make_client_from_settings(s)
    assert c.base_url == "http://x"
    assert c.api_key == "k"
