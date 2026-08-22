"""
CommonCreed Chatterbox sidecar — HTTP TTS server.

Exposes two endpoints:

  POST /tts
    body: {
      "text": str,
      "reference_audio_path": str | null,   # path inside the container
      "exaggeration": float = 0.5,           # 0.0 neutral → 1.0 dramatic
      "cfg_weight": float = 0.5,             # lower = slower, more deliberate
      "temperature": float = 0.8,
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
    # Stock ChatterboxTTS defaults are exaggeration=0.5, cfg_weight=0.5. The
    # service previously defaulted exaggeration to 0.3 — FLATTER than stock —
    # and never passed cfg_weight at all, leaving it at whatever the library
    # chose. The two interact by design: higher exaggeration speeds speech up,
    # lower cfg_weight slows it into something more deliberate. Vendor-
    # documented expressive preset is exaggeration 0.7 / cfg_weight 0.3.
    exaggeration: float = Field(default=0.5, ge=0.0, le=1.0)
    cfg_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    temperature: float = Field(default=0.8, ge=0.05, le=1.5)
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

    # Resolve the reference against REFS_ROOT.
    #
    # This was the single most damaging bug in the pipeline. The old code did
    # `Path(ref).exists()` on a BARE FILENAME, which resolves against the
    # container's working directory (/app) rather than the mounted refs volume
    # (/app/refs). It therefore never found any reference, set ref=None, and
    # generated with Chatterbox's DEFAULT VOICE — logging only a warning.
    # Every video produced up to 2026-08-17 used a stranger's voice while the
    # config, the client and the request payload all correctly named the
    # owner's clip.
    #
    # Silent degradation is the whole problem: a missing reference is now a
    # 400, because generating a video in the wrong voice is far worse than
    # failing loudly.
    ref = req.reference_audio_path
    if ref:
        candidate = Path(ref)
        if not candidate.is_absolute():
            candidate = REFS_ROOT / ref
        try:
            resolved = candidate.resolve()
            resolved.relative_to(REFS_ROOT.resolve())
        except (ValueError, OSError):
            raise HTTPException(
                status_code=400,
                detail=f"reference_audio_path {ref!r} escapes {REFS_ROOT}")
        if not resolved.exists():
            raise HTTPException(
                status_code=400,
                detail=(f"reference_audio_path {ref!r} not found under "
                        f"{REFS_ROOT}. Refusing to generate in the wrong voice; "
                        f"see /refs/list for what is available."))
        ref = str(resolved)

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
            cfg_weight=req.cfg_weight,
            temperature=req.temperature,
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



# ─── voice blending ──────────────────────────────────────────────────────────
#
# Chatterbox conditions generation on TWO separable things, and they can be
# sourced independently:
#
#   * `t3.speaker_emb` and `gen["embedding"]` are continuous speaker-identity
#     vectors — WHO is talking. Being continuous, they interpolate.
#   * `t3.cond_prompt_speech_tokens`, `gen["prompt_token"]` and
#     `gen["prompt_feat"]` are discrete tokens and frame features lifted from
#     the reference — HOW they talk: the cadence, the settledness, the way
#     consonants land. Discrete things do not average; blending token IDs
#     produces a third token that means something unrelated.
#
# So the blend takes identity as a weighted mix and delivery wholesale from
# whichever reference is named. That maps onto the actual request: keep one
# voice's pronunciation and calm, dial the other's identity back in.

class BlendRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)
    ref_a: str
    ref_b: str
    # Weight on B for the identity vectors. 0.0 = pure A, 1.0 = pure B.
    alpha: float = Field(default=0.5, ge=0.0, le=1.0)
    # Which reference supplies the discrete delivery prompts.
    prompt_from: str = Field(default="b", pattern="^[ab]$")
    exaggeration: float = Field(default=0.5, ge=0.0, le=1.0)
    cfg_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    temperature: float = Field(default=0.8, ge=0.05, le=1.5)
    output_filename: Optional[str] = Field(default=None, max_length=200)


def _resolve_ref(ref: str) -> str:
    candidate = Path(ref)
    if not candidate.is_absolute():
        candidate = REFS_ROOT / ref
    try:
        resolved = candidate.resolve()
        resolved.relative_to(REFS_ROOT.resolve())
    except (ValueError, OSError):
        raise HTTPException(status_code=400,
                            detail=f"reference {ref!r} escapes {REFS_ROOT}")
    if not resolved.exists():
        raise HTTPException(status_code=400,
                            detail=f"reference {ref!r} not found under {REFS_ROOT}")
    return str(resolved)


def _slerp(a, b, t: float):
    """Interpolate along the sphere, not through it.

    Voice-encoder embeddings are L2-normalised, so they live on a unit sphere.
    A straight linear mix of two unit vectors is SHORTER than either — at
    alpha 0.5 between two fairly different speakers it can lose a noticeable
    fraction of its length, which reads as weaker conditioning and a blander
    voice, exactly where the blend is supposed to be most interesting.
    Spherical interpolation keeps the length and spaces the steps evenly, so
    alpha 0.5 sounds halfway rather than washed out.
    """
    import torch as _t
    a_n = a / a.norm(dim=-1, keepdim=True).clamp_min(1e-9)
    b_n = b / b.norm(dim=-1, keepdim=True).clamp_min(1e-9)
    dot = (a_n * b_n).sum(-1, keepdim=True).clamp(-1.0, 1.0)
    omega = _t.acos(dot)
    sin_o = _t.sin(omega)
    mag = (1 - t) * a.norm(dim=-1, keepdim=True) + t * b.norm(dim=-1, keepdim=True)
    if bool((sin_o.abs() < 1e-6).all()):
        # Nearly parallel: slerp is numerically unstable and lerp is exact.
        out = (1 - t) * a_n + t * b_n
        return out / out.norm(dim=-1, keepdim=True).clamp_min(1e-9) * mag
    out = (_t.sin((1 - t) * omega) / sin_o) * a_n + (_t.sin(t * omega) / sin_o) * b_n
    return out * mag



def _snapshot_conds(conds):
    """A detached copy of a Conditionals.

    copy.deepcopy() cannot be used: the tensors come out of inference, so they
    are non-leaf and torch refuses to deepcopy them. Detaching and cloning each
    tensor gives an independent snapshot, which is what is actually needed —
    preparing the second reference overwrites model.conds in place, so without
    a real copy the first reference is simply lost.
    """
    from chatterbox.models.t3.modules.cond_enc import T3Cond
    t3 = T3Cond(
        speaker_emb=conds.t3.speaker_emb.detach().clone(),
        cond_prompt_speech_tokens=(
            None if conds.t3.cond_prompt_speech_tokens is None
            else conds.t3.cond_prompt_speech_tokens.detach().clone()),
        emotion_adv=(None if conds.t3.emotion_adv is None
                     else conds.t3.emotion_adv.detach().clone()),
    )
    gen = {k: (v.detach().clone() if torch.is_tensor(v) else v)
           for k, v in conds.gen.items()}
    return type(conds)(t3, gen)


@app.post("/tts_blend")
def tts_blend(req: BlendRequest):
    text = _clean_text(req.text)
    if not text:
        raise HTTPException(status_code=400, detail="text empty after preprocessing")
    a_path, b_path = _resolve_ref(req.ref_a), _resolve_ref(req.ref_b)

    filename = req.output_filename or f"blend_{int(time.time())}_{uuid.uuid4().hex[:8]}.wav"
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="output_filename must not contain / or ..")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_ROOT / filename

    try:
        model = _get_model()
        model.prepare_conditionals(a_path, exaggeration=req.exaggeration)
        conds_a = _snapshot_conds(model.conds)
        model.prepare_conditionals(b_path, exaggeration=req.exaggeration)
        conds_b = _snapshot_conds(model.conds)

        base = conds_b if req.prompt_from == "b" else conds_a
        other = conds_a if req.prompt_from == "b" else conds_b
        # alpha is always the weight on B, whichever supplied the prompts.
        t = req.alpha if req.prompt_from == "a" else (1.0 - req.alpha)

        from chatterbox.models.t3.modules.cond_enc import T3Cond
        blended = _slerp(base.t3.speaker_emb, other.t3.speaker_emb, t)
        base.t3 = T3Cond(
            speaker_emb=blended,
            cond_prompt_speech_tokens=base.t3.cond_prompt_speech_tokens,
            emotion_adv=req.exaggeration * torch.ones(1, 1, 1),
        ).to(device=model.device)
        if "embedding" in base.gen and "embedding" in other.gen:
            base.gen["embedding"] = _slerp(base.gen["embedding"], other.gen["embedding"], t)

        model.conds = base
        t0 = time.time()
        wav = model.generate(text, audio_prompt_path=None,
                             exaggeration=req.exaggeration,
                             cfg_weight=req.cfg_weight,
                             temperature=req.temperature)
        torchaudio.save(str(output_path), wav.cpu(), model.sr)
        logger.info("blend OK: alpha=%.2f prompt_from=%s out=%s gen_ms=%.0f",
                    req.alpha, req.prompt_from, output_path.name,
                    (time.time() - t0) * 1000)
        # The blended conditionals must not leak into the next plain /tts call.
        model.conds = None
        return {"output_path": str(output_path), "sample_rate": model.sr}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("blend failed")
        model = _model
        if model is not None:
            model.conds = None
        raise HTTPException(status_code=500, detail=f"blend failed: {exc}")

@app.post("/unload")
def unload():
    """Drop the TTS model and release its VRAM.

    The 3090 has 24 GB and MiniMax-H3 needs 21.7 GB of it. Chatterbox loads
    lazily and then stays resident for the life of the process, so by the time
    the b-roll stage runs its few GB are idle but still held, and the video
    generation fails on an out-of-memory error that surfaces as an opaque
    ComfyUI "status: error". The clip is simply dropped and the video ships
    with one fewer shot, which is how generated footage quietly disappeared
    from the output entirely.

    The next /tts call reloads (~10s), which is a fair price for the shot.
    """
    global _model
    had = _model is not None
    _model = None
    try:
        import gc
        gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
    except Exception:                              # noqa: BLE001 — best effort
        pass
    logger.info("unload: model_was_loaded=%s", had)
    return {"unloaded": had}


if __name__ == "__main__":
    import uvicorn

    logger.info("CommonCreed Chatterbox sidecar starting on :%d (device=%s)", PORT, DEVICE)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
