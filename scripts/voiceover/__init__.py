"""Voice-over generation — local Chatterbox (default) or ElevenLabs API."""

from .voice_generator import VoiceGenerator
from .chatterbox_generator import ChatterboxVoiceGenerator

_DEFAULT_PROVIDER = "chatterbox"


def make_voice_generator(config: dict = None):
    """Factory for the configured voice provider.

    Config keys:
        voice_provider: "chatterbox" (default) or "elevenlabs"
        chatterbox_reference_audio: path to voice clone reference WAV
        elevenlabs_api_key: ElevenLabs API key (for "elevenlabs" provider)
    """
    config = config or {}
    provider = config.get("voice_provider", _DEFAULT_PROVIDER).lower()

    if provider == "chatterbox":
        return ChatterboxVoiceGenerator(
            reference_audio=config.get("chatterbox_reference_audio", ""),
            device=config.get("device", "cuda"),
        )

    if provider == "elevenlabs":
        return VoiceGenerator(
            api_key=config.get("elevenlabs_api_key"),
        )

    raise ValueError(
        f"Unknown voice_provider {provider!r}. "
        f"Supported: 'chatterbox', 'elevenlabs'."
    )


__all__ = ["VoiceGenerator", "ChatterboxVoiceGenerator", "make_voice_generator"]
