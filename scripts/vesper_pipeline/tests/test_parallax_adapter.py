"""Tests for :class:`VesperParallaxAdapter`.

ComfyUI + GPU mutex stubbed; verifies mutex acquisition, workflow
loading, parameter substitution contract, error paths.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from video_gen.gpu_mutex import (  # noqa: E402
    FakeMutexBackend,
    GpuMutexAcquireTimeout,
    GpuPlaneMutex,
)
from vesper_pipeline.parallax_adapter import (  # noqa: E402
    ParallaxGenerationError,
    VesperParallaxAdapter,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _fresh_mutex() -> GpuPlaneMutex:
    return GpuPlaneMutex(FakeMutexBackend())


def _write_stub_workflow(tmp: str) -> str:
    wf = {
        "1": {
            "inputs": {
                "image": "{{input_image}}",
                "motion": "{{motion_mode}}",
                "duration": "{{duration_s}}",
            },
            "class_type": "DepthParallax",
        }
    }
    path = os.path.join(tmp, "depth_parallax.json")
    with open(path, "w") as f:
        json.dump(wf, f)
    return path


class _FakeComfy:
    def __init__(self, *, download_files: list[str] | None = None,
                 run_raises=None, download_raises=None):
        self.download_files = download_files if download_files is not None else []
        self.run_raises = run_raises
        self.download_raises = download_raises
        self.run_calls: List[dict] = []
        self.download_calls: List[dict] = []

    async def run_workflow(self, workflow, params=None, wait_for_completion=True):
        self.run_calls.append({"workflow": workflow, "params": params})
        if self.run_raises is not None:
            raise self.run_raises
        return "prompt-xyz"

    async def download_output(self, prompt_id, output_dir, output_filename=None):
        self.download_calls.append({
            "prompt_id": prompt_id,
            "output_dir": output_dir,
            "output_filename": output_filename,
        })
        if self.download_raises is not None:
            raise self.download_raises
        return list(self.download_files)


class HappyPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vp-parallax-")
        self.workflow_path = _write_stub_workflow(self.tmp)
        self.still_path = os.path.join(self.tmp, "s.png")
        with open(self.still_path, "wb") as f:
            f.write(b"png-stub")
        self.out_path = os.path.join(self.tmp, "par.mp4")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_animate_submits_workflow_with_correct_params(self):
        mutex = _fresh_mutex()
        comfy = _FakeComfy(download_files=[self.out_path])
        adapter = VesperParallaxAdapter(
            comfyui_client=comfy,
            mutex=mutex,
            workflow_path=self.workflow_path,
        )
        result = _run(adapter.animate(
            self.still_path, self.out_path,
            duration_s=3.5, motion_mode="orbit_slight",
        ))
        self.assertEqual(result, self.out_path)
        self.assertEqual(len(comfy.run_calls), 1)
        params = comfy.run_calls[0]["params"]
        self.assertEqual(params["input_image"], self.still_path)
        self.assertEqual(params["duration_s"], 3.5)
        self.assertEqual(params["motion_mode"], "orbit_slight")
        self.assertEqual(params["output_fps"], 30)
        self.assertIn("seed", params)

    def test_motion_mode_defaults_to_push_in_2d(self):
        mutex = _fresh_mutex()
        comfy = _FakeComfy(download_files=[self.out_path])
        adapter = VesperParallaxAdapter(
            comfyui_client=comfy,
            mutex=mutex,
            workflow_path=self.workflow_path,
        )
        _run(adapter.animate(
            self.still_path, self.out_path, duration_s=3.0,
        ))
        self.assertEqual(
            comfy.run_calls[0]["params"]["motion_mode"],
            "push_in_2d",
        )

    def test_mutex_released_after_success(self):
        mutex = _fresh_mutex()
        comfy = _FakeComfy(download_files=[self.out_path])
        adapter = VesperParallaxAdapter(
            comfyui_client=comfy,
            mutex=mutex,
            workflow_path=self.workflow_path,
        )
        _run(adapter.animate(
            self.still_path, self.out_path, duration_s=3.0,
        ))
        # Mutex is free again.
        after = mutex.acquire(caller="after", timeout_s=1.0)
        self.assertEqual(after.caller, "after")


class FailurePathTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vp-parallax-err-")
        self.workflow_path = _write_stub_workflow(self.tmp)
        self.still_path = os.path.join(self.tmp, "s.png")
        with open(self.still_path, "wb") as f:
            f.write(b"png-stub")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_empty_still_path_raises(self):
        adapter = VesperParallaxAdapter(
            comfyui_client=_FakeComfy(),
            mutex=_fresh_mutex(),
            workflow_path=self.workflow_path,
        )
        with self.assertRaises(ParallaxGenerationError):
            _run(adapter.animate("", "/tmp/out.mp4", duration_s=3.0))

    def test_nonexistent_still_raises(self):
        adapter = VesperParallaxAdapter(
            comfyui_client=_FakeComfy(),
            mutex=_fresh_mutex(),
            workflow_path=self.workflow_path,
        )
        with self.assertRaises(ParallaxGenerationError):
            _run(adapter.animate(
                "/does/not/exist.png", "/tmp/out.mp4", duration_s=3.0,
            ))

    def test_mutex_timeout_bubbles_up_unchanged(self):
        """Plan Unit 10 contingency: the pipeline degrades the beat to
        Ken Burns when the mutex times out. Must NOT wrap as
        ParallaxGenerationError."""
        mutex = _fresh_mutex()
        _ = mutex.acquire(caller="hog")  # lock held; adapter can't acquire
        adapter = VesperParallaxAdapter(
            comfyui_client=_FakeComfy(),
            mutex=mutex,
            workflow_path=self.workflow_path,
            mutex_timeout_s=0.1,
        )
        with self.assertRaises(GpuMutexAcquireTimeout):
            _run(adapter.animate(
                self.still_path, "/tmp/out.mp4", duration_s=3.0,
            ))

    def test_comfyui_run_error_becomes_parallax_generation_error(self):
        comfy = _FakeComfy(run_raises=RuntimeError("ComfyUI 500"))
        adapter = VesperParallaxAdapter(
            comfyui_client=comfy,
            mutex=_fresh_mutex(),
            workflow_path=self.workflow_path,
        )
        with self.assertRaises(ParallaxGenerationError) as cm:
            _run(adapter.animate(
                self.still_path, "/tmp/out.mp4", duration_s=3.0,
            ))
        self.assertIn("ComfyUI", str(cm.exception))

    def test_missing_workflow_file_raises_with_runbook_pointer(self):
        adapter = VesperParallaxAdapter(
            comfyui_client=_FakeComfy(),
            mutex=_fresh_mutex(),
            workflow_path="/does/not/exist.json",
        )
        with self.assertRaises(ParallaxGenerationError) as cm:
            _run(adapter.animate(
                self.still_path, "/tmp/out.mp4", duration_s=3.0,
            ))
        # Runbook pointer for the operator who trips this.
        self.assertIn("runbook", str(cm.exception).lower())

    def test_no_output_files_raises(self):
        comfy = _FakeComfy(download_files=[])
        adapter = VesperParallaxAdapter(
            comfyui_client=comfy,
            mutex=_fresh_mutex(),
            workflow_path=self.workflow_path,
        )
        with self.assertRaises(ParallaxGenerationError) as cm:
            _run(adapter.animate(
                self.still_path, "/tmp/out.mp4", duration_s=3.0,
            ))
        self.assertIn("no output", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
