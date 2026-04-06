"""
Gmail API client for the sidecar.

Wraps `googleapiclient.discovery.build('gmail', 'v1', ...)` to fetch the most
recent TLDR AI newsletter. Constructs Google credentials from an OAuth token
JSON string (refresh-token flow) so the sidecar can run headless.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from email.utils import parsedate_to_datetime
from typing import Optional

logger = logging.getLogger(__name__)


def _b64url_decode(data: str) -> bytes:
    if not data:
        return b""
    padding = 4 - (len(data) % 4)
    if padding and padding < 4:
        data = data + ("=" * padding)
    return base64.urlsafe_b64decode(data.encode("ascii"))


def _strip_html(html: str) -> str:
    # Remove script/style blocks first
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Replace <br> and block tags with newlines
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</(p|div|li|h[1-6]|tr)>", "\n", html, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _find_part(payload: dict, mime_type: str) -> Optional[dict]:
    """Depth-first search for the first part with the given mimeType."""
    if not payload:
        return None
    if payload.get("mimeType") == mime_type and payload.get("body", {}).get("data"):
        return payload
    for part in payload.get("parts", []) or []:
        found = _find_part(part, mime_type)
        if found:
            return found
    return None


def _extract_body(payload: dict) -> str:
    # Prefer text/plain; fall back to text/html stripped to text.
    plain = _find_part(payload, "text/plain")
    if plain:
        data = plain.get("body", {}).get("data", "")
        return _b64url_decode(data).decode("utf-8", errors="replace")
    html = _find_part(payload, "text/html")
    if html:
        data = html.get("body", {}).get("data", "")
        raw = _b64url_decode(data).decode("utf-8", errors="replace")
        return _strip_html(raw)
    # Single-part messages put the body directly on payload
    body_data = payload.get("body", {}).get("data", "")
    if body_data:
        raw = _b64url_decode(body_data).decode("utf-8", errors="replace")
        if payload.get("mimeType") == "text/html":
            return _strip_html(raw)
        return raw
    return ""


def _header(payload: dict, name: str) -> str:
    name_lower = name.lower()
    for h in payload.get("headers", []) or []:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "")
    return ""


class GmailClient:
    """Thin wrapper around the Gmail v1 API for TLDR newsletter fetches."""

    def __init__(self, oauth_token_json: str) -> None:
        """
        Args:
            oauth_token_json: JSON string containing OAuth token data with
                at minimum: client_id, client_secret, refresh_token. May also
                include token, token_uri, scopes.
        """
        # Imports are local so tests can patch googleapiclient.discovery.build
        # without requiring the package at import time.
        from google.oauth2.credentials import Credentials  # type: ignore
        from googleapiclient.discovery import build  # type: ignore

        data = json.loads(oauth_token_json)
        creds = Credentials(
            token=data.get("token"),
            refresh_token=data.get("refresh_token"),
            token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=data.get("client_id"),
            client_secret=data.get("client_secret"),
            scopes=data.get("scopes") or ["https://www.googleapis.com/auth/gmail.readonly"],
        )
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    def fetch_latest_newsletter(
        self,
        sender: str = "dan@tldrnewsletter.com",
        max_age_hours: int = 24,
    ) -> Optional[dict]:
        """Fetch the most recent newsletter from `sender` within `max_age_hours`.

        Returns a dict with keys: message_id, received_at (ISO string),
        subject, body_text — or None if no match.
        """
        days = max_age_hours // 24 + 1
        query = f"from:{sender} newer_than:{days}d"
        users = self._service.users()
        list_resp = users.messages().list(userId="me", q=query, maxResults=10).execute()
        messages = list_resp.get("messages", []) or []
        if not messages:
            return None

        fetched = []
        for m in messages:
            full = users.messages().get(userId="me", id=m["id"], format="full").execute()
            fetched.append(full)

        def _ts(msg: dict) -> int:
            # internalDate is ms since epoch as a string
            try:
                return int(msg.get("internalDate", "0"))
            except (TypeError, ValueError):
                return 0

        fetched.sort(key=_ts, reverse=True)
        latest = fetched[0]

        payload = latest.get("payload", {}) or {}
        subject = _header(payload, "Subject")
        date_hdr = _header(payload, "Date")
        received_at = ""
        if date_hdr:
            try:
                received_at = parsedate_to_datetime(date_hdr).isoformat()
            except (TypeError, ValueError):
                received_at = date_hdr
        body_text = _extract_body(payload)

        return {
            "message_id": latest.get("id", ""),
            "received_at": received_at,
            "subject": subject,
            "body_text": body_text,
        }
