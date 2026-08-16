"""Subprocess entrypoints for GPU work.

Each function here is invoked as ``python -m jobs <verb> ...`` in a FRESH
process. That is the whole point: when the process exits the CUDA context dies
with it and VRAM returns to the GPU. The parent FastAPI server never imports
torch, so it never holds a CUDA context of its own.

Contrast with the Chatterbox service, which loads its model in-process and
pins 3.64 GB indefinitely — that behaviour OOM'd the first avatar render on
2026-08-16 and is the reason for this design.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

LATENTSYNC_DIR = Path("/app/LatentSync")
CACHE = Path(os.environ.get("LATENTSYNC_CACHE", "/root/.cache/latentsync"))
CKPT = LATENTSYNC_DIR / "checkpoints"


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def ensure_weights() -> None:
    """Download LatentSync weights into the persistent cache, then symlink.

    Only two files are needed for inference (upstream's own setup_env.sh
    downloads exactly these); the insightface auxiliary models fetch
    themselves on first face-detection call.
    """
    from huggingface_hub import hf_hub_download

    CACHE.mkdir(parents=True, exist_ok=True)
    CKPT.mkdir(parents=True, exist_ok=True)

    wanted = ["latentsync_unet.pt", "whisper/tiny.pt"]
    for rel in wanted:
        dest = CKPT / rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        _log(f"downloading {rel} ...")
        src = hf_hub_download(
            repo_id="ByteDance/LatentSync-1.6",
            filename=rel,
            cache_dir=str(CACHE / "hf"),
        )
        # Symlink rather than copy: the file is ~5 GB and the cache volume
        # already holds the only durable copy.
        if dest.is_symlink() or dest.exists():
            dest.unlink()
        dest.symlink_to(src)
        _log(f"ready {rel}")


def lipsync(video_path: str, audio_path: str, out_path: str,
            steps: int = 20, guidance: float = 1.5, seed: int = 1247) -> dict:
    """Run LatentSync inference. Returns a summary dict."""
    ensure_weights()
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "scripts.inference",
        "--unet_config_path", "configs/unet/stage2_512.yaml",
        "--inference_ckpt_path", "checkpoints/latentsync_unet.pt",
        "--inference_steps", str(steps),
        "--guidance_scale", str(guidance),
        "--seed", str(seed),
        "--enable_deepcache",
        "--video_path", video_path,
        "--audio_path", audio_path,
        "--video_out_path", out_path,
    ]
    _log("running: " + " ".join(cmd))
    r = subprocess.run(cmd, cwd=str(LATENTSYNC_DIR), capture_output=True, text=True)
    if r.returncode != 0:
        tail = (r.stderr or "")[-2000:]
        raise RuntimeError(f"latentsync inference failed rc={r.returncode}: {tail}")
    if not Path(out_path).exists():
        raise RuntimeError("latentsync reported success but produced no file")
    return {"output_path": out_path, "steps": steps, "guidance": guidance}


def transcribe(audio_path: str, model_name: str = "large-v3") -> dict:
    """Word-level transcription on the GPU.

    The pipeline's own implementation is hardcoded to
    ``WhisperModel("base", device="cpu", compute_type="int8")`` — smallest
    model, on CPU, quantised — because the sidecar container has no GPU.
    Running it here instead is the whole reason this endpoint exists.
    """
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cuda", compute_type="float16",
                         download_root=str(CACHE / "whisper"))
    segments, info = model.transcribe(audio_path, word_timestamps=True)
    words = []
    seg_out = []
    for seg in segments:
        seg_out.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
        for w in (seg.words or []):
            words.append({"word": w.word.strip(), "start": w.start, "end": w.end})
    return {
        "language": info.language,
        "duration": info.duration,
        "model": model_name,
        "words": words,
        "segments": seg_out,
    }


def main() -> int:
    verb = sys.argv[1]
    payload = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    if verb == "lipsync":
        result = lipsync(**payload)
    elif verb == "transcribe":
        result = transcribe(**payload)
    elif verb == "warm":
        ensure_weights()
        result = {"ok": True}
    else:
        raise SystemExit(f"unknown verb {verb!r}")
    # Sentinel-delimited so the parent can parse cleanly past any library chatter.
    print("---RESULT---")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
