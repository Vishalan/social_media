"""Tests for ``ChatterboxVoiceGenerator.check_ref_available`` (Unit 8).

The pre-flight has three discriminated outcomes:
  * ``ok``           — proceed with TTS
  * ``ref_missing``  — sidecar up, reference absent → abort this channel
  * ``sidecar_down`` — transport failure → abort both pipelines

Tests mock the ``requests`` layer so no live sidecar is needed.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from voiceover.chatterbox_generator import (
    ChatterboxVoiceGenerator,
    PreflightResult,
)


def _gen() -> ChatterboxVoiceGenerator:
    """Fresh generator with a harmless endpoint (never hit in tests)."""
    return ChatterboxVoiceGenerator(
        reference_audio="/app/refs/vesper/archivist.wav",
        endpoint="http://test-chatterbox:7777",
    )


def _mock_refs_list_response(entries: list[str], *, status_code: int = 200):
    """Build a MagicMock that mimics ``requests.get().json()`` behavior."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = {
        "refs_root": "/app/refs",
        "entries": entries,
        "exists": True,
    }
    # raise_for_status() short-circuits on 2xx; raises HTTPError on 4xx/5xx.
    if status_code >= 400:
        import requests
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Server Error"
        )
    else:
        response.raise_for_status.return_value = None
    return response


class PreflightOkTests(unittest.TestCase):
    def test_expected_ref_present_returns_ok(self):
        g = _gen()
        with patch("voiceover.chatterbox_generator.requests.get") as mock_get:
            mock_get.return_value = _mock_refs_list_response(
                entries=[
                    "commoncreed/narrator.wav",
                    "vesper/archivist.wav",
                ],
            )
            result = g.check_ref_available("/app/refs/vesper/archivist.wav")
        self.assertEqual(result.status, "ok")

    def test_relative_ref_lookup_also_works(self):
        """Caller may pass the relative path directly."""
        g = _gen()
        with patch("voiceover.chatterbox_generator.requests.get") as mock_get:
            mock_get.return_value = _mock_refs_list_response(
                entries=["vesper/archivist.wav"],
            )
            result = g.check_ref_available("vesper/archivist.wav")
        self.assertEqual(result.status, "ok")

    def test_host_path_prefix_stripped(self):
        """A host-side path like /opt/commoncreed/assets/... is normalized
        to the relative form before matching."""
        g = _gen()
        with patch("voiceover.chatterbox_generator.requests.get") as mock_get:
            mock_get.return_value = _mock_refs_list_response(
                entries=["vesper/archivist.wav"],
            )
            result = g.check_ref_available(
                "/opt/commoncreed/assets/vesper/archivist.wav"
            )
        self.assertEqual(result.status, "ok")


class PreflightRefMissingTests(unittest.TestCase):
    def test_sidecar_up_but_ref_absent_returns_ref_missing(self):
        g = _gen()
        with patch("voiceover.chatterbox_generator.requests.get") as mock_get:
            mock_get.return_value = _mock_refs_list_response(
                entries=["commoncreed/narrator.wav"],
            )
            result = g.check_ref_available("/app/refs/vesper/archivist.wav")
        self.assertEqual(result.status, "ref_missing")
        self.assertIn("vesper/archivist.wav", result.reason)

    def test_empty_refs_root_returns_ref_missing(self):
        g = _gen()
        with patch("voiceover.chatterbox_generator.requests.get") as mock_get:
            mock_get.return_value = _mock_refs_list_response(entries=[])
            result = g.check_ref_available("/app/refs/vesper/archivist.wav")
        self.assertEqual(result.status, "ref_missing")


class PreflightSidecarDownTests(unittest.TestCase):
    def test_connection_error_returns_sidecar_down(self):
        import requests
        g = _gen()
        with patch("voiceover.chatterbox_generator.requests.get") as mock_get:
            mock_get.side_effect = requests.ConnectionError("ECONNREFUSED")
            result = g.check_ref_available("/app/refs/vesper/archivist.wav")
        self.assertEqual(result.status, "sidecar_down")
        self.assertIn("ECONNREFUSED", result.reason)

    def test_timeout_returns_sidecar_down(self):
        import requests
        g = _gen()
        with patch("voiceover.chatterbox_generator.requests.get") as mock_get:
            mock_get.side_effect = requests.ReadTimeout("read timed out")
            result = g.check_ref_available("/app/refs/vesper/archivist.wav")
        self.assertEqual(result.status, "sidecar_down")

    def test_5xx_returns_sidecar_down(self):
        g = _gen()
        with patch("voiceover.chatterbox_generator.requests.get") as mock_get:
            mock_get.return_value = _mock_refs_list_response(
                entries=[], status_code=503,
            )
            result = g.check_ref_available("/app/refs/vesper/archivist.wav")
        self.assertEqual(result.status, "sidecar_down")


class ListRefsTests(unittest.TestCase):
    def test_list_refs_returns_entries_from_sidecar(self):
        g = _gen()
        with patch("voiceover.chatterbox_generator.requests.get") as mock_get:
            mock_get.return_value = _mock_refs_list_response(
                entries=["a/one.wav", "b/two.wav", "c/three.wav"],
            )
            entries = g.list_refs()
        self.assertEqual(entries, ["a/one.wav", "b/two.wav", "c/three.wav"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
