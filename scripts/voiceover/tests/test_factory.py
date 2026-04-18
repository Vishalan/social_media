"""Tests for `make_voice_generator` + the Chatterbox HTTP client.

No network in these tests — `requests.post` is monkeypatched. Chatterbox's
heavy deps (torch / chatterbox-tts) live in the sidecar container, not in
the Python client, so these tests run in any environment.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

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


def test_chatterbox_defaults_to_in_compose_endpoint(monkeypatch):
    monkeypatch.delenv("CHATTERBOX_ENDPOINT", raising=False)
    gen = make_voice_generator({"voice_provider": "chatterbox"})
    assert gen.endpoint == "http://commoncreed_chatterbox:7777"


def test_chatterbox_endpoint_from_config_overrides_default():
    gen = make_voice_generator(
        {"voice_provider": "chatterbox", "chatterbox_endpoint": "http://gpu-box:7777"}
    )
    assert gen.endpoint == "http://gpu-box:7777"


def test_chatterbox_endpoint_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("CHATTERBOX_ENDPOINT", "http://env-box:7777")
    gen = make_voice_generator({"voice_provider": "chatterbox"})
    assert gen.endpoint == "http://env-box:7777"


def test_chatterbox_generate_posts_json_and_writes_file(tmp_path, monkeypatch):
    fake_resp = SimpleNamespace(
        status_code=200,
        json=lambda: {
            "output_path": str(tmp_path / "out.wav"),
            "duration_ms": 1234.0,
            "sample_rate": 24000,
        },
        text="",
    )
    (tmp_path / "out.wav").write_bytes(b"fake-wav")

    post = MagicMock(return_value=fake_resp)
    monkeypatch.setattr("voiceover.chatterbox_generator.requests.post", post)

    gen = ChatterboxVoiceGenerator(
        reference_audio="/app/refs/ref.wav",
        endpoint="http://gpu:7777",
    )
    result = gen.generate("Hello world", str(tmp_path / "out.wav"))

    assert result == str(tmp_path / "out.wav")
    post.assert_called_once()
    args, kwargs = post.call_args
    assert args[0] == "http://gpu:7777/tts"
    body = kwargs["json"]
    assert body["text"] == "Hello world"
    assert body["reference_audio_path"] == "/app/refs/ref.wav"
    assert body["exaggeration"] == pytest.approx(0.3)
    assert body["output_filename"] == "out.wav"
    assert kwargs["timeout"] == 600


def test_chatterbox_generate_raises_on_http_error(tmp_path, monkeypatch):
    fake_resp = SimpleNamespace(status_code=500, text="boom", json=lambda: {})
    monkeypatch.setattr(
        "voiceover.chatterbox_generator.requests.post",
        MagicMock(return_value=fake_resp),
    )
    gen = ChatterboxVoiceGenerator(endpoint="http://gpu:7777")
    with pytest.raises(RuntimeError, match="HTTP 500"):
        gen.generate("hi", str(tmp_path / "x.wav"))


def test_chatterbox_generate_rejects_empty_text(tmp_path):
    gen = ChatterboxVoiceGenerator(endpoint="http://gpu:7777")
    with pytest.raises(ValueError, match="empty"):
        gen.generate("   ", str(tmp_path / "x.wav"))


def test_chatterbox_estimate_cost_is_zero():
    gen = ChatterboxVoiceGenerator(endpoint="http://gpu:7777")
    cost = gen.estimate_cost("some text")
    assert cost["estimated_cost_usd"] == 0.0
    assert cost["character_count"] == 9
