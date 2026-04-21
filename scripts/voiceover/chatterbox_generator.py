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
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

# Chatterbox single-shot generation caps around ~40s of audio (~1000 tokens).
# Scripts longer than that silently truncate. We chunk at sentence boundaries
# to stay well under that cap. 380 chars ≈ 25-30s of speech at typical pace,
# leaving headroom for punchier lines.
_MAX_CHARS_PER_CHUNK = 380


@dataclass(frozen=True)
class PreflightResult:
    """Outcome of :meth:`ChatterboxVoiceGenerator.check_ref_available`.

    Three discriminated states drive the tiered error-handling in
    plan System-Wide Impact #5:

      * ``ok``           — proceed with TTS.
      * ``ref_missing``  — the sidecar is healthy but this channel's
        reference is absent; abort THIS channel's run only.
      * ``sidecar_down`` — /refs/list transport failure or 5xx; abort
        BOTH pipelines' current runs.
    """

    status: Literal["ok", "ref_missing", "sidecar_down"]
    reason: str = ""


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

    @staticmethod
    def _chunk_text(text: str, max_chars: int = _MAX_CHARS_PER_CHUNK) -> List[str]:
        """Split text at sentence boundaries into chunks of at most max_chars.

        Chatterbox single-shot TTS caps around ~40s of audio. Long scripts
        silently truncate if not chunked, which is what was cutting the
        pipeline's voiceovers to 40s regardless of script length.
        """
        text = " ".join(text.split())  # normalize whitespace
        if not text:
            return []
        # Split on sentence-ending punctuation while keeping the punctuation.
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: List[str] = []
        current = ""
        for sent in sentences:
            if not sent:
                continue
            # Single sentence longer than the cap → hard-split on commas, then
            # as a last resort on word boundaries.
            if len(sent) > max_chars:
                pieces = re.split(r"(?<=,)\s+", sent)
                for piece in pieces:
                    while len(piece) > max_chars:
                        # Split at nearest word boundary ≤ max_chars.
                        cut = piece.rfind(" ", 0, max_chars)
                        if cut <= 0:
                            cut = max_chars
                        chunks.append(piece[:cut].strip())
                        piece = piece[cut:].strip()
                    if piece:
                        if len(current) + 1 + len(piece) <= max_chars:
                            current = (current + " " + piece).strip()
                        else:
                            if current:
                                chunks.append(current)
                            current = piece
                continue
            # Normal sentence — accumulate into current chunk up to the cap.
            if len(current) + 1 + len(sent) <= max_chars:
                current = (current + " " + sent).strip()
            else:
                if current:
                    chunks.append(current)
                current = sent
        if current:
            chunks.append(current)
        return chunks

    def _post_chunk(self, text: str, exaggeration: float, sidecar_filename: str) -> dict:
        payload = {
            "text": text,
            "reference_audio_path": self.reference_audio or None,
            "exaggeration": float(exaggeration),
            "output_filename": sidecar_filename,
        }
        url = f"{self.endpoint}/tts"
        resp = requests.post(url, json=payload, timeout=self.request_timeout_s)
        if resp.status_code >= 400:
            raise RuntimeError(
                f"chatterbox TTS failed (HTTP {resp.status_code}): {resp.text[:500]}"
            )
        return resp.json()

    # ─── Pre-flight + discovery ──────────────────────────────────────────────

    def list_refs(self, timeout_s: float = 5.0) -> list[str]:
        """Return the sidecar's list of mounted reference .wav paths.

        Relative to ``REFS_ROOT`` inside the container (e.g.
        ``"vesper/archivist.wav"``). Used by the pre-flight discriminator
        to distinguish "reference missing from volume" from "sidecar
        unreachable" before a full TTS call commits GPU time. Raises
        :class:`requests.RequestException` on transport failure.
        """
        url = f"{self.endpoint}/refs/list"
        resp = requests.get(url, timeout=timeout_s)
        resp.raise_for_status()
        data = resp.json()
        return list(data.get("entries") or [])

    def check_ref_available(
        self,
        expected_ref: str,
        *,
        timeout_s: float = 5.0,
    ) -> "PreflightResult":
        """Tiered pre-flight: does the sidecar have ``expected_ref`` mounted?

        Returns a :class:`PreflightResult` with three discriminated states
        so the caller can choose whether to abort the whole pipeline or
        just this channel's run (Unit 8 / System-Wide Impact #5):

          * ``status='sidecar_down'``  — /refs/list timed out or 5xx →
            abort both pipelines' current runs, alert owner.
          * ``status='ref_missing'``   — /refs/list OK but the expected
            path is not in the listing → abort this channel's run only,
            alert owner.
          * ``status='ok'``            — the reference is available;
            proceed with TTS.

        ``expected_ref`` is compared two ways: as a direct substring of
        the container path (``/app/refs/vesper/archivist.wav``) and as a
        matching relative path entry (``vesper/archivist.wav``). Either
        form is acceptable so callers can pass whichever they have.
        """
        try:
            entries = self.list_refs(timeout_s=timeout_s)
        except requests.RequestException as exc:
            logger.warning(
                "chatterbox /refs/list transport failure — classifying "
                "as sidecar_down: %s", exc,
            )
            return PreflightResult(status="sidecar_down", reason=str(exc))

        # Accept either the absolute container path or the relative entry.
        # Strip a leading "/app/refs/" from the expected ref before comparing
        # against the relative-path entries returned by the sidecar.
        needle = expected_ref
        for prefix in ("/app/refs/", "/opt/commoncreed/assets/"):
            if needle.startswith(prefix):
                needle = needle[len(prefix):]
                break
        needle = needle.lstrip("/")
        if needle in entries:
            return PreflightResult(status="ok")
        return PreflightResult(
            status="ref_missing",
            reason=f"{expected_ref!r} (normalized {needle!r}) not in {len(entries)} refs",
        )

    @staticmethod
    def _concat_wavs(wav_paths: List[Path], output_path: Path) -> None:
        """Concatenate WAVs with ffmpeg's concat demuxer (no re-encode)."""
        # Build a concat list file. ffmpeg's concat demuxer needs one
        # "file <path>" line per input.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as lst:
            for p in wav_paths:
                lst.write(f"file '{p.resolve()}'\n")
            list_path = lst.name
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", list_path,
                    "-c", "copy",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode(errors="replace")[-1500:]
            raise RuntimeError(f"wav concat failed: {stderr}") from exc
        finally:
            Path(list_path).unlink(missing_ok=True)

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

        Long scripts are split into sentence-boundary chunks (~380 chars each)
        to stay under Chatterbox's ~40s single-shot cap, then concatenated
        with ffmpeg.
        """
        if not text.strip():
            raise ValueError("text is empty")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        target = Path(output_path)

        chunks = self._chunk_text(text)
        if not chunks:
            raise ValueError("text is empty after chunking")

        logger.info(
            "chatterbox: %d chunks (total %d chars, max chunk %d chars)",
            len(chunks),
            sum(len(c) for c in chunks),
            max(len(c) for c in chunks),
        )

        # Single chunk → simple path, writes directly to target filename.
        if len(chunks) == 1:
            sidecar_filename = target.name
            logger.info(
                "POST %s/tts chars=%d exag=%.1f timeout=%ds",
                self.endpoint, len(chunks[0]), exaggeration, self.request_timeout_s,
            )
            data = self._post_chunk(chunks[0], exaggeration, sidecar_filename)
            generated = Path(data["output_path"])
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

        # Multi-chunk: generate each to a unique filename on the shared volume,
        # concatenate, then clean up.
        run_id = uuid.uuid4().hex[:8]
        stem = target.stem
        chunk_paths: List[Path] = []
        total_gen_ms = 0.0
        sr = 0
        try:
            for i, chunk in enumerate(chunks):
                chunk_filename = f"{stem}__chunk{i:02d}__{run_id}.wav"
                logger.info(
                    "POST %s/tts chunk %d/%d chars=%d",
                    self.endpoint, i + 1, len(chunks), len(chunk),
                )
                data = self._post_chunk(chunk, exaggeration, chunk_filename)
                chunk_paths.append(Path(data["output_path"]))
                total_gen_ms += float(data.get("duration_ms", 0))
                sr = int(data.get("sample_rate", sr))
            self._concat_wavs(chunk_paths, target)
            logger.info(
                "chatterbox OK — wrote %s (%d chunks, gen %.1fs total, sr=%d)",
                target,
                len(chunks),
                total_gen_ms / 1000.0,
                sr,
            )
            return str(target)
        finally:
            for p in chunk_paths:
                p.unlink(missing_ok=True)

    def estimate_cost(self, text: str) -> dict:
        """Local generation — zero marginal cost."""
        return {
            "character_count": len(text),
            "chunks": 1,
            "estimated_cost_usd": 0.0,
            "pricing_note": "Local GPU generation via chatterbox sidecar.",
        }
