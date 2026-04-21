"""
CommonCreed Chatterbox sidecar — HTTP TTS server.

Exposes two endpoints:

  POST /tts
    body: {
      "text": str,
      "reference_audio_path": str | null,   # path inside the container
      "exaggeration": float = 0.3,           # 0.0 neutral → 1.0 dramatic
      "output_filename": str | null,         # defaults to timestamp.wav
    }
    200: { output_path: str, duration_ms: float, sample_rate: int }
    400: { error: str }  — validation
    500: { error: str }  — generation failed

  GET /healthz
    200: { "ok": true, "model_loaded": bool, "device": str }

The model is loaded lazily on first /tts call so container startup is fast
(health check clears in <1s). First /tts adds ~10s for the model load; every
call after that is ~18s per minute of speech on RTX 3090.

Reference audio paths are resolved inside the container. The sidecar mounts
/opt/commoncreed/assets at /app/refs so a client that POSTs
"reference_audio_path": "/app/refs/vishalan_voice_ref.wav" gets the host file.

Output WAVs are written under /app/output/<timestamp>.wav on the shared
commoncreed_output volume so the Python sidecar can pick them up.
"""
from __future__ import annotations

import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional

import torch
import torchaudio
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("chatterbox-sidecar")

PORT = int(os.environ.get("CHATTERBOX_PORT", "7777"))
OUTPUT_ROOT = Path(os.environ.get("CHATTERBOX_OUTPUT_ROOT", "/app/output"))
REFS_ROOT = Path(os.environ.get("CHATTERBOX_REFS_ROOT", "/app/refs"))
DEVICE = os.environ.get("CHATTERBOX_DEVICE", "cuda")

app = FastAPI(title="CommonCreed Chatterbox", version="0.1.0")
_model = None


def _get_model():
    """Lazy-load. Populated on first /tts call."""
    global _model
    if _model is not None:
        return _model
    from chatterbox.tts import ChatterboxTTS  # noqa: import here to keep startup fast

    if DEVICE == "cuda" and not torch.cuda.is_available():
        logger.warning("CUDA requested but not available; falling back to CPU")
        effective = "cpu"
    else:
        effective = DEVICE
    logger.info("Loading Chatterbox model to %s...", effective)
    t0 = time.time()
    _model = ChatterboxTTS.from_pretrained(device=effective)
    logger.info("Chatterbox model loaded in %.1fs", time.time() - t0)
    return _model


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)
    reference_audio_path: Optional[str] = None
    exaggeration: float = Field(default=0.3, ge=0.0, le=1.0)
    output_filename: Optional[str] = Field(default=None, max_length=200)


class TTSResponse(BaseModel):
    output_path: str
    duration_ms: float
    sample_rate: int


def _clean_text(text: str) -> str:
    """Match the preprocessing that VoiceGenerator.generate does so both
    providers produce audio from the same text body."""
    text = re.sub(r"\[Pause\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bPause\.", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bPause\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[.*?\]", "", text)
    return " ".join(text.split())


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "model_loaded": _model is not None,
            "device": DEVICE,
            "cuda_available": torch.cuda.is_available(),
        }
    )


@app.get("/refs/list")
def refs_list() -> JSONResponse:
    """List every reference .wav file mounted under ``REFS_ROOT``.

    Returned paths are **relative** to the refs root (e.g.
    ``"vesper/archivist.wav"``), so pipeline pre-flight can check for a
    specific channel's reference without needing knowledge of the
    container mount point. The endpoint enables tiered error
    discrimination (Unit 8): if ``/healthz`` is healthy but the expected
    reference is missing from this listing, the caller classifies the
    failure as Vesper-only config-fail rather than sidecar-down.

    Path-traversal guard: refuse to descend into symlinks that resolve
    outside ``REFS_ROOT``.
    """
    entries: list[str] = []
    if not REFS_ROOT.exists():
        return JSONResponse(
            {"refs_root": str(REFS_ROOT), "entries": [], "exists": False}
        )
    try:
        real_root = REFS_ROOT.resolve()
        for path in REFS_ROOT.rglob("*.wav"):
            try:
                real_path = path.resolve()
            except OSError:
                continue
            # Reject any symlink that escapes the refs root.
            try:
                rel = real_path.relative_to(real_root)
            except ValueError:
                logger.warning(
                    "refs/list: skipping %s — resolves outside %s",
                    path, real_root,
                )
                continue
            entries.append(str(rel).replace(os.sep, "/"))
        entries.sort()
        return JSONResponse(
            {
                "refs_root": str(REFS_ROOT),
                "entries": entries,
                "exists": True,
            }
        )
    except Exception as exc:
        logger.exception("refs/list failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"refs/list failed: {exc}")


@app.post("/tts", response_model=TTSResponse)
def tts(req: TTSRequest) -> TTSResponse:
    text = _clean_text(req.text)
    if not text:
        raise HTTPException(status_code=400, detail="text empty after preprocessing")

    ref = req.reference_audio_path
    if ref and not Path(ref).exists():
        logger.warning("reference_audio_path %s not found; generating without cloning", ref)
        ref = None

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    filename = req.output_filename or f"chatterbox_{int(time.time())}_{uuid.uuid4().hex[:8]}.wav"
    # Prevent path traversal; the client only supplies a filename, not a path.
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="output_filename must not contain / or ..")
    output_path = OUTPUT_ROOT / filename

    try:
        model = _get_model()
        t0 = time.time()
        wav = model.generate(
            text,
            audio_prompt_path=ref,
            exaggeration=req.exaggeration,
        )
        torchaudio.save(str(output_path), wav.cpu(), model.sr)
        dur_ms = (time.time() - t0) * 1000
        logger.info(
            "tts OK: chars=%d ref=%s out=%s gen_ms=%.0f",
            len(text),
            "yes" if ref else "no",
            output_path.name,
            dur_ms,
        )
        return TTSResponse(
            output_path=str(output_path),
            duration_ms=dur_ms,
            sample_rate=model.sr,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("tts generation failed")
        raise HTTPException(status_code=500, detail=f"generation failed: {exc}")


if __name__ == "__main__":
    import uvicorn

    logger.info("CommonCreed Chatterbox sidecar starting on :%d (device=%s)", PORT, DEVICE)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
