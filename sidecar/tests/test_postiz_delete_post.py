"""Tests for :meth:`PostizClient.delete_post` — rapid-unpublish plumbing."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

_SIDECAR = Path(__file__).resolve().parent.parent
if str(_SIDECAR) not in sys.path:
    sys.path.insert(0, str(_SIDECAR))

from postiz_client import PostizClient  # type: ignore # noqa: E402


class DeletePostTests(unittest.TestCase):
    def test_delete_post_issues_delete_request_to_correct_path(self):
        client = PostizClient(base_url="http://postiz", api_key="test-key")
        spy = MagicMock(return_value={"deleted": True})
        client._request_json = spy  # type: ignore[assignment]

        result = client.delete_post("p-ig-abc123")
        self.assertEqual(result, {"deleted": True})

        spy.assert_called_once()
        method, path = spy.call_args.args[:2]
        self.assertEqual(method, "DELETE")
        self.assertEqual(path, "/api/public/v1/posts/p-ig-abc123")

    def test_delete_post_with_empty_id_raises(self):
        client = PostizClient(base_url="http://postiz", api_key="test-key")
        client._request_json = MagicMock()  # type: ignore[assignment]
        with self.assertRaises(ValueError):
            client.delete_post("")

    def test_delete_post_propagates_4xx(self):
        """404 / 410 / platform rejection must surface to the caller —
        the rapid-unpublish summary reports per-post outcome."""
        import requests
        client = PostizClient(base_url="http://postiz", api_key="test-key")

        def _raise_http(*args, **kw):
            resp = MagicMock()
            resp.status_code = 404
            raise requests.HTTPError("Postiz 4xx 404: not found", response=resp)

        client._request_json = MagicMock(side_effect=_raise_http)  # type: ignore[assignment]
        with self.assertRaises(requests.HTTPError):
            client.delete_post("p-already-gone")


if __name__ == "__main__":
    unittest.main(verbosity=2)
