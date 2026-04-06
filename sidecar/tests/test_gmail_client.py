"""Tests for sidecar.gmail_client."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


FAKE_TOKEN_JSON = json.dumps(
    {
        "token": "fake-access",
        "refresh_token": "fake-refresh",
        "client_id": "fake-client",
        "client_secret": "fake-secret",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
    }
)


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _message(
    msg_id: str,
    internal_date: int,
    subject: str = "TLDR AI",
    plain: str = "",
    html: str = "",
    date_hdr: str = "Sat, 05 Apr 2026 05:00:00 +0000",
) -> dict:
    parts = []
    if plain:
        parts.append(
            {"mimeType": "text/plain", "body": {"data": _b64url(plain)}}
        )
    if html:
        parts.append(
            {"mimeType": "text/html", "body": {"data": _b64url(html)}}
        )
    if not parts:
        parts = [{"mimeType": "text/plain", "body": {"data": _b64url("empty")}}]
    return {
        "id": msg_id,
        "internalDate": str(internal_date),
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date_hdr},
            ],
            "parts": parts,
        },
    }


def _fake_service(messages: list[dict]) -> MagicMock:
    """Build a fake Gmail service object."""
    service = MagicMock()
    list_resp = {"messages": [{"id": m["id"]} for m in messages]}

    by_id = {m["id"]: m for m in messages}

    users = service.users.return_value
    msgs = users.messages.return_value

    list_exec = MagicMock()
    list_exec.execute.return_value = list_resp
    msgs.list.return_value = list_exec

    def _get(userId, id, format):
        e = MagicMock()
        e.execute.return_value = by_id[id]
        return e

    msgs.get.side_effect = _get
    return service


@pytest.fixture
def mock_build():
    with patch("googleapiclient.discovery.build") as build_mock:
        yield build_mock


@pytest.fixture
def mock_creds():
    with patch("google.oauth2.credentials.Credentials") as creds_mock:
        creds_mock.return_value = MagicMock(name="creds")
        yield creds_mock


def test_fetch_latest_newsletter_returns_latest_match(mock_build, mock_creds):
    from sidecar.gmail_client import GmailClient

    messages = [
        _message("a", 1_000_000_000_000, plain="old A"),
        _message("b", 3_000_000_000_000, plain="newest B"),
        _message("c", 2_000_000_000_000, plain="middle C"),
    ]
    mock_build.return_value = _fake_service(messages)

    client = GmailClient(FAKE_TOKEN_JSON)
    result = client.fetch_latest_newsletter()

    assert result is not None
    assert result["message_id"] == "b"
    assert "newest B" in result["body_text"]


def test_fetch_latest_newsletter_returns_none_when_no_match(mock_build, mock_creds):
    from sidecar.gmail_client import GmailClient

    service = MagicMock()
    users = service.users.return_value
    msgs = users.messages.return_value
    list_exec = MagicMock()
    list_exec.execute.return_value = {"messages": []}
    msgs.list.return_value = list_exec
    mock_build.return_value = service

    client = GmailClient(FAKE_TOKEN_JSON)
    assert client.fetch_latest_newsletter() is None


def test_fetch_latest_newsletter_parses_plaintext_body(mock_build, mock_creds):
    from sidecar.gmail_client import GmailClient

    mock_build.return_value = _fake_service(
        [_message("x", 1, plain="Hello plain body with stories.")]
    )
    client = GmailClient(FAKE_TOKEN_JSON)
    result = client.fetch_latest_newsletter()
    assert result["body_text"].startswith("Hello plain body")
    assert result["subject"] == "TLDR AI"


def test_fetch_latest_newsletter_parses_html_body(mock_build, mock_creds):
    from sidecar.gmail_client import GmailClient

    html = "<html><body><p>Hello <b>HTML</b> body</p><p>Second line</p></body></html>"
    mock_build.return_value = _fake_service(
        [_message("y", 1, html=html)]
    )
    client = GmailClient(FAKE_TOKEN_JSON)
    result = client.fetch_latest_newsletter()
    text = result["body_text"]
    assert "Hello" in text and "HTML" in text and "Second line" in text
    assert "<" not in text and ">" not in text


def test_gmail_api_exception_propagates(mock_build, mock_creds):
    from sidecar.gmail_client import GmailClient

    service = MagicMock()
    users = service.users.return_value
    msgs = users.messages.return_value
    list_exec = MagicMock()
    list_exec.execute.side_effect = RuntimeError("API down")
    msgs.list.return_value = list_exec
    mock_build.return_value = service

    client = GmailClient(FAKE_TOKEN_JSON)
    with pytest.raises(RuntimeError, match="API down"):
        client.fetch_latest_newsletter()
