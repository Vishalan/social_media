"""Voice-over generation — ElevenLabs (cloud) or Chatterbox (local GPU).

The pipeline picks a provider via the ``voice_provider`` config key (populated
from the ``VOICE_PROVIDER`` env var in the CLI entry point). ``elevenlabs`` is
the default for backward compatibility; flip to ``chatterbox`` once the local
GPU + reference audio are in place.
"""

from typing import Any, Dict, Union

from .chatterbox_generator import ChatterboxVoiceGenerator
from .voice_generator import VoiceGenerator

__all__ = [
    "ChatterboxVoiceGenerator",
    "VoiceGenerator",
    "make_voice_generator",
]

VoiceGenLike = Union[VoiceGenerator, ChatterboxVoiceGenerator]


def make_voice_generator(config: Dict[str, Any]) -> VoiceGenLike:
    """Return the configured voice generator.

    Reads ``config["voice_provider"]`` (lowered). Unknown providers raise
    ``ValueError`` — failing loudly is better than silently defaulting.
    """
    provider = str(config.get("voice_provider", "elevenlabs")).lower()

    if provider == "chatterbox":
        return ChatterboxVoiceGenerator(
            reference_audio=config.get("chatterbox_reference_audio") or None,
            device=config.get("chatterbox_device", "cuda"),
        )
    if provider == "elevenlabs":
        return VoiceGenerator(api_key=config.get("elevenlabs_api_key"))
    raise ValueError(
        f"Unknown voice_provider: {provider!r} (expected 'elevenlabs' or 'chatterbox')"
    )
