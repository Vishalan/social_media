"""Unit 8 SHELL — narrow Docker socket client."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sidecar.docker_manager import (  # noqa: E402
    DockerManager,
    DEFAULT_ALLOWLIST,
    SIDECAR_CONTAINER_NAME,
)


class _FakeResp:
    def __init__(self, status: int, body: bytes = b""):
        self.status = status
        self._body = body

    def read(self):
        return self._body


class _FakeConn:
    def __init__(self, status: int = 204, body: bytes = b"", raises: bool = False):
        self.status = status
        self.body = body
        self.raises = raises
        self.requests = []

    def request(self, method, path):
        if self.raises:
            raise OSError("docker socket exploded")
        self.requests.append((method, path))

    def getresponse(self):
        return _FakeResp(self.status, self.body)

    def close(self):
        pass


def _mgr_with_conn(fake_conn: _FakeConn) -> DockerManager:
    mgr = DockerManager(socket_path="/dev/null")
    mgr._open_connection = lambda: fake_conn  # type: ignore
    return mgr


def test_restart_allowed_container():
    fake = _FakeConn(status=204)
    mgr = _mgr_with_conn(fake)
    result = mgr.restart_containers(["postiz"])
    assert result["restarted"] == ["postiz"]
    assert result["rejected"] == []
    assert result["errors"] == []
    assert fake.requests == [("POST", "/v1.41/containers/postiz/restart")]


def test_restart_rejects_disallowed_container():
    fake = _FakeConn(status=204)
    mgr = _mgr_with_conn(fake)
    result = mgr.restart_containers(["commoncreed_sidecar"])
    assert result["restarted"] == []
    assert result["rejected"] == ["commoncreed_sidecar"]
    # Critical: the fake conn must NEVER have been asked
    assert fake.requests == []


def test_restart_handles_docker_error():
    fake = _FakeConn(status=500, body=b"boom")
    mgr = _mgr_with_conn(fake)
    result = mgr.restart_containers(["postiz"])
    assert result["restarted"] == []
    assert len(result["errors"]) == 1
    assert result["errors"][0]["name"] == "postiz"


def test_restart_rejects_arbitrary_container_name():
    fake = _FakeConn(status=204)
    mgr = _mgr_with_conn(fake)
    result = mgr.restart_containers(["totally-random-name-xyz"])
    assert result["restarted"] == []
    assert result["rejected"] == ["totally-random-name-xyz"]
    assert fake.requests == []


def test_allowlist_does_NOT_contain_sidecar_self():
    assert SIDECAR_CONTAINER_NAME not in DEFAULT_ALLOWLIST
    # And even if a caller tries to inject it via the constructor, the
    # manager strips it out.
    mgr = DockerManager(allowlist=("postiz", SIDECAR_CONTAINER_NAME))
    assert SIDECAR_CONTAINER_NAME not in mgr.allowlist
    assert not mgr.is_allowed(SIDECAR_CONTAINER_NAME)
