"""
Postiz REST client for the sidecar (Unit 7).

A purpose-built thin wrapper around the Postiz public REST API for the
end-to-end pipeline. We chose to build this fresh inside the sidecar
(rather than reuse ``scripts/posting/postiz_poster.py``) for cleaner
separation: the sidecar's posting needs are different (multipart with
thumbnail, IG collab usernames, scheduled-slot field, dual platform
payload), and reusing the scripts module would couple the sidecar to the
script package's mount point and per-platform conventions.

All HTTP errors are surfaced cleanly:
  - 5xx -> retry twice with exponential backoff (1s, 2s) -> raise
  - 4xx -> raise immediately, no retry
  - network exception -> retry on the same schedule, then re-raise
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


POSTIZ_POSTS_PATH = "/public/v1/posts"
POSTIZ_ACCOUNTS_PATH = "/public/v1/integrations"


class PostizClient:
    """Thin wrapper around the Postiz REST API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.timeout = timeout

    # ------------------------------------------------------------------
    # publish_post
    # ------------------------------------------------------------------
    def publish_post(
        self,
        video_path: str,
        thumbnail_path: str,
        ig_caption: str,
        yt_title: str,
        yt_description: str,
        ig_collab_usernames: list[str],
        scheduled_slot: datetime,
    ) -> dict:
        """Publish a video to Instagram + YouTube via Postiz.

        Returns the parsed JSON response from Postiz on success. Raises
        ``requests.HTTPError`` on persistent failure (5xx after retries) or
        immediately on 4xx.
        """
        url = f"{self.base_url}{POSTIZ_POSTS_PATH}"
        headers = {"Authorization": self.api_key}

        platforms_payload: list[dict[str, Any]] = [
            {
                "platform": "instagram",
                "caption": ig_caption,
                "collaborators": list(ig_collab_usernames or []),
                "coverUrl": Path(thumbnail_path).name,
            },
            {
                "platform": "youtube",
                "title": yt_title[:100],
                "description": yt_description,
                "thumbnail": Path(thumbnail_path).name,
            },
        ]
        body = {
            "scheduledFor": scheduled_slot.isoformat() if scheduled_slot else None,
            "platforms": platforms_payload,
        }

        max_attempts = 3
        backoff = [1, 2]
        last_exc: Optional[Exception] = None

        for attempt in range(max_attempts):
            try:
                with open(video_path, "rb") as vf, open(thumbnail_path, "rb") as tf:
                    files = {
                        "video": (Path(video_path).name, vf, "video/mp4"),
                        "thumbnail": (Path(thumbnail_path).name, tf, "image/jpeg"),
                    }
                    data = {"payload": json.dumps(body)}
                    logger.info(
                        "Postiz publish_post attempt %d/%d -> %s",
                        attempt + 1,
                        max_attempts,
                        url,
                    )
                    resp = requests.post(
                        url,
                        headers=headers,
                        files=files,
                        data=data,
                        timeout=self.timeout,
                    )
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("Postiz request error (attempt %d): %s", attempt + 1, exc)
                if attempt < max_attempts - 1:
                    time.sleep(backoff[attempt])
                    continue
                raise

            status = resp.status_code
            if 200 <= status < 300:
                try:
                    return resp.json()
                except ValueError:
                    return {"raw": resp.text}

            if 400 <= status < 500:
                raise requests.HTTPError(
                    f"Postiz 4xx {status}: {resp.text}", response=resp
                )

            # 5xx
            logger.warning(
                "Postiz 5xx %d on attempt %d/%d", status, attempt + 1, max_attempts
            )
            if attempt < max_attempts - 1:
                time.sleep(backoff[attempt])
                continue
            raise requests.HTTPError(
                f"Postiz 5xx {status} after {max_attempts} attempts: {resp.text}",
                response=resp,
            )

        if last_exc:
            raise last_exc
        raise RuntimeError("PostizClient.publish_post exited retry loop unexpectedly")

    # ------------------------------------------------------------------
    # get_account_tokens
    # ------------------------------------------------------------------
    def get_account_tokens(self) -> dict:
        """Read connected-platform IG access tokens from Postiz.

        Tries the admin/integrations REST endpoint first. If that returns
        4xx (Postiz doesn't expose tokens via REST in many builds), falls
        back to reading the Postiz Postgres DB directly using ``DATABASE_URL``
        from the environment.

        Returns a dict shaped like::

            {"instagram": {"<account_id>": {"access_token": "...", "user_id": "..."}}}
        """
        # --- attempt 1: admin REST API ---
        try:
            url = f"{self.base_url}{POSTIZ_ACCOUNTS_PATH}"
            resp = requests.get(
                url,
                headers={"Authorization": self.api_key},
                timeout=self.timeout,
            )
            if 200 <= resp.status_code < 300:
                return self._normalize_token_payload(resp.json())
            logger.info(
                "Postiz integrations endpoint returned %d, falling back to DB",
                resp.status_code,
            )
        except requests.RequestException as exc:
            logger.info("Postiz integrations endpoint failed (%s), falling back to DB", exc)

        # --- attempt 2: Postgres direct ---
        return self._read_tokens_from_postgres()

    @staticmethod
    def _normalize_token_payload(payload: Any) -> dict:
        """Coerce a variety of Postiz response shapes into our flat dict."""
        out: dict = {"instagram": {}}
        items = payload if isinstance(payload, list) else payload.get("items", [])
        for item in items or []:
            if not isinstance(item, dict):
                continue
            platform = (item.get("platform") or item.get("provider") or "").lower()
            if platform != "instagram":
                continue
            acct_id = str(item.get("id") or item.get("internalId") or "")
            out["instagram"][acct_id] = {
                "access_token": item.get("token") or item.get("accessToken") or "",
                "user_id": item.get("providerIdentifier")
                or item.get("igUserId")
                or "",
            }
        return out

    def _read_tokens_from_postgres(self) -> dict:
        """Last-resort fallback: read tokens from the Postiz Postgres DB."""
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            logger.warning(
                "PostizClient: no DATABASE_URL env var set; cannot fall back to Postgres"
            )
            return {"instagram": {}}
        try:
            import psycopg2  # type: ignore
        except ImportError:
            logger.warning("psycopg2 not installed; Postgres fallback unavailable")
            return {"instagram": {}}

        try:
            conn = psycopg2.connect(db_url)
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, token, \"providerIdentifier\" "
                    "FROM \"Integration\" WHERE provider = 'instagram'"
                )
                rows = cur.fetchall() or []
                out: dict = {"instagram": {}}
                for row in rows:
                    out["instagram"][str(row[0])] = {
                        "access_token": row[1] or "",
                        "user_id": row[2] or "",
                    }
                return out
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("Postiz Postgres fallback failed: %s", exc)
            return {"instagram": {}}


def make_client_from_settings(settings) -> PostizClient:
    """Build a PostizClient from a sidecar Settings instance."""
    return PostizClient(
        base_url=getattr(settings, "POSTIZ_BASE_URL", "") or "",
        api_key=getattr(settings, "POSTIZ_API_KEY", "") or "",
    )
