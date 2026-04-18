"""
Local voice generation using Chatterbox TTS (Resemble AI).

Drop-in alternative to ElevenLabs VoiceGenerator. Runs entirely on the
local GPU (5-7 GB VRAM), zero API cost. Supports voice cloning from a
short reference audio clip (10-30 seconds).

Usage::

    gen = ChatterboxVoiceGenerator(reference_audio="assets/voice_ref.wav")
    gen.generate("Hello world", "output/voice.wav")
"""
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ChatterboxVoiceGenerator:
    """Generate voice-over using Chatterbox TTS locally on GPU."""

    def __init__(
        self,
        reference_audio: Optional[str] = None,
        device: str = "cuda",
    ):
        """
        Args:
            reference_audio: Path to a 10-30s WAV file of the target voice.
                             If None, uses CHATTERBOX_REFERENCE_AUDIO env var.
            device: torch device ("cuda" or "cpu")
        """
        self.reference_audio = reference_audio or os.getenv("CHATTERBOX_REFERENCE_AUDIO", "")
        self.device = device
        self._model = None
        logger.info("ChatterboxVoiceGenerator initialized (model loads on first call)")

    def _load_model(self):
        if self._model is not None:
            return
        from chatterbox.tts import ChatterboxTTS
        logger.info("Loading Chatterbox model to %s...", self.device)
        self._model = ChatterboxTTS.from_pretrained(device=self.device)
        logger.info("Chatterbox model loaded")

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
        ``voice_id`` and ``voice_name`` are accepted but ignored — Chatterbox
        uses the reference audio for voice identity.

        Args:
            text: Text to convert to speech
            output_path: Path to save the WAV file
            exaggeration: Emotion exaggeration (0.0 = neutral, 1.0 = dramatic)

        Returns:
            Path to the generated audio file
        """
        import re as _re
        import torchaudio

        self._load_model()

        # Preprocess: strip stage directions (same as ElevenLabs generator)
        text = _re.sub(r'\[.*?\]', '', text)
        text = _re.sub(r'\bPause\.?\b', '', text, flags=_re.IGNORECASE)
        text = ' '.join(text.split())

        if not text.strip():
            raise ValueError("No text to generate after preprocessing")

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        ref_audio = self.reference_audio or None
        if ref_audio and not Path(ref_audio).exists():
            logger.warning("Reference audio %s not found, generating without cloning", ref_audio)
            ref_audio = None

        logger.info(
            "Generating %d chars with Chatterbox (ref=%s, exag=%.1f)",
            len(text), "yes" if ref_audio else "no", exaggeration,
        )

        wav = self._model.generate(
            text,
            audio_prompt_path=ref_audio,
            exaggeration=exaggeration,
        )

        torchaudio.save(output_path, wav.cpu(), self._model.sr)
        logger.info("Chatterbox voice saved to %s", output_path)
        return output_path

    def estimate_cost(self, text: str) -> dict:
        """Local generation — zero cost."""
        return {
            "character_count": len(text),
            "chunks": 1,
            "estimated_cost_usd": 0.0,
            "pricing_note": "Local GPU generation, no API cost.",
        }
