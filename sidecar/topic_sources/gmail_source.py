"""
Gmail topic source — fetches the most recent TLDR AI newsletter and runs
it through Claude to extract structured story items.

This is the original CommonCreed source. Existed as inlined logic inside
jobs/daily_trigger.py before the topic_sources abstraction — this file
is the lift-and-move with no behaviour changes.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..gmail_client import GmailClient
from ..topic_selector import extract_items

logger = logging.getLogger(__name__)


class GmailTopicSource:
    name = "gmail"

    def is_configured(self, settings: Any) -> bool:
        oauth_path = getattr(settings, "GMAIL_OAUTH_PATH", "") or ""
        if not oauth_path:
            return False
        try:
            return Path(oauth_path).exists()
        except Exception:
            return False

    def fetch_items(self, settings: Any) -> tuple[list[dict], str]:
        oauth_path = getattr(settings, "GMAIL_OAUTH_PATH", "") or ""
        try:
            oauth_json = Path(oauth_path).read_text()
        except Exception as exc:
            logger.warning("gmail source: cannot read OAuth token: %s", exc)
            return [], ""

        try:
            gmail = GmailClient(oauth_json)
            newsletter = gmail.fetch_latest_newsletter()
        except Exception as exc:
            logger.warning(
                "gmail source: fetch_latest_newsletter failed: %s", exc
            )
            return [], ""

        if newsletter is None:
            logger.info("gmail source: no newsletter within 24h")
            return [], ""

        body_text = (newsletter.get("body_text") or "").strip()
        label = (newsletter.get("received_at") or "").strip() or "gmail"
        if not body_text:
            logger.info("gmail source: empty newsletter body")
            return [], label

        try:
            items = extract_items(body_text)
        except Exception as exc:
            logger.warning("gmail source: extract_items failed: %s", exc)
            return [], label

        # Stamp the source so scoring + later analytics can tell which
        # source each candidate came from, even when sources are mixed.
        for it in items:
            it.setdefault("source", self.name)

        return items, label
