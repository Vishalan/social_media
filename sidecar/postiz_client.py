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
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


POSTIZ_POSTS_PATH = "/api/public/v1/posts"
POSTIZ_ACCOUNTS_PATH = "/api/public/v1/integrations"
POSTIZ_UPLOAD_PATH = "/api/public/v1/upload"

# Postiz integration identifier strings as returned by GET /integrations.
PROVIDER_INSTAGRAM = "instagram"
PROVIDER_YOUTUBE = "youtube"


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
    # _request_json — small helper for the JSON endpoints
    # ------------------------------------------------------------------
    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        files: Optional[dict] = None,
        data: Optional[dict] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": self.api_key}
        if json_body is not None and files is None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(json_body).encode()
        else:
            body = None

        max_attempts = 3
        backoff = [1, 2]
        for attempt in range(max_attempts):
            try:
                if files is not None:
                    resp = requests.request(
                        method,
                        url,
                        headers=headers,
                        files=files,
                        data=data,
                        timeout=self.timeout,
                    )
                else:
                    resp = requests.request(
                        method,
                        url,
                        headers=headers,
                        data=body,
                        timeout=self.timeout,
                    )
            except requests.RequestException as exc:
                logger.warning("Postiz %s %s network error (attempt %d): %s",
                               method, path, attempt + 1, exc)
                if attempt < max_attempts - 1:
                    time.sleep(backoff[attempt])
                    continue
                raise

            if 200 <= resp.status_code < 300:
                try:
                    return resp.json()
                except ValueError:
                    return {"raw": resp.text}
            if 400 <= resp.status_code < 500:
                raise requests.HTTPError(
                    f"Postiz 4xx {resp.status_code}: {resp.text}",
                    response=resp,
                )
            logger.warning("Postiz %s %s 5xx %d (attempt %d)",
                           method, path, resp.status_code, attempt + 1)
            if attempt < max_attempts - 1:
                time.sleep(backoff[attempt])
                continue
            raise requests.HTTPError(
                f"Postiz 5xx {resp.status_code} after {max_attempts} attempts: {resp.text}",
                response=resp,
            )
        raise RuntimeError("Postiz request exited retry loop unexpectedly")

    # ------------------------------------------------------------------
    # _list_integrations + caching
    # ------------------------------------------------------------------
    def list_integrations(self) -> list[dict]:
        """GET /api/public/v1/integrations — connected accounts list."""
        result = self._request_json("GET", POSTIZ_ACCOUNTS_PATH)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and isinstance(result.get("items"), list):
            return result["items"]
        return []

    def integration_id_for(self, identifier: str, profile: Optional[str] = None) -> Optional[str]:
        """Find a connected integration's id by identifier (e.g. ``instagram``).

        If ``profile`` is given (e.g. ``commoncreed``), prefer the integration
        whose profile field matches — needed when more than one IG account is
        connected.
        """
        items = self.list_integrations()
        # Prefer profile match
        if profile:
            for it in items:
                if it.get("identifier") == identifier and it.get("profile") == profile:
                    return it.get("id")
        for it in items:
            if it.get("identifier") == identifier:
                return it.get("id")
        return None

    # ------------------------------------------------------------------
    # _upload_file — POST /api/public/v1/upload (multipart, "file" field)
    # ------------------------------------------------------------------
    def upload_file(self, local_path: str, mime: str = "application/octet-stream") -> dict:
        """Upload a file to Postiz storage; returns the saved Media row.

        The Postiz response has the shape ``{id, organizationId, name, path, ...}``.
        Both ``id`` and ``path`` are required when referencing the file from
        a post body.
        """
        with open(local_path, "rb") as fh:
            files = {"file": (Path(local_path).name, fh, mime)}
            result = self._request_json(
                "POST", POSTIZ_UPLOAD_PATH, files=files, data={}
            )
        if not isinstance(result, dict) or "id" not in result or "path" not in result:
            raise RuntimeError(
                f"Postiz upload returned unexpected shape: {result!r}"
            )
        return result

    # ------------------------------------------------------------------
    # publish_post — two-step: upload media, then create post
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
        ig_profile: Optional[str] = None,
        yt_profile: Optional[str] = None,
    ) -> dict:
        """Publish a video to Instagram + YouTube via Postiz.

        Two-step contract enforced by Postiz public API:

        1. POST /api/public/v1/upload (multipart "file") for the video AND
           the thumbnail — each call returns ``{id, path, ...}``.
        2. POST /api/public/v1/posts with shape::

               {
                 "type": "now",
                 "shortLink": false,
                 "date": "<ISO 8601>",
                 "tags": [],
                 "posts": [
                   {
                     "integration": {"id": "<integrationId>"},
                     "value": [{"content": "...", "image": [{"id, path}]}],
                     "settings": {}   # server fills __type from provider
                   },
                   ...
                 ]
               }

        Returns the parsed JSON response from /posts (the created post group).
        Raises ``requests.HTTPError`` on persistent failure.
        """
        # 1. resolve integration ids ----------------------------------
        ig_id = self.integration_id_for(PROVIDER_INSTAGRAM, profile=ig_profile)
        yt_id = self.integration_id_for(PROVIDER_YOUTUBE, profile=yt_profile)
        if not ig_id and not yt_id:
            raise RuntimeError(
                "Postiz publish_post: no instagram or youtube integration "
                "found — check Postiz Settings → Channels"
            )

        # 2. upload video + thumbnail ---------------------------------
        logger.info(
            "Postiz publish_post: uploading video=%s thumbnail=%s",
            Path(video_path).name,
            Path(thumbnail_path).name,
        )
        video_media = self.upload_file(video_path, mime="video/mp4")
        thumb_media = self.upload_file(thumbnail_path, mime="image/jpeg")
        logger.info(
            "Postiz upload result: video.id=%s video.path=%s thumb.id=%s thumb.path=%s",
            video_media.get("id"),
            video_media.get("path"),
            thumb_media.get("id"),
            thumb_media.get("path"),
        )

        # 3. build the posts array ------------------------------------
        ig_full_caption = ig_caption
        yt_full_description = (
            f"{yt_title}\n\n{yt_description}".strip()
            if yt_description
            else yt_title
        )

        posts: list[dict[str, Any]] = []
        if ig_id:
            ig_settings: dict[str, Any] = {
                # InstagramDto.post_type — IsIn(['post', 'story']), IsDefined.
                # Postiz auto-detects video as a Reel inside the "post" type.
                "post_type": "post",
            }
            # Native Postiz collaborators tagging — way cleaner than the
            # post-publish IG Direct edit fallback.
            if ig_collab_usernames:
                ig_settings["collaborators"] = [
                    {"label": u} for u in ig_collab_usernames if u
                ]
            posts.append(
                {
                    "integration": {"id": ig_id},
                    "value": [
                        {
                            "content": ig_full_caption,
                            "image": [
                                {
                                    "id": video_media["id"],
                                    "path": video_media["path"],
                                }
                            ],
                        }
                    ],
                    "settings": ig_settings,
                }
            )
        if yt_id:
            yt_settings: dict[str, Any] = {
                # YoutubeSettingsDto: title (2-100), type IsIn(public/private/unlisted)
                "title": yt_title[:100],
                "type": "public",
                # Optional: explicitly mark as not for kids so YT doesn't
                # restrict comments + recommendations.
                "selfDeclaredMadeForKids": "no",
                # Use the uploaded thumbnail as the YouTube custom cover.
                "thumbnail": {
                    "id": thumb_media["id"],
                    "path": thumb_media["path"],
                },
            }
            posts.append(
                {
                    "integration": {"id": yt_id},
                    "value": [
                        {
                            "content": yt_full_description,
                            "image": [
                                {
                                    "id": video_media["id"],
                                    "path": video_media["path"],
                                }
                            ],
                        }
                    ],
                    "settings": yt_settings,
                }
            )

        # 4. fire CreatePostDto -----------------------------------------
        # Decide between "schedule" and "now":
        # - If the requested slot is in the future, ask Postiz to queue
        #   the post for that exact time. Postiz fires it at the slot.
        # - If the slot is missing or already in the past (e.g. user
        #   approved AFTER the peak hour), fall back to "now" so the post
        #   still goes out immediately.
        target = scheduled_slot or datetime.utcnow()
        if target.tzinfo is None:
            # Treat naive datetimes as UTC for the wire format. Sidecar
            # internal slot picker uses local time, but Postiz expects ISO
            # 8601 with explicit Z; the host runs in the owner's TZ so this
            # round-trip is safe as long as we're consistent.
            target_utc = target
        else:
            target_utc = target.astimezone(tz=None).replace(tzinfo=None)
        now_utc = datetime.utcnow()
        if target_utc > now_utc + timedelta(seconds=30):
            post_type = "schedule"
            date_iso = target_utc.isoformat() + "Z"
        else:
            post_type = "now"
            # Postiz still requires `date` even when type="now"; use the
            # current UTC instant.
            date_iso = now_utc.isoformat() + "Z"
        body = {
            "type": post_type,
            "shortLink": False,
            "date": date_iso,
            "tags": [],
            "posts": posts,
        }
        logger.info(
            "Postiz publish_post: type=%s date=%s",
            post_type,
            date_iso,
        )
        logger.info(
            "Postiz publish_post: creating %d post(s) ig_id=%s yt_id=%s",
            len(posts),
            ig_id,
            yt_id,
        )
        return self._request_json("POST", POSTIZ_POSTS_PATH, json_body=body)

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
