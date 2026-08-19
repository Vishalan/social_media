"""Generated cinematic b-roll via MiniMax H3, running locally on the 3090.

Replaces the LTX-Video experiment, which was wired up, measured and disabled:
LTX produced a blue smear with no recognisable subject at any prompt length.
H3 on the same hardware produces coherent scenes — a data centre aisle with
racks and reflective floor, a face lit by a phone, hands on a keyboard.

WHAT IT COSTS, because this is the number that decides how it is used:
roughly 6.5 minutes per 3-second clip at 640x640 / 20 steps, using 21.7GB of
the 24GB card. That is the same order as an avatar segment, so generated
footage is a HERO SHOT — one per video — not a general b-roll type. The cap
lives in config, not here.

THREE THINGS THAT HAD TO BE RIGHT, each found the hard way:

* The community GGUF weights ship with a packaging marker appended past the
  declared end of every file ("L2P_bypass_<name>_<timestamp>", 57-72 bytes).
  Sizes match the hub metadata exactly, so nothing looks wrong, but safetensors
  refuses to load a file it cannot fully account for. See tools/fix_h3_markers.py.
* Encoding the negative prompt through a second MiniMaxH3ImageToVideo runs the
  text tower twice and OOMs the sampler. ConditioningZeroOut costs nothing.
* ComfyUI keeps the 19.9GB UNet resident between prompts, which is a feature
  everywhere except a 24GB card: the text encoder then has nowhere to go and
  every clip after the first fails. Free before each render.

LICENCE: MiniMax H3 Community License. The Applicable Territory excludes the
EU, UK, South Korea and the USA, and commercial use requires displaying
"MiniMax H3" prominently. Both are the operator's call, which is why this is
off by default.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HOST = os.environ.get("COMFY_HOST", "http://127.0.0.1:8188")
COMFY_ROOT = os.environ.get("COMFY_ROOT", "/home/vishalan/ComfyUI")

UNET = "MiniMax-H3-FL2VA-Q4_K_M.gguf"
CLIP = "qwen3vl_32b_minimax_h3-Q4_K_M.gguf"
VAE = "minimax_h3_video_vae_fp16.safetensors"

# Generated on-screen lettering is always garbled, and fake words undermine a
# video whose whole claim is that the facts are real. Our typography layer owns
# every word the viewer reads.
NEGATIVE_HINT = ("no text, no letters, no words, no captions, no logos, "
                 "no watermark, no deformed hands")


class H3Error(RuntimeError):
    """Raised when a clip cannot be generated."""


def _post(path: str, payload: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(
        f"{HOST}{path}", json.dumps(payload).encode(),
        {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"{}")


def available() -> bool:
    """Whether ComfyUI is up with the H3 weights loaded."""
    try:
        urllib.request.urlopen(f"{HOST}/system_stats", timeout=10).read()
    except Exception:
        return False
    for sub, name in (("unet", UNET), ("text_encoders", CLIP), ("vae", VAE)):
        if not Path(COMFY_ROOT, "models", sub, name).is_file():
            logger.info("H3 unavailable: %s/%s missing", sub, name)
            return False
    return True


def _free_vram() -> None:
    try:
        _post("/free", {"unload_models": True, "free_memory": True})
        time.sleep(3)
    except Exception as exc:                        # noqa: BLE001 — best effort
        logger.debug("free failed: %s", exc)


def _graph(*, prompt: str, width: int, height: int, length: int, steps: int,
           cfg: float, seed: int, first_frame: Optional[str]) -> dict:
    g: dict = {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": UNET}},
        "2": {"class_type": "MiniMaxH3SigmaShift",
              "inputs": {"model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "3": {"class_type": "CLIPLoaderGGUF",
              "inputs": {"clip_name": CLIP, "type": "minimax"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "5": {"class_type": "MiniMaxH3ImageToVideo",
              "inputs": {"clip": ["3", 0], "vae": ["4", 0], "prompt": prompt,
                         "width": width, "height": height, "length": length}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
        "7": {"class_type": "KSampler",
              "inputs": {"model": ["2", 0], "positive": ["5", 0], "negative": ["6", 0],
                         "latent_image": ["5", 1], "seed": seed, "steps": steps,
                         "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
                         "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["4", 0]}},
        "9": {"class_type": "SaveWEBM",
              "inputs": {"images": ["8", 0], "filename_prefix": "h3",
                         "codec": "vp9", "fps": 24.0, "crf": 24.0}},
    }
    if first_frame:
        g["10"] = {"class_type": "LoadImage", "inputs": {"image": first_frame}}
        g["11"] = {"class_type": "ImageScale",
                   "inputs": {"image": ["10", 0], "width": width, "height": height,
                              "upscale_method": "lanczos", "crop": "center"}}
        g["5"]["inputs"]["first_frame"] = ["11", 0]
    return g


def stage_first_frame(image_path: str) -> str:
    """Copy an artifact into ComfyUI's input dir and return its bare name.

    LoadImage resolves names against ComfyUI's own input directory, so an
    absolute path from our run dir does not work.
    """
    src = Path(image_path)
    if not src.is_file():
        raise H3Error(f"first frame {image_path} does not exist")
    dest_dir = Path(COMFY_ROOT, "input")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"ff_{src.stem}{src.suffix}"
    shutil.copy(src, dest)
    return dest.name


def render(*, scene: str, out_path: str, duration_s: float = 3.0,
           width: int = 1080, height: int = 998, fps: int = 25,
           gen_size: int = 640, steps: int = 20, cfg: float = 5.0,
           seed: int = 11, first_frame: Optional[str] = None,
           timeout_s: int = 2400) -> str:
    """Generate one clip and conform it to the content panel.

    Args:
        scene: a described SCENE, not a concept. "A dark data centre aisle,
            racks receding, blue status lights" works; "the future of AI" does
            not.
        first_frame: optional path to an artifact the clip should start from —
            a source logo card or a page capture — so the motion is grounded in
            something real from the story.
    """
    if not scene.strip():
        raise H3Error("ai_scene needs a scene description")

    staged = stage_first_frame(first_frame) if first_frame else None
    length = int(duration_s * 24) + 1
    prompt = f"{scene.strip()}. {NEGATIVE_HINT}"

    _free_vram()
    pid = _post("/prompt", {
        "prompt": _graph(prompt=prompt, width=gen_size, height=gen_size,
                         length=length, steps=steps, cfg=cfg, seed=seed,
                         first_frame=staged),
        "client_id": str(uuid.uuid4()),
    })["prompt_id"]
    logger.info("H3 generating %.1fs: %s", duration_s, scene[:70])

    t0 = time.time()
    produced = None
    while time.time() - t0 < timeout_s:
        hist = json.loads(urllib.request.urlopen(
            f"{HOST}/history/{pid}", timeout=30).read())
        entry = hist.get(pid)
        if entry:
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise H3Error(f"generation failed: {json.dumps(status)[:400]}")
            if status.get("completed"):
                for out in entry["outputs"].values():
                    for f in out.get("images", []) + out.get("videos", []):
                        cand = Path(COMFY_ROOT, "output",
                                    f.get("subfolder", ""), f["filename"])
                        if cand.is_file():
                            produced = str(cand)
                break
        time.sleep(5)

    if not produced:
        raise H3Error(f"no output after {time.time() - t0:.0f}s")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", produced,
         "-vf", (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                 f"crop={width}:{height},fps={fps}"),
         "-t", f"{duration_s:.3f}", "-an",
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out_path],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise H3Error(f"conform failed: {r.stderr[-300:]}")
    logger.info("H3 clip in %.0fs -> %s", time.time() - t0, Path(out_path).name)
    return out_path
