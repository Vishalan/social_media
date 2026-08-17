"""Generated cinematic b-roll — for stories with nothing concrete to show.

The reference analysis found a lot of generated footage in the researcher video:
a wireframe human figure on a grid, a noir-lit man at a desk, hands cupping
light. It works there because the subject is a neural implant — abstract,
speculative, with no product page to point a camera at.

It is deliberately NOT a default type. For "X open-sourced its ranking
algorithm" the strongest visuals are the real repository, the real settings
page, the real licence badge; a moody stock-feeling shot of a person at a
laptop would be exactly the irrelevant filler that stock search already
supplied. So the director offers this only when a beat has no concrete artifact
behind it, and the capability gate enforces it.

Model choice: LTX-Video 2B, run through diffusers rather than ComfyUI.
Reasons, all from the avatar spike's measurements on this same 3090:

* LTX-2.3-22B peaks at 77 GB — impossible on 24 GB.
* Wan2.2-14B undistilled extrapolates to 13-19 h per minute of video; even the
  4-step Lightning LoRA is ~1.5-2.5 h per minute, so 5-8 min for a 3s clip.
* LTX-Video 2B generates a few seconds in well under a minute and needs no
  ComfyUI server to babysit.

Renders in a SUBPROCESS so the CUDA context dies with it — the same discipline
the LatentSync service uses, and for the same reason: the pipeline runs other
GPU work and cannot afford a leaked allocation.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AiVideoError(RuntimeError):
    """Raised when generated footage cannot be produced."""


# The venv carrying torch for this GPU. The pipeline itself runs on system
# python, which has no torch — see the sidecar's own CPU-only constraint.
# The StableAvatar venv: torch 2.7.0+cu128, created with stdlib venv so it has
# pip. venv_ls was built by uv and has no pip binary, which broke the first
# install attempt.
_TORCH_PYTHON = os.environ.get(
    "AIVIDEO_PYTHON", "/home/vishalan/avatar-spike/venv/bin/python")

_WORKER = r'''
import json, sys, torch
from diffusers import LTXPipeline
from diffusers.utils import export_to_video

prompt, negative, out, w, h, nframes, steps, seed = sys.argv[1:9]
w, h, nframes, steps, seed = int(w), int(h), int(nframes), int(steps), int(seed)

pipe = LTXPipeline.from_pretrained("Lightricks/LTX-Video",
                                   torch_dtype=torch.bfloat16)
pipe.to("cuda")
# Slicing keeps the VAE decode inside 24 GB at 1080-wide output.
pipe.vae.enable_slicing()
pipe.vae.enable_tiling()

frames = pipe(
    prompt=prompt,
    negative_prompt=negative,
    width=w, height=h,
    num_frames=nframes,
    num_inference_steps=steps,
    generator=torch.Generator("cuda").manual_seed(seed),
).frames[0]
export_to_video(frames, out, fps=24)
print("AIVIDEO_OK")
'''

# Shared negative prompt. Text is the important one: generated on-screen text is
# always garbled, and a b-roll clip with fake words in it undermines a video
# whose whole claim is that the facts are real.
_NEGATIVE = ("worst quality, blurry, jittery, distorted, watermark, "
             "text, letters, words, captions, subtitles, logos, "
             "deformed hands, extra limbs, oversaturated")


def available() -> bool:
    """Whether generated footage can be produced on this host."""
    if not os.path.exists(_TORCH_PYTHON):
        return False
    probe = subprocess.run(
        [_TORCH_PYTHON, "-c",
         "import diffusers, torch; "
         "from diffusers import LTXPipeline; "
         "print(torch.cuda.is_available())"],
        capture_output=True, text=True)
    return probe.returncode == 0 and "True" in probe.stdout


def build_ai_clip(*, prompt: str, out_path: str, duration_s: float,
                  width: int = 1080, height: int = 998, fps: int = 25,
                  seed: int = 7, steps: int = 30,
                  style_suffix: str = "") -> str:
    """Generate one cinematic clip from a text prompt.

    Args:
        prompt: what to show. Should describe a SCENE, not a concept — "a
            wireframe human figure rotating on a dark grid" works, "the future
            of AI" does not.
        duration_s: target length; LTX works in multiples of 8 frames plus one.
        style_suffix: appended to keep a consistent grade across a video.
    """
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    # LTX requires num_frames % 8 == 1, and dimensions divisible by 32.
    want = max(9, int(duration_s * 24))
    nframes = ((want - 1) // 8) * 8 + 1
    gen_w = (width // 32) * 32
    gen_h = (height // 32) * 32

    full = f"{prompt.strip()}. {style_suffix}".strip()
    logger.info("Generating %d frames at %dx%d: %s", nframes, gen_w, gen_h,
                prompt[:90])

    raw = str(Path(out_path).with_name(Path(out_path).stem + "_raw.mp4"))
    r = subprocess.run(
        [_TORCH_PYTHON, "-c", _WORKER, full, _NEGATIVE, raw,
         str(gen_w), str(gen_h), str(nframes), str(steps), str(seed)],
        capture_output=True, text=True, timeout=1800)
    if "AIVIDEO_OK" not in (r.stdout or "") or not os.path.exists(raw):
        raise AiVideoError(
            f"generation failed: {(r.stderr or r.stdout or '')[-400:]}")

    # Conform to the panel: LTX renders at 24fps and its own dimensions.
    conform = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", raw,
         "-vf", (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                 f"crop={width}:{height},fps={fps}"),
         "-t", f"{duration_s:.3f}", "-an",
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out_path],
        capture_output=True, text=True)
    if conform.returncode != 0:
        raise AiVideoError(f"conform failed: {conform.stderr[-300:]}")
    logger.info("Generated %s", Path(out_path).name)
    return out_path
