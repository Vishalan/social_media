"""CommonCreed LatentSync sidecar — HTTP front for local avatar lip-sync.

Mirrors the Chatterbox service shape so the pipeline talks to both the same
way: a small FastAPI app, paths on shared volumes, no payload streaming.

Design note — every GPU job runs in a SUBPROCESS (see jobs.py). This server
never imports torch, so it holds no CUDA context and idles at ~0 MiB VRAM.
That is deliberate: Chatterbox loads in-process and pins 3.64 GB forever,
which OOM'd the first avatar render on 2026-08-16 when both wanted the GPU.

Endpoints
    GET  /healthz        liveness + whether weights are on disk
    GET  /clips/list     the gesture-clip library, with motion tags
    POST /lipsync        gesture clip + audio  -> lip-synced video
    POST /transcribe     audio -> word-level timestamps (GPU large-v3)
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("latentsync")

PORT = int(os.environ.get("LATENTSYNC_PORT", "7778"))
OUTPUT_ROOT = Path(os.environ.get("LATENTSYNC_OUTPUT", "/app/output"))
CLIPS_ROOT = Path(os.environ.get("LATENTSYNC_CLIPS", "/app/clips"))
WORK_ROOT = Path(os.environ.get("LATENTSYNC_WORK", "/app/work"))
CKPT = Path("/app/LatentSync/checkpoints")

# Generous: a 60s short is ~21 min of inference at the measured 21 s per second
# of video, and a cold run adds weight download on top.
JOB_TIMEOUT_S = int(os.environ.get("LATENTSYNC_TIMEOUT_S", "5400"))

for p in (OUTPUT_ROOT, WORK_ROOT):
    p.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="CommonCreed LatentSync", version="0.1.0")


# --------------------------------------------------------------------------
# subprocess bridge
# --------------------------------------------------------------------------
def _run_job(verb: str, payload: dict, timeout: int = JOB_TIMEOUT_S) -> dict:
    """Invoke jobs.py in a fresh process and parse its sentinel-delimited JSON."""
    cmd = [sys.executable, "-u", "/app/jobs.py", verb, json.dumps(payload)]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504,
                            detail=f"{verb} exceeded {timeout}s")
    elapsed = time.time() - t0

    if r.returncode != 0:
        tail = (r.stderr or "")[-1500:]
        logger.error("%s failed rc=%s: %s", verb, r.returncode, tail)
        raise HTTPException(status_code=500, detail=f"{verb} failed: {tail}")

    marker = "---RESULT---"
    if marker not in r.stdout:
        raise HTTPException(status_code=500,
                            detail=f"{verb} produced no result block")
    try:
        result = json.loads(r.stdout.split(marker, 1)[1].strip())
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500,
                            detail=f"{verb} result unparseable: {exc}")
    result["_elapsed_s"] = round(elapsed, 2)
    return result


def _safe_name(name: str) -> str:
    """Reject traversal. Callers pass bare filenames, never paths."""
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400,
                            detail="name must not contain path separators")
    return name


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------
class LipsyncRequest(BaseModel):
    # Either a clip from the library...
    clip: Optional[str] = Field(
        None, description="Filename in the gesture-clip library, e.g. 'clip_07.mp4'")
    # ...or an explicit path already visible to this container.
    video_path: Optional[str] = Field(
        None, description="Absolute path to a 25fps video with a frontal face")
    audio_path: str = Field(
        ..., description="Absolute path to 16kHz mono WAV, same duration as the video")
    output_filename: Optional[str] = Field(None, max_length=200)
    inference_steps: int = Field(20, ge=1, le=100)
    guidance_scale: float = Field(1.5, ge=0.0, le=10.0)
    seed: int = 1247


class LipsyncResponse(BaseModel):
    output_path: str
    generation_ms: float          # NOT the video duration -- see naming note below
    video_duration_s: float
    clip_used: str


class TranscribeRequest(BaseModel):
    audio_path: str
    model: str = Field("large-v3", description="faster-whisper model name")


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------
@app.get("/healthz")
def healthz() -> JSONResponse:
    unet = CKPT / "latentsync_unet.pt"
    return JSONResponse({
        "ok": True,
        "weights_present": unet.exists(),
        "clips_mounted": CLIPS_ROOT.exists(),
        # This server holds no CUDA context by design; VRAM is only ever
        # occupied for the lifetime of a job subprocess.
        "holds_cuda_context": False,
    })


@app.get("/clips/list")
def clips_list() -> JSONResponse:
    """The gesture-clip library, with motion tags if a manifest is present."""
    if not CLIPS_ROOT.exists():
        return JSONResponse({"clips": [], "manifest": None})
    manifest_path = CLIPS_ROOT / "manifest.json"
    manifest = None
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            logger.warning("manifest.json present but unparseable")
    clips = sorted(p.name for p in CLIPS_ROOT.glob("*.mp4"))
    return JSONResponse({"clips": clips, "manifest": manifest})


@app.post("/lipsync", response_model=LipsyncResponse)
def lipsync(req: LipsyncRequest) -> LipsyncResponse:
    if bool(req.clip) == bool(req.video_path):
        raise HTTPException(status_code=400,
                            detail="pass exactly one of 'clip' or 'video_path'")

    if req.clip:
        video_path = CLIPS_ROOT / _safe_name(req.clip)
        clip_used = req.clip
    else:
        video_path = Path(req.video_path)
        clip_used = video_path.name
    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"video not found: {video_path}")

    audio_path = Path(req.audio_path)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"audio not found: {audio_path}")

    filename = _safe_name(req.output_filename or f"lipsync_{uuid.uuid4().hex[:8]}.mp4")
    if not filename.endswith(".mp4"):
        filename += ".mp4"
    out_path = OUTPUT_ROOT / filename

    result = _run_job("lipsync", {
        "video_path": str(video_path),
        "audio_path": str(audio_path),
        "out_path": str(out_path),
        "steps": req.inference_steps,
        "guidance": req.guidance_scale,
        "seed": req.seed,
    })

    dur = _probe_duration(out_path)
    logger.info("lipsync OK clip=%s out=%s gen=%.1fs dur=%.2fs",
                clip_used, filename, result["_elapsed_s"], dur)
    return LipsyncResponse(
        output_path=str(out_path),
        # Named generation_ms, not duration_ms, on purpose: the Chatterbox
        # service returns wall-clock under the name `duration_ms` next to
        # `sample_rate`, which reads as audio length and is off by ~2.5x.
        generation_ms=result["_elapsed_s"] * 1000.0,
        video_duration_s=dur,
        clip_used=clip_used,
    )


@app.post("/transcribe")
def transcribe(req: TranscribeRequest) -> JSONResponse:
    if not Path(req.audio_path).exists():
        raise HTTPException(status_code=404, detail=f"audio not found: {req.audio_path}")
    result = _run_job("transcribe", {
        "audio_path": req.audio_path,
        "model_name": req.model,
    }, timeout=1800)
    logger.info("transcribe OK model=%s words=%d gen=%.1fs",
                req.model, len(result.get("words", [])), result["_elapsed_s"])
    return JSONResponse(result)


@app.post("/warm")
def warm() -> JSONResponse:
    """Pre-download weights so the first real request isn't paying for it."""
    return JSONResponse(_run_job("warm", {}, timeout=3600))


def _probe_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
            capture_output=True, text=True, timeout=30)
        return round(float(r.stdout.strip()), 3)
    except Exception:
        return 0.0


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
