"""Tests for :class:`FluxRouter` (Unit 9b).

Exercises the local-first / fal.ai-fallback decision tree using
stubbed backends. No real network calls — no ComfyUI, no fal.ai.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Optional

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from still_gen.flux_client import FluxGenerationError, FluxResult  # noqa: E402
from still_gen.flux_router import FluxRouter  # noqa: E402
from video_gen.gpu_mutex import GpuMutexAcquireTimeout  # noqa: E402


class _StubBackend:
    """Backend double with scripted behavior per call."""

    def __init__(self, name: str, behavior: list):
        self.name = name
        self.behavior = list(behavior)  # copy — drained in FIFO order
        self.calls: list[dict] = []

    async def generate(
        self,
        prompt,
        output_path,
        *,
        image_size=None,
        num_inference_steps=None,
        guidance_scale=None,
        seed=None,
        negative_prompt=None,
    ):
        self.calls.append({"prompt": prompt, "output_path": output_path})
        if not self.behavior:
            raise AssertionError(f"{self.name}: no scripted behavior left")
        next_step = self.behavior.pop(0)
        if isinstance(next_step, BaseException):
            raise next_step
        return next_step


def _ok(path: str = "/tmp/out.png") -> FluxResult:
    return FluxResult(
        local_path=path,
        remote_url="x://y",
        width=768,
        height=1344,
        duration_ms=1.0,
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class LocalSuccessPathTests(unittest.TestCase):
    def test_local_succeeds_skips_fallback(self):
        local = _StubBackend("local", [_ok()])
        fallback = _StubBackend("fallback", [])
        router = FluxRouter(local=local, fallback=fallback)

        result = _run(router.generate("horror", "/tmp/out.png"))
        self.assertEqual(result.local_path, "/tmp/out.png")
        self.assertEqual(router.telemetry.calls, 1)
        self.assertEqual(router.telemetry.local_success, 1)
        self.assertEqual(router.telemetry.fallback_invocations, 0)
        self.assertEqual(len(fallback.calls), 0, "fallback must not be invoked")


class MutexTimeoutFallbackTests(unittest.TestCase):
    def test_mutex_timeout_routes_to_fallback(self):
        local = _StubBackend(
            "local", [GpuMutexAcquireTimeout("gpu plane busy")]
        )
        fallback = _StubBackend("fallback", [_ok()])
        router = FluxRouter(local=local, fallback=fallback)

        result = _run(router.generate("horror", "/tmp/out.png"))
        self.assertEqual(result.local_path, "/tmp/out.png")
        self.assertEqual(router.telemetry.local_success, 0)
        self.assertEqual(router.telemetry.fallback_invocations, 1)
        self.assertEqual(router.telemetry.fallback_success, 1)
        self.assertEqual(len(fallback.calls), 1)

    def test_comfyui_error_routes_to_fallback(self):
        local = _StubBackend(
            "local", [FluxGenerationError("workflow missing")]
        )
        fallback = _StubBackend("fallback", [_ok()])
        router = FluxRouter(local=local, fallback=fallback)

        _ = _run(router.generate("horror", "/tmp/out.png"))
        self.assertEqual(router.telemetry.fallback_invocations, 1)
        self.assertEqual(router.telemetry.fallback_success, 1)


class BothPathsFailTests(unittest.TestCase):
    def test_both_paths_fail_raises_and_counts_failure(self):
        local = _StubBackend("local", [FluxGenerationError("local bad")])
        fallback = _StubBackend(
            "fallback", [FluxGenerationError("fal.ai bad")]
        )
        router = FluxRouter(local=local, fallback=fallback)

        with self.assertRaises(FluxGenerationError) as cm:
            _run(router.generate("horror", "/tmp/out.png"))
        self.assertIn("Both Flux paths failed", str(cm.exception))
        self.assertIn("local bad", str(cm.exception))
        self.assertIn("fal.ai bad", str(cm.exception))
        self.assertEqual(router.telemetry.total_failures, 1)
        self.assertEqual(router.telemetry.fallback_invocations, 1)
        self.assertEqual(router.telemetry.fallback_success, 0)

    def test_no_fallback_configured_raises_with_guidance(self):
        local = _StubBackend("local", [GpuMutexAcquireTimeout("busy")])
        router = FluxRouter(local=local, fallback=None)

        with self.assertRaises(FluxGenerationError) as cm:
            _run(router.generate("horror", "/tmp/out.png"))
        self.assertIn("no fal.ai fallback configured", str(cm.exception).lower())
        self.assertEqual(router.telemetry.total_failures, 1)


class TelemetryTests(unittest.TestCase):
    def test_fallback_rate_is_fraction_of_calls(self):
        # Script: 2 local successes, then 1 mutex timeout + 1 fallback success.
        local = _StubBackend(
            "local",
            [
                _ok("/tmp/a.png"),
                _ok("/tmp/b.png"),
                GpuMutexAcquireTimeout("busy"),
            ],
        )
        fallback = _StubBackend("fallback", [_ok("/tmp/c.png")])
        router = FluxRouter(local=local, fallback=fallback)

        _run(router.generate("p1", "/tmp/a.png"))
        _run(router.generate("p2", "/tmp/b.png"))
        _run(router.generate("p3", "/tmp/c.png"))

        self.assertEqual(router.telemetry.calls, 3)
        self.assertEqual(router.telemetry.local_success, 2)
        self.assertEqual(router.telemetry.fallback_invocations, 1)
        self.assertEqual(router.telemetry.fallback_success, 1)
        self.assertAlmostEqual(router.telemetry.fallback_rate(), 1 / 3, places=3)


class PromptOptionsPassThroughTests(unittest.TestCase):
    def test_options_forwarded_to_local(self):
        captured = {}

        class _Capture(_StubBackend):
            async def generate(self, prompt, output_path, **opts):
                captured["prompt"] = prompt
                captured["opts"] = opts
                return _ok(output_path)

        local = _Capture("local", [_ok()])
        router = FluxRouter(local=local)
        _run(router.generate(
            "a dark hallway",
            "/tmp/h.png",
            image_size="portrait_16_9",
            num_inference_steps=28,
            guidance_scale=3.5,
            seed=1234,
            negative_prompt="blur",
        ))
        self.assertEqual(captured["prompt"], "a dark hallway")
        self.assertEqual(captured["opts"]["num_inference_steps"], 28)
        self.assertEqual(captured["opts"]["seed"], 1234)
        self.assertEqual(captured["opts"]["negative_prompt"], "blur")


if __name__ == "__main__":
    unittest.main(verbosity=2)
