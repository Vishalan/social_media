"""Tests for Unit 12 additions to :class:`PostizClient`:

  * ``tt_profile`` kwarg (TikTok net-new)
  * ``ai_disclosure`` kwarg wiring onto YT + TT payloads

The Postiz HTTP layer is mocked so no live requests are made. These
assertions verify the WIRE payload shape so a Postiz client contract
change is caught before it ships.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

_SIDECAR = Path(__file__).resolve().parent.parent
if str(_SIDECAR) not in sys.path:
    sys.path.insert(0, str(_SIDECAR))

from postiz_client import (  # type: ignore
    PostizClient,
    PROVIDER_INSTAGRAM,
    PROVIDER_TIKTOK,
    PROVIDER_YOUTUBE,
)


def _integrations_fixture() -> list[dict]:
    return [
        {"id": "ig-abc", "identifier": PROVIDER_INSTAGRAM, "profile": "vesper"},
        {"id": "yt-def", "identifier": PROVIDER_YOUTUBE, "profile": "vesper"},
        {"id": "tt-ghi", "identifier": PROVIDER_TIKTOK, "profile": "vesper"},
        {"id": "ig-ccc", "identifier": PROVIDER_INSTAGRAM, "profile": "commoncreed"},
    ]


def _make_client_with_mocks(integrations: list[dict] | None = None) -> tuple[PostizClient, MagicMock]:
    """Build a PostizClient with list_integrations + upload_file +
    _request_json stubbed. Returns ``(client, request_spy)`` where
    ``request_spy`` captures the JSON body sent to POST /posts so tests
    can assert wire shape."""
    client = PostizClient(base_url="http://postiz", api_key="test-key")

    ints = integrations if integrations is not None else _integrations_fixture()
    client.list_integrations = MagicMock(return_value=ints)  # type: ignore[assignment]

    # upload_file returns a canned {id, path} payload.
    def _upload(local_path, mime="application/octet-stream"):
        return {
            "id": f"media-{Path(local_path).name}",
            "path": f"/media/{Path(local_path).name}",
            "organizationId": "org-1",
        }
    client.upload_file = MagicMock(side_effect=_upload)  # type: ignore[assignment]

    # _request_json captures the posts-create call and returns a dummy success.
    request_spy = MagicMock(return_value={"ok": True, "postIds": ["p-1"]})
    client._request_json = request_spy  # type: ignore[assignment]

    return client, request_spy


def _minimal_publish_kwargs(**overrides):
    """Baseline publish_post kwargs. Test overrides layer on top."""
    base = dict(
        video_path="/tmp/fake.mp4",
        thumbnail_path="/tmp/fake.jpg",
        ig_caption="IG caption here",
        yt_title="YT title here",
        yt_description="YT description body",
        ig_collab_usernames=[],
        scheduled_slot=datetime.utcnow() - timedelta(minutes=5),  # immediate
    )
    base.update(overrides)
    return base


class TikTokRoutingTests(unittest.TestCase):
    def test_tt_profile_adds_tiktok_post_element(self):
        client, spy = _make_client_with_mocks()
        client.publish_post(**_minimal_publish_kwargs(
            ig_profile="vesper",
            yt_profile="vesper",
            tt_profile="vesper",
        ))
        # One POST /posts call
        spy.assert_called_once()
        _, path = spy.call_args.args[:2]
        self.assertEqual(path, "/api/public/v1/posts")
        body = spy.call_args.kwargs["json_body"]
        integration_ids = [p["integration"]["id"] for p in body["posts"]]
        self.assertIn("ig-abc", integration_ids)
        self.assertIn("yt-def", integration_ids)
        self.assertIn("tt-ghi", integration_ids)

    def test_no_tt_profile_skips_tiktok_entirely(self):
        """Pre-Unit-12 callers (no tt_profile) keep IG+YT-only behavior."""
        client, spy = _make_client_with_mocks()
        client.publish_post(**_minimal_publish_kwargs(
            ig_profile="vesper",
            yt_profile="vesper",
        ))
        body = spy.call_args.kwargs["json_body"]
        integration_ids = [p["integration"]["id"] for p in body["posts"]]
        self.assertIn("ig-abc", integration_ids)
        self.assertIn("yt-def", integration_ids)
        self.assertNotIn("tt-ghi", integration_ids)

    def test_tt_caption_overrides_ig_caption(self):
        client, spy = _make_client_with_mocks()
        client.publish_post(**_minimal_publish_kwargs(
            ig_profile="vesper",
            yt_profile="vesper",
            tt_profile="vesper",
            tt_caption="CUSTOM TT BODY",
        ))
        body = spy.call_args.kwargs["json_body"]
        tt_post = next(p for p in body["posts"] if p["integration"]["id"] == "tt-ghi")
        self.assertEqual(tt_post["value"][0]["content"], "CUSTOM TT BODY")

    def test_tt_caption_defaults_to_ig_caption(self):
        client, spy = _make_client_with_mocks()
        client.publish_post(**_minimal_publish_kwargs(
            ig_profile="vesper",
            yt_profile="vesper",
            tt_profile="vesper",
            ig_caption="IG BODY",
        ))
        body = spy.call_args.kwargs["json_body"]
        tt_post = next(p for p in body["posts"] if p["integration"]["id"] == "tt-ghi")
        self.assertEqual(tt_post["value"][0]["content"], "IG BODY")

    def test_tt_profile_no_integration_does_not_break_other_platforms(self):
        """If TikTok isn't actually connected in Postiz, IG+YT still go out."""
        # Integration list without TikTok.
        ints = [
            {"id": "ig-abc", "identifier": PROVIDER_INSTAGRAM, "profile": "vesper"},
            {"id": "yt-def", "identifier": PROVIDER_YOUTUBE, "profile": "vesper"},
        ]
        client, spy = _make_client_with_mocks(integrations=ints)
        client.publish_post(**_minimal_publish_kwargs(
            ig_profile="vesper",
            yt_profile="vesper",
            tt_profile="vesper",  # caller asks for TT but it's not connected
        ))
        body = spy.call_args.kwargs["json_body"]
        integration_ids = [p["integration"]["id"] for p in body["posts"]]
        self.assertEqual(sorted(integration_ids), ["ig-abc", "yt-def"])


class AiDisclosureTests(unittest.TestCase):
    def test_yt_gets_containsSyntheticMedia_true_when_disclosed(self):
        client, spy = _make_client_with_mocks()
        client.publish_post(**_minimal_publish_kwargs(
            ig_profile="vesper",
            yt_profile="vesper",
            tt_profile="vesper",
            ai_disclosure=True,
        ))
        body = spy.call_args.kwargs["json_body"]
        yt_post = next(p for p in body["posts"] if p["integration"]["id"] == "yt-def")
        self.assertTrue(yt_post["settings"].get("containsSyntheticMedia"))

    def test_tt_gets_disclosure_info_ai_generated(self):
        client, spy = _make_client_with_mocks()
        client.publish_post(**_minimal_publish_kwargs(
            ig_profile="vesper",
            yt_profile="vesper",
            tt_profile="vesper",
            ai_disclosure=True,
        ))
        body = spy.call_args.kwargs["json_body"]
        tt_post = next(p for p in body["posts"] if p["integration"]["id"] == "tt-ghi")
        self.assertEqual(
            tt_post["settings"].get("disclosure_info"),
            {"ai_generated": True},
        )

    def test_ig_has_no_ai_disclosure_field_even_when_set(self):
        """Instagram has no Graph API for the AI label (C2PA-only per the
        plan + framework research); we don't invent a settings field."""
        client, spy = _make_client_with_mocks()
        client.publish_post(**_minimal_publish_kwargs(
            ig_profile="vesper",
            yt_profile="vesper",
            tt_profile="vesper",
            ai_disclosure=True,
        ))
        body = spy.call_args.kwargs["json_body"]
        ig_post = next(p for p in body["posts"] if p["integration"]["id"] == "ig-abc")
        # No containsSyntheticMedia or disclosure_info field at the IG level.
        self.assertNotIn("containsSyntheticMedia", ig_post["settings"])
        self.assertNotIn("disclosure_info", ig_post["settings"])

    def test_ai_disclosure_default_off_omits_fields(self):
        """Back-compat: pre-Unit-12 callers didn't pass ai_disclosure at all.
        With the default False the payload must not carry the new fields."""
        client, spy = _make_client_with_mocks()
        client.publish_post(**_minimal_publish_kwargs(
            ig_profile="vesper",
            yt_profile="vesper",
            tt_profile="vesper",
            # ai_disclosure omitted entirely — defaults to False
        ))
        body = spy.call_args.kwargs["json_body"]
        yt_post = next(p for p in body["posts"] if p["integration"]["id"] == "yt-def")
        tt_post = next(p for p in body["posts"] if p["integration"]["id"] == "tt-ghi")
        self.assertNotIn("containsSyntheticMedia", yt_post["settings"])
        self.assertNotIn("disclosure_info", tt_post["settings"])


class ImageOnlyModeTests(unittest.TestCase):
    """Image-only mode (memes) still skips YT + TT since both need video."""

    def test_image_mode_skips_yt_and_tt(self):
        client, spy = _make_client_with_mocks()
        client.publish_post(**_minimal_publish_kwargs(
            ig_profile="commoncreed",
            yt_profile="commoncreed",
            tt_profile="commoncreed",
            media_kind="image",
        ))
        body = spy.call_args.kwargs["json_body"]
        integration_ids = [p["integration"]["id"] for p in body["posts"]]
        # Only the IG (commoncreed) integration makes it through.
        self.assertEqual(integration_ids, ["ig-ccc"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
