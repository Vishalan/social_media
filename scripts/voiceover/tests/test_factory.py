"""Tests for `make_voice_generator` — the voice provider factory.

No network, no GPU. Chatterbox's heavy deps (torch/torchaudio/chatterbox-tts)
are only imported inside `ChatterboxVoiceGenerator._load_model`, so
constructing the class is safe in CI without those packages installed.
"""

from __future__ import annotations

import pytest

from voiceover import (
    ChatterboxVoiceGenerator,
    VoiceGenerator,
    make_voice_generator,
)


def test_factory_defaults_to_elevenlabs():
    gen = make_voice_generator({"elevenlabs_api_key": "fake-key"})
    assert isinstance(gen, VoiceGenerator)
    assert gen.api_key == "fake-key"


def test_factory_returns_elevenlabs_when_explicit():
    gen = make_voice_generator(
        {"voice_provider": "elevenlabs", "elevenlabs_api_key": "fake-key"}
    )
    assert isinstance(gen, VoiceGenerator)


def test_factory_returns_chatterbox():
    gen = make_voice_generator(
        {
            "voice_provider": "chatterbox",
            "chatterbox_reference_audio": "/path/to/ref.wav",
            "chatterbox_device": "cpu",
        }
    )
    assert isinstance(gen, ChatterboxVoiceGenerator)
    assert gen.reference_audio == "/path/to/ref.wav"
    assert gen.device == "cpu"


def test_factory_chatterbox_defaults_device_to_cuda():
    gen = make_voice_generator(
        {"voice_provider": "chatterbox", "chatterbox_reference_audio": "/x.wav"}
    )
    assert gen.device == "cuda"


def test_factory_provider_matching_is_case_insensitive():
    gen = make_voice_generator(
        {"voice_provider": "ChatterBox", "chatterbox_reference_audio": "/x.wav"}
    )
    assert isinstance(gen, ChatterboxVoiceGenerator)


def test_factory_raises_on_unknown_provider():
    with pytest.raises(ValueError, match="Unknown voice_provider"):
        make_voice_generator({"voice_provider": "bark"})


def test_factory_raises_on_unknown_provider_mentions_both_valid_options():
    with pytest.raises(ValueError, match="elevenlabs.*chatterbox"):
        make_voice_generator({"voice_provider": "espeak"})


def test_chatterbox_empty_reference_passes_none_to_constructor(monkeypatch):
    monkeypatch.delenv("CHATTERBOX_REFERENCE_AUDIO", raising=False)
    gen = make_voice_generator(
        {"voice_provider": "chatterbox", "chatterbox_reference_audio": ""}
    )
    # Factory converts "" → None so ChatterboxVoiceGenerator's fallback chain
    # (`reference_audio or os.getenv(...)`) can pick up the env var when set.
    # With env var unset, the final value is "".
    assert gen.reference_audio == ""
