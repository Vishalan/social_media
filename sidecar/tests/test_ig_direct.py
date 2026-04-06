"""Unit 7 — IGDirectClient tests. All HTTP mocked."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar.ig_direct import IGDirectClient, GRAPH_API_VERSION  # noqa: E402


def _resp(status, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json = MagicMock(return_value=payload or {})
    r.raise_for_status = MagicMock()
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    return r


def test_graph_api_version_is_v20():
    assert GRAPH_API_VERSION == "v20.0"


# --- verify_collab ----------------------------------------------------------

def test_verify_collab_present():
    c = IGDirectClient("token")
    payload = {"id": "m1", "collaborators": {"data": [{"username": "vishalan.ai"}]}}
    with patch("sidecar.ig_direct.requests.get", return_value=_resp(200, payload)):
        assert c.verify_collab("m1", "vishalan.ai") is True


def test_verify_collab_present_case_insensitive():
    c = IGDirectClient("token")
    payload = {"collaborators": {"data": [{"username": "Vishalan.AI"}]}}
    with patch("sidecar.ig_direct.requests.get", return_value=_resp(200, payload)):
        assert c.verify_collab("m1", "@vishalan.ai") is True


def test_verify_collab_absent():
    c = IGDirectClient("token")
    payload = {"collaborators": {"data": [{"username": "someone_else"}]}}
    with patch("sidecar.ig_direct.requests.get", return_value=_resp(200, payload)):
        assert c.verify_collab("m1", "vishalan.ai") is False


def test_verify_collab_no_collaborators_field():
    c = IGDirectClient("token")
    with patch("sidecar.ig_direct.requests.get", return_value=_resp(200, {"id": "x"})):
        assert c.verify_collab("m1", "vishalan.ai") is False


def test_verify_collab_http_error_bubbles():
    c = IGDirectClient("token")
    with patch("sidecar.ig_direct.requests.get", return_value=_resp(500)):
        with pytest.raises(requests.HTTPError):
            c.verify_collab("m1", "vishalan.ai")


# --- add_collab_by_edit -----------------------------------------------------

def test_add_collab_by_edit_success():
    c = IGDirectClient("token")
    with patch(
        "sidecar.ig_direct.requests.post",
        return_value=_resp(200, {"success": True}),
    ):
        out = c.add_collab_by_edit("m1", "uid")
    assert out == {"success": True}


def test_add_collab_by_edit_unsupported_returns_none():
    c = IGDirectClient("token")
    with patch(
        "sidecar.ig_direct.requests.post",
        return_value=_resp(400, text="not allowed"),
    ):
        out = c.add_collab_by_edit("m1", "uid")
    assert out is None


def test_add_collab_by_edit_network_error_returns_none():
    c = IGDirectClient("token")
    with patch(
        "sidecar.ig_direct.requests.post",
        side_effect=requests.ConnectionError("nope"),
    ):
        out = c.add_collab_by_edit("m1", "uid")
    assert out is None


# --- add_collab_by_recreate ------------------------------------------------

def test_add_collab_by_recreate_success():
    c = IGDirectClient("token")
    create = _resp(200, {"id": "container1"})
    publish = _resp(200, {"id": "media2"}, text='{"id":"media2"}')
    with patch(
        "sidecar.ig_direct.requests.post", side_effect=[create, publish]
    ):
        out = c.add_collab_by_recreate("iguid", "http://v", "cap", ["uid1"])
    assert out["ok"] is True
    assert out["container_id"] == "container1"
    assert out["media"]["id"] == "media2"


def test_add_collab_by_recreate_create_fails():
    c = IGDirectClient("token")
    with patch(
        "sidecar.ig_direct.requests.post",
        side_effect=[_resp(400, text="bad")],
    ):
        out = c.add_collab_by_recreate("iguid", "http://v", "cap", ["uid"])
    assert out["ok"] is False
    assert out["stage"] == "create"


def test_add_collab_by_recreate_publish_fails():
    c = IGDirectClient("token")
    create = _resp(200, {"id": "c1"})
    publish = _resp(500, text="oops")
    with patch(
        "sidecar.ig_direct.requests.post", side_effect=[create, publish]
    ):
        out = c.add_collab_by_recreate("iguid", "http://v", "cap", ["uid"])
    assert out["ok"] is False
    assert out["stage"] == "publish"


def test_add_collab_by_recreate_network_error():
    c = IGDirectClient("token")
    with patch(
        "sidecar.ig_direct.requests.post",
        side_effect=requests.ConnectionError("dead"),
    ):
        out = c.add_collab_by_recreate("iguid", "http://v", "cap", ["uid"])
    assert out["ok"] is False
    assert out["stage"] == "network"
