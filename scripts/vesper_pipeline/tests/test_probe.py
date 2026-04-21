"""Tests for :mod:`scripts.vesper_pipeline.probe`.

Hermetic — every HTTP + Redis client is injected. No real network.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import List

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from vesper_pipeline.probe import (  # noqa: E402
    ProbeResult,
    ProbeStatus,
    Prober,
    format_results,
    main,
)


# ─── Fakes ─────────────────────────────────────────────────────────────────


class _FakeHttpClient:
    """Records GETs + returns canned responses keyed by URL substring."""

    def __init__(self, responses: dict[str, dict]):
        # responses: {url_substr: {status_code, text?, exc?}}
        self.responses = responses
        self.calls: List[dict] = []

    def get(self, url, *, headers=None, timeout=5.0):
        self.calls.append({
            "url": url, "headers": dict(headers or {}), "timeout": timeout,
        })
        for substr, spec in self.responses.items():
            if substr in url:
                if "exc" in spec:
                    raise spec["exc"]

                class _Resp:
                    status_code = spec.get("status_code", 200)
                    text = spec.get("text", "")

                    @staticmethod
                    def json():
                        return spec.get("json", {})

                return _Resp()
        # No match → treat as connection error.
        raise RuntimeError(f"no fake for URL {url}")


class _FakeRedis:
    def __init__(self, *, pong: bool = True, exc: Exception | None = None):
        self.pong = pong
        self.exc = exc

    def ping(self):
        if self.exc:
            raise self.exc
        return self.pong


def _env(**overrides) -> dict:
    base = {
        "REDIS_URL": "redis://localhost:6379",
        "COMFYUI_URL": "http://server:8188",
        "CHATTERBOX_ENDPOINT": "http://server:7777",
        "CHATTERBOX_REFERENCE_AUDIO": "/app/refs/archivist.wav",
        "POSTIZ_URL": "http://server:3000",
        "POSTIZ_API_KEY": "po-xyz",
        "TELEGRAM_BOT_TOKEN": "tg-123",
    }
    base.update(overrides)
    return base


def _prober(
    *,
    env: dict | None = None,
    http: _FakeHttpClient | None = None,
    redis: _FakeRedis | None = None,
) -> Prober:
    http = http or _FakeHttpClient({})
    redis_obj = redis if redis is not None else _FakeRedis(pong=True)
    return Prober(
        env=env or _env(),
        http_client_factory=lambda: http,
        redis_client_factory=lambda url: redis_obj,
    )


# ─── Redis probe ──────────────────────────────────────────────────────────


class RedisProbeTests(unittest.TestCase):
    def test_redis_ping_passes(self):
        prober = _prober()
        result = prober._probe_redis()
        self.assertEqual(result.status, ProbeStatus.PASS)
        self.assertTrue(result.required)

    def test_redis_missing_url_fails(self):
        prober = _prober(env=_env(REDIS_URL=""))
        result = prober._probe_redis()
        self.assertEqual(result.status, ProbeStatus.FAIL)
        self.assertIn("REDIS_URL not set", result.message)

    def test_redis_ping_connection_error_fails(self):
        prober = _prober(redis=_FakeRedis(
            exc=ConnectionError("conn refused"),
        ))
        result = prober._probe_redis()
        self.assertEqual(result.status, ProbeStatus.FAIL)
        self.assertIn("PING failed", result.message)
        self.assertIn("conn refused", result.message)


# ─── ComfyUI probe ────────────────────────────────────────────────────────


class ComfyUIProbeTests(unittest.TestCase):
    def test_comfyui_200_passes(self):
        http = _FakeHttpClient({
            "/system_stats": {"status_code": 200},
        })
        prober = _prober(http=http)
        result = prober._probe_comfyui()
        self.assertEqual(result.status, ProbeStatus.PASS)
        self.assertIn("/system_stats", http.calls[0]["url"])

    def test_comfyui_missing_url_fails(self):
        prober = _prober(env=_env(COMFYUI_URL=""))
        result = prober._probe_comfyui()
        self.assertEqual(result.status, ProbeStatus.FAIL)

    def test_comfyui_500_fails(self):
        http = _FakeHttpClient({
            "/system_stats": {"status_code": 500},
        })
        prober = _prober(http=http)
        result = prober._probe_comfyui()
        self.assertEqual(result.status, ProbeStatus.FAIL)


# ─── Chatterbox probes ────────────────────────────────────────────────────


class ChatterboxProbeTests(unittest.TestCase):
    def test_health_pass_then_refs_with_matching_archivist(self):
        http = _FakeHttpClient({
            "/health": {"status_code": 200},
            "/refs/list": {
                "status_code": 200,
                "text": '{"files": ["archivist.wav", "cc_default.wav"]}',
            },
        })
        prober = _prober(http=http)
        results = prober._probe_chatterbox()
        statuses = [r.status for r in results]
        self.assertEqual(statuses, [ProbeStatus.PASS, ProbeStatus.PASS])

    def test_refs_list_without_archivist_warns(self):
        """Vesper's ref file missing from the server-side list = warn
        (pipeline will fall back to default voice)."""
        http = _FakeHttpClient({
            "/health": {"status_code": 200},
            "/refs/list": {
                "status_code": 200,
                "text": '{"files": ["cc_default.wav"]}',
            },
        })
        prober = _prober(http=http)
        results = prober._probe_chatterbox()
        self.assertEqual(results[0].status, ProbeStatus.PASS)  # health
        self.assertEqual(results[1].status, ProbeStatus.WARN)  # refs
        self.assertIn("archivist.wav", results[1].message)

    def test_health_fail_skips_refs(self):
        http = _FakeHttpClient({
            "/health": {"status_code": 502},
        })
        prober = _prober(http=http)
        results = prober._probe_chatterbox()
        self.assertEqual(results[0].status, ProbeStatus.FAIL)
        self.assertEqual(results[1].status, ProbeStatus.SKIP)

    def test_missing_endpoint_fails(self):
        prober = _prober(env=_env(CHATTERBOX_ENDPOINT=""))
        results = prober._probe_chatterbox()
        self.assertEqual(results[0].status, ProbeStatus.FAIL)


# ─── Postiz probe ─────────────────────────────────────────────────────────


class PostizProbeTests(unittest.TestCase):
    def test_postiz_200_with_auth_header(self):
        http = _FakeHttpClient({
            "/api/public/v1/integrations": {"status_code": 200, "text": "[]"},
        })
        prober = _prober(http=http)
        result = prober._probe_postiz()
        self.assertEqual(result.status, ProbeStatus.PASS)
        self.assertEqual(http.calls[0]["headers"].get("Authorization"), "po-xyz")

    def test_postiz_missing_env_fails_with_list(self):
        prober = _prober(env=_env(POSTIZ_API_KEY=""))
        result = prober._probe_postiz()
        self.assertEqual(result.status, ProbeStatus.FAIL)
        self.assertIn("POSTIZ_API_KEY", result.message)

    def test_postiz_401_fails(self):
        http = _FakeHttpClient({
            "/api/public/v1/integrations": {"status_code": 401},
        })
        prober = _prober(http=http)
        result = prober._probe_postiz()
        self.assertEqual(result.status, ProbeStatus.FAIL)
        self.assertIn("401", result.message)


# ─── Telegram probe ───────────────────────────────────────────────────────


class TelegramProbeTests(unittest.TestCase):
    def test_getme_200_passes(self):
        http = _FakeHttpClient({
            "/getMe": {"status_code": 200},
        })
        prober = _prober(http=http)
        result = prober._probe_telegram()
        self.assertEqual(result.status, ProbeStatus.PASS)

    def test_invalid_token_404_fails(self):
        http = _FakeHttpClient({
            "/getMe": {"status_code": 404},
        })
        prober = _prober(http=http)
        result = prober._probe_telegram()
        self.assertEqual(result.status, ProbeStatus.FAIL)

    def test_missing_token_fails(self):
        prober = _prober(env=_env(TELEGRAM_BOT_TOKEN=""))
        result = prober._probe_telegram()
        self.assertEqual(result.status, ProbeStatus.FAIL)


# ─── fal.ai probe (optional) ──────────────────────────────────────────────


class FalAiProbeTests(unittest.TestCase):
    def test_skip_when_key_absent(self):
        prober = _prober(env=_env(FAL_API_KEY=""))
        result = prober._probe_fal_ai()
        self.assertEqual(result.status, ProbeStatus.SKIP)
        self.assertFalse(result.required)
        self.assertFalse(result.is_blocking)

    def test_404_from_root_treated_as_reachable(self):
        http = _FakeHttpClient({
            "fal.run": {"status_code": 404},
        })
        prober = _prober(env=_env(FAL_API_KEY="fal-x"), http=http)
        result = prober._probe_fal_ai()
        self.assertEqual(result.status, ProbeStatus.PASS)
        self.assertFalse(result.required)

    def test_connection_error_warns_but_not_blocking(self):
        http = _FakeHttpClient({})  # no match → RuntimeError
        prober = _prober(env=_env(FAL_API_KEY="fal-x"), http=http)
        result = prober._probe_fal_ai()
        self.assertEqual(result.status, ProbeStatus.WARN)
        self.assertFalse(result.is_blocking)


# ─── End-to-end + CLI ─────────────────────────────────────────────────────


class EndToEndTests(unittest.TestCase):
    def _http_happy(self):
        return _FakeHttpClient({
            "/system_stats": {"status_code": 200},
            "/health": {"status_code": 200},
            "/refs/list": {
                "status_code": 200,
                "text": '{"files": ["archivist.wav"]}',
            },
            "/api/public/v1/integrations": {"status_code": 200, "text": "[]"},
            "/getMe": {"status_code": 200},
            "fal.run": {"status_code": 404},
        })

    def test_all_passing_produces_zero_blockers(self):
        prober = _prober(
            env=_env(FAL_API_KEY="fal-x"),
            http=self._http_happy(),
        )
        results = prober.run()
        self.assertEqual(prober.blocking_failures(results), [])

    def test_one_required_fail_blocks(self):
        http = self._http_happy()
        # Break Postiz specifically.
        http.responses["/api/public/v1/integrations"] = {"status_code": 401}
        prober = _prober(http=http)
        results = prober.run()
        blockers = prober.blocking_failures(results)
        self.assertEqual(len(blockers), 1)
        self.assertEqual(blockers[0].name, "postiz")


class FormatResultsTests(unittest.TestCase):
    def test_format_shows_summary_with_blocking_count(self):
        results = [
            ProbeResult("a", ProbeStatus.PASS, latency_ms=12.5),
            ProbeResult("b", ProbeStatus.FAIL, message="boom"),
        ]
        text = format_results(results)
        self.assertIn("[ok] a", text)
        self.assertIn("[FAIL] b", text)
        self.assertIn("boom", text)
        self.assertIn("1 blocking", text)
        self.assertIn("(12 ms)", text)


class MainExitCodeTests(unittest.TestCase):
    def test_happy_exits_zero(self):
        import vesper_pipeline.probe as probe_mod

        class _AllPass(Prober):
            def run(self):
                return [ProbeResult("x", ProbeStatus.PASS)]

        original = probe_mod.Prober
        probe_mod.Prober = _AllPass  # type: ignore[assignment]
        try:
            self.assertEqual(main(), 0)
        finally:
            probe_mod.Prober = original  # type: ignore[assignment]

    def test_blocker_exits_two(self):
        import vesper_pipeline.probe as probe_mod

        class _Fail(Prober):
            def run(self):
                return [ProbeResult("x", ProbeStatus.FAIL, message="bad")]

        original = probe_mod.Prober
        probe_mod.Prober = _Fail  # type: ignore[assignment]
        try:
            self.assertEqual(main(), 2)
        finally:
            probe_mod.Prober = original  # type: ignore[assignment]


if __name__ == "__main__":
    unittest.main(verbosity=2)
