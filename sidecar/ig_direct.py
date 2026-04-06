"""
Direct Instagram Graph API client (Unit 7).

The plan mandates a publish-then-VERIFY-then-fallback approach for IG
Collab tagging: after Postiz reports success, the sidecar reads back the
collaborators field from the IG Graph API. If our expected collaborator
isn't there, we attempt to repair via:
  1) edit-the-existing-media (rarely supported)
  2) recreate-the-media (the nuclear option)

Graph API version: ``v20.0`` — current as of April 2026 and the latest
stable release that supports the ``collaborators`` field on media objects.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


GRAPH_API_VERSION = "v20.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class IGDirectClient:
    """Thin Graph API client for collab verification + repair."""

    def __init__(self, access_token: str, timeout: float = 20.0) -> None:
        self.access_token = access_token or ""
        self.timeout = timeout

    # ------------------------------------------------------------------
    # verify_collab
    # ------------------------------------------------------------------
    def verify_collab(
        self, ig_media_id: str, expected_collaborator_username: str
    ) -> bool:
        """Return True if ``expected_collaborator_username`` is on the media."""
        url = f"{GRAPH_BASE}/{ig_media_id}"
        params = {
            "fields": "id,collaborators{username}",
            "access_token": self.access_token,
        }
        resp = requests.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json() or {}
        collaborators = (data.get("collaborators") or {}).get("data") or []
        target = (expected_collaborator_username or "").lstrip("@").lower()
        for c in collaborators:
            uname = (c.get("username") or "").lstrip("@").lower()
            if uname == target:
                return True
        return False

    # ------------------------------------------------------------------
    # add_collab_by_edit
    # ------------------------------------------------------------------
    def add_collab_by_edit(
        self, ig_media_id: str, collaborator_ig_user_id: str
    ) -> Optional[dict]:
        """Attempt to edit an existing media to add a collaborator.

        Many account types do NOT support editing collaborators after
        publish. We treat any failure here as "unsupported" and return None
        rather than raising — the caller will fall through to the recreate
        path.
        """
        url = f"{GRAPH_BASE}/{ig_media_id}"
        try:
            resp = requests.post(
                url,
                data={
                    "collaborators": collaborator_ig_user_id,
                    "access_token": self.access_token,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.info("IG add_collab_by_edit network error: %s", exc)
            return None

        if 200 <= resp.status_code < 300:
            try:
                return resp.json()
            except ValueError:
                return {"raw": resp.text}

        logger.info(
            "IG add_collab_by_edit returned %d: %s", resp.status_code, resp.text
        )
        return None

    # ------------------------------------------------------------------
    # add_collab_by_recreate
    # ------------------------------------------------------------------
    def add_collab_by_recreate(
        self,
        ig_user_id: str,
        video_url: str,
        caption: str,
        collaborator_ig_user_ids: list[str],
    ) -> dict:
        """Create a new IG media with collaborators set from the start.

        Two-step Graph API flow:
          1) POST /{ig-user-id}/media       (creates a container)
          2) POST /{ig-user-id}/media_publish

        Returns a structured dict — never raises out for HTTP errors.
        """
        try:
            create_url = f"{GRAPH_BASE}/{ig_user_id}/media"
            create_resp = requests.post(
                create_url,
                data={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": caption,
                    "collaborators": ",".join(collaborator_ig_user_ids or []),
                    "access_token": self.access_token,
                },
                timeout=self.timeout,
            )
            if not (200 <= create_resp.status_code < 300):
                return {
                    "ok": False,
                    "stage": "create",
                    "status": create_resp.status_code,
                    "body": create_resp.text,
                }
            container_id = (create_resp.json() or {}).get("id")
            if not container_id:
                return {
                    "ok": False,
                    "stage": "create",
                    "error": "missing container id",
                }

            publish_url = f"{GRAPH_BASE}/{ig_user_id}/media_publish"
            publish_resp = requests.post(
                publish_url,
                data={
                    "creation_id": container_id,
                    "access_token": self.access_token,
                },
                timeout=self.timeout,
            )
            if not (200 <= publish_resp.status_code < 300):
                return {
                    "ok": False,
                    "stage": "publish",
                    "status": publish_resp.status_code,
                    "body": publish_resp.text,
                    "container_id": container_id,
                }
            return {
                "ok": True,
                "container_id": container_id,
                "media": publish_resp.json() if publish_resp.text else {},
            }
        except requests.RequestException as exc:
            logger.warning("IG add_collab_by_recreate network error: %s", exc)
            return {"ok": False, "stage": "network", "error": str(exc)}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("IG add_collab_by_recreate unexpected: %s", exc)
            return {"ok": False, "stage": "unexpected", "error": str(exc)}
