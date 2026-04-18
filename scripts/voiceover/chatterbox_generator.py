"""
Chatterbox TTS client — talks to the `commoncreed_chatterbox` HTTP sidecar.

The heavy lifting (torch, CUDA, model weights) lives in the sidecar container
at deploy/chatterbox/. This class is just a thin HTTP client that POSTs text
and writes the resulting WAV to the requested output path.

Drop-in alternative to VoiceGenerator — same generate(text, output_path)
signature. Voice cloning identity comes from the reference audio file path,
which must be readable from inside the chatterbox container (the sidecar
mounts /opt/commoncreed/assets/ at /app/refs/).

Usage::

    gen = ChatterboxVoiceGenerator(
        reference_audio="/app/refs/voice_ref.wav",
        endpoint="http://commoncreed_chatterbox:7777",
    )
    gen.generate("Hello world", "output/voice.wav")
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class ChatterboxVoiceGenerator:
    """HTTP client for the Chatterbox TTS sidecar."""

    def __init__(
        self,
        reference_audio: Optional[str] = None,
        endpoint: Optional[str] = None,
        device: str = "cuda",
        request_timeout_s: int = 600,
    ):
        """
        Args:
            reference_audio: Path to a 10-30s reference WAV **as seen from
                inside the chatterbox container** (typically under /app/refs/).
                Falls back to CHATTERBOX_REFERENCE_AUDIO env var.
            endpoint: Base URL of the chatterbox sidecar. Falls back to
                CHATTERBOX_ENDPOINT env var, then to the in-compose default
                http://commoncreed_chatterbox:7777.
            device: Historical — informational only. Device selection happens
                in the sidecar via CHATTERBOX_DEVICE. Kept in the constructor
                so the factory in __init__.py can keep a stable signature.
            request_timeout_s: Per-request timeout. 600s is generous; 1 min of
                speech generates in ~18s on RTX 3090, so 10 min covers a
                10-min long-form script with head-room.
        """
        self.reference_audio = reference_audio or os.getenv(
            "CHATTERBOX_REFERENCE_AUDIO", ""
        )
        self.endpoint = (
            endpoint
            or os.getenv("CHATTERBOX_ENDPOINT")
            or "http://commoncreed_chatterbox:7777"
        ).rstrip("/")
        self.device = device
        self.request_timeout_s = request_timeout_s
        logger.info(
            "ChatterboxVoiceGenerator initialized (endpoint=%s, ref=%s)",
            self.endpoint,
            "yes" if self.reference_audio else "no",
        )

    def generate(
        self,
        text: str,
        output_path: str,
        voice_id: Optional[str] = None,
        voice_name: str = "default",
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        exaggeration: float = 0.3,
    ) -> str:
        """Generate voice-over for the given text.

        Interface matches VoiceGenerator.generate() for drop-in compatibility.
        ``voice_id``, ``voice_name``, ``stability``, ``similarity_boost`` are
        accepted for signature parity with ElevenLabs but ignored — Chatterbox
        uses the reference audio for voice identity and has its own parameter
        model (exaggeration only).
        """
        if not text.strip():
            raise ValueError("text is empty")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # The sidecar writes to its own /app/output filesystem and returns the
        # path of that file. We hand it a deterministic filename so we know
        # where to pick it up, then copy it to the caller's output_path.
        # Path.name strips any directory traversal, so this is safe to forward.
        sidecar_filename = Path(output_path).name

        payload = {
            "text": text,
            "reference_audio_path": self.reference_audio or None,
            "exaggeration": float(exaggeration),
            "output_filename": sidecar_filename,
        }
        url = f"{self.endpoint}/tts"
        logger.info(
            "POST %s chars=%d exag=%.1f timeout=%ds",
            url,
            len(text),
            exaggeration,
            self.request_timeout_s,
        )

        resp = requests.post(url, json=payload, timeout=self.request_timeout_s)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"chatterbox TTS failed (HTTP {resp.status_code}): {resp.text[:500]}"
            )
        data = resp.json()

        # The sidecar's output dir and the caller's are both mounted on the
        # commoncreed_output volume, so the path the sidecar reports is the
        # same file the caller sees. If the mounts differ, copy explicitly.
        generated = Path(data["output_path"])
        target = Path(output_path)
        if generated.resolve() != target.resolve():
            if generated.exists():
                shutil.copyfile(generated, target)
            else:
                raise RuntimeError(
                    f"chatterbox produced {generated} but it is not visible to the client"
                )

        logger.info(
            "chatterbox OK — wrote %s (gen %.1fs, sr=%d)",
            target,
            data.get("duration_ms", 0) / 1000.0,
            data.get("sample_rate", 0),
        )
        return str(target)

    def estimate_cost(self, text: str) -> dict:
        """Local generation — zero marginal cost."""
        return {
            "character_count": len(text),
            "chunks": 1,
            "estimated_cost_usd": 0.0,
            "pricing_note": "Local GPU generation via chatterbox sidecar.",
        }
