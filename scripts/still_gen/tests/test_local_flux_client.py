"""Tests for :class:`LocalFluxClient` (Unit 9b).

ComfyUIClient and GpuPlaneMutex are both stubbed so the test suite is
hermetic. Verifies:
  * GPU mutex is acquired/released around the workflow run
  * workflow JSON is loaded and parameters substituted (round-trip
    exercised by the substitution logic in ComfyUIClient — we check
    the `params` dict passed in)
  * GpuMutexAcquireTimeout propagates upward (router catches it)
  * ComfyUI errors become FluxGenerationError
  * Missing workflow file raises FluxGenerationError with guidance
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from still_gen.flux_client import FluxGenerationError  # noqa: E402
from still_gen.local_flux_client import LocalFluxClient  # noqa: E402
from video_gen.gpu_mutex import (  # noqa: E402
    FakeMutexBackend,
    GpuMutexAcquireTimeout,
    GpuPlaneMutex,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _write_stub_workflow(tmpdir: str) -> str:
    """Minimal workflow JSON with substitution placeholders."""
    wf = {
        "3": {  # KSampler
            "inputs": {
                "steps": "{{num_inference_steps}}",
                "cfg": "{{guidance_scale}}",
                "seed": "{{seed}}",
            },
            "class_type": "KSampler",
        },
        "6": {  # CLIP text positive
            "inputs": {"text": "{{prompt}}"},
            "class_type": "CLIPTextEncode",
        },
        "7": {  # CLIP text negative
            "inputs": {"text": "{{negative_prompt}}"},
            "class_type": "CLIPTextEncode",
        },
        "9": {  # EmptyLatentImage
            "inputs": {
                "width": "{{width}}",
                "height": "{{height}}",
            },
            "class_type": "EmptyLatentImage",
        },
    }
    path = os.path.join(tmpdir, "flux_still.json")
    with open(path, "w") as f:
        json.dump(wf, f)
    return path


def _fresh_mutex() -> GpuPlaneMutex:
    backend = FakeMutexBackend()
    return GpuPlaneMutex(backend)


class _FakeComfy:
    """Async-API-compatible stub for ComfyUIClient."""

    def __init__(
        self,
        *,
        run_result: str = "prompt-123",
        download_files: list[str] | None = None,
        run_raises: BaseException | None = None,
        download_raises: BaseException | None = None,
    ):
        self.run_result = run_result
        self.download_files = (
            download_files if download_files is not None else ["/tmp/out.png"]
        )
        self.run_raises = run_raises
        self.download_raises = download_raises
        self.run_calls: list[dict] = []
        self.download_calls: list[dict] = []

    async def run_workflow(self, workflow_json, params=None, wait_for_completion=True):
        self.run_calls.append({"workflow": workflow_json, "params": params})
        if self.run_raises is not None:
            raise self.run_raises
        return self.run_result

    async def download_output(self, prompt_id, output_dir, output_filename=None):
        self.download_calls.append({
            "prompt_id": prompt_id,
            "output_dir": output_dir,
            "output_filename": output_filename,
        })
        if self.download_raises is not None:
            raise self.download_raises
        return list(self.download_files)


class LocalFluxHappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="local-flux-")
        self.workflow_path = _write_stub_workflow(self.tmp)
        self.output_dir = os.path.join(self.tmp, "out")
        os.makedirs(self.output_dir, exist_ok=True)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_generate_acquires_mutex_and_submits_workflow(self):
        mutex = _fresh_mutex()
        target = os.path.join(self.output_dir, "beat_001.png")
        comfy = _FakeComfy(download_files=[target])
        client = LocalFluxClient(
            comfyui_client=comfy,
            mutex=mutex,
            workflow_path=self.workflow_path,
            output_dir=self.output_dir,
        )

        result = _run(client.generate(
            "a bone-white hallway at 3am",
            target,
            seed=42,
        ))

        # workflow submitted with the right params
        self.assertEqual(len(comfy.run_calls), 1)
        params = comfy.run_calls[0]["params"]
        self.assertEqual(params["prompt"], "a bone-white hallway at 3am")
        self.assertEqual(params["seed"], 42)
        self.assertEqual(params["num_inference_steps"], 28)  # default
        # 9:16 portrait default
        self.assertEqual(params["width"], 768)
        self.assertEqual(params["height"], 1344)

        # download invoked with the right output path split
        self.assertEqual(len(comfy.download_calls), 1)
        self.assertEqual(
            comfy.download_calls[0]["output_filename"],
            "beat_001.png",
        )

        # mutex released (next acquire should succeed cheaply)
        after = mutex.acquire(caller="next", timeout_s=1.0)
        self.assertEqual(after.caller, "next")

        # result shape is correct
        self.assertEqual(result.local_path, target)
        self.assertEqual(result.width, 768)
        self.assertEqual(result.height, 1344)

    def test_custom_image_size_resolved_to_explicit_wh(self):
        mutex = _fresh_mutex()
        comfy = _FakeComfy()
        client = LocalFluxClient(
            comfyui_client=comfy,
            mutex=mutex,
            workflow_path=self.workflow_path,
        )
        _run(client.generate("x", "/tmp/y.png", image_size="square_hd"))
        params = comfy.run_calls[0]["params"]
        self.assertEqual(params["width"], 1024)
        self.assertEqual(params["height"], 1024)


class LocalFluxFailureModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="local-flux-fail-")
        self.workflow_path = _write_stub_workflow(self.tmp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_mutex_timeout_bubbles_up_unchanged(self):
        """Router catches GpuMutexAcquireTimeout — the client must NOT
        wrap it in FluxGenerationError."""
        mutex = _fresh_mutex()
        # Hog the slot so the LocalFluxClient acquire times out fast.
        _ = mutex.acquire(caller="hog")

        comfy = _FakeComfy()
        client = LocalFluxClient(
            comfyui_client=comfy,
            mutex=mutex,
            workflow_path=self.workflow_path,
            mutex_timeout_s=0.1,
        )
        with self.assertRaises(GpuMutexAcquireTimeout):
            _run(client.generate("x", "/tmp/y.png"))
        # ComfyUI should never have been called
        self.assertEqual(len(comfy.run_calls), 0)

    def test_comfyui_error_becomes_flux_generation_error(self):
        mutex = _fresh_mutex()
        comfy = _FakeComfy(run_raises=RuntimeError("ComfyUI connection refused"))
        client = LocalFluxClient(
            comfyui_client=comfy,
            mutex=mutex,
            workflow_path=self.workflow_path,
        )
        with self.assertRaises(FluxGenerationError) as cm:
            _run(client.generate("x", "/tmp/y.png"))
        self.assertIn("ComfyUI", str(cm.exception))

        # Mutex must still be released on error path
        after = mutex.acquire(caller="next", timeout_s=1.0)
        self.assertEqual(after.caller, "next")

    def test_download_error_becomes_flux_generation_error(self):
        mutex = _fresh_mutex()
        comfy = _FakeComfy(download_raises=RuntimeError("404 on /view"))
        client = LocalFluxClient(
            comfyui_client=comfy,
            mutex=mutex,
            workflow_path=self.workflow_path,
        )
        with self.assertRaises(FluxGenerationError) as cm:
            _run(client.generate("x", "/tmp/y.png"))
        self.assertIn("download", str(cm.exception).lower())

    def test_no_output_files_raises_flux_generation_error(self):
        mutex = _fresh_mutex()
        comfy = _FakeComfy(download_files=[])  # success-reported but empty
        client = LocalFluxClient(
            comfyui_client=comfy,
            mutex=mutex,
            workflow_path=self.workflow_path,
        )
        with self.assertRaises(FluxGenerationError) as cm:
            _run(client.generate("x", "/tmp/y.png"))
        self.assertIn("no output", str(cm.exception).lower())

    def test_missing_workflow_file_raises_with_guidance(self):
        mutex = _fresh_mutex()
        comfy = _FakeComfy()
        client = LocalFluxClient(
            comfyui_client=comfy,
            mutex=mutex,
            workflow_path="/does/not/exist/flux_still.json",
        )
        with self.assertRaises(FluxGenerationError) as cm:
            _run(client.generate("x", "/tmp/y.png"))
        self.assertIn("workflow", str(cm.exception).lower())
        self.assertIn("falls back", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
