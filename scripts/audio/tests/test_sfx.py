"""Tests for Unit 0.3 — ``scripts.audio.sfx``.

All tests are hermetic:
  * No real ffmpeg invocation (subprocess.run is patched).
  * No real network (the module never touches the network).
  * .wav files are the committed Tier-2 synthesized fixtures, not
    regenerated here.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

# Dual-import: bare primary (consistent with scripts/pytest.ini pythonpath=.);
# ``scripts.`` fallback when only the repo root is on sys.path.
try:
    from audio import sfx as sfx_module  # type: ignore[import-not-found]
    from audio.sfx import (  # type: ignore[import-not-found]
        SFX_DIR,
        SFX_WEIGHT,
        VOICE_WEIGHT,
        SfxEvent,
        _build_amix_cmd,
        _derive_event_seed,
        mix_sfx_into_audio,
        pick_sfx,
    )
except ImportError:  # pragma: no cover — fallback when only repo-root on sys.path
    from scripts.audio import sfx as sfx_module  # type: ignore[no-redef]
    from scripts.audio.sfx import (  # type: ignore[no-redef]
        SFX_DIR,
        SFX_WEIGHT,
        VOICE_WEIGHT,
        SfxEvent,
        _build_amix_cmd,
        _derive_event_seed,
        mix_sfx_into_audio,
        pick_sfx,
    )


# ─── Fixture expectations ────────────────────────────────────────────────────

EXPECTED_FILES: tuple[str, ...] = (
    "cut_whoosh",
    "cut_swoop",
    "cut_swish",
    "pop_short",
    "pop_high",
    "pop_low",
    "ding_clean",
    "ding_chime",
    "tick_soft",
    "tick_hard",
    "thud_soft",
    "thud_dramatic",
    "whoosh_long",
    "swipe_in",
    "swipe_out",
)
MAX_BYTES_PER_FILE = 50_000


# ─── 1. Library presence + budget ────────────────────────────────────────────


def test_all_fifteen_sfx_files_present_and_under_budget() -> None:
    """All 15 canonical SFX files exist, are non-empty, and <50KB each."""
    missing: list[str] = []
    too_big: list[tuple[str, int]] = []
    empty: list[str] = []
    for name in EXPECTED_FILES:
        p = SFX_DIR / f"{name}.wav"
        if not p.exists():
            missing.append(name)
            continue
        size = p.stat().st_size
        if size == 0:
            empty.append(name)
        elif size >= MAX_BYTES_PER_FILE:
            too_big.append((name, size))
    assert not missing, f"Missing SFX files: {missing}"
    assert not empty, f"Empty SFX files: {empty}"
    assert not too_big, f"Oversized SFX files: {too_big}"

    # Total count check — guards against accidentally shipping extras.
    wav_count = len(list(SFX_DIR.glob("*.wav")))
    assert wav_count == 15, f"Expected 15 .wav files, found {wav_count}"


def test_all_sfx_are_valid_riff_wave() -> None:
    """Every file in the library passes a stdlib ``wave.open`` round-trip."""
    import wave

    for name in EXPECTED_FILES:
        p = SFX_DIR / f"{name}.wav"
        with wave.open(str(p), "rb") as wf:
            assert wf.getnchannels() == 1, f"{name} must be mono"
            assert wf.getframerate() == 44100, f"{name} must be 44.1 kHz"
            assert wf.getsampwidth() == 2, f"{name} must be 16-bit"
            assert wf.getnframes() > 0, f"{name} has zero frames"


# ─── 2. pick_sfx determinism ─────────────────────────────────────────────────


def test_pick_sfx_deterministic() -> None:
    """Same (category, intensity, seed) → same file path."""
    a = pick_sfx("punch", "light", seed=42)
    b = pick_sfx("punch", "light", seed=42)
    assert a == b
    assert a.exists()
    assert a.parent == SFX_DIR

    # Different buckets can resolve to different files even with the same seed.
    c = pick_sfx("cut", "heavy", seed=42)
    assert c.parent == SFX_DIR


def test_pick_sfx_seed_varies_selection() -> None:
    """Across a spread of seeds, ``pick_sfx`` touches >1 candidate."""
    # "punch" / "light" has 3 candidates — sweeping seeds should hit
    # at least 2 distinct choices.
    chosen: set[Path] = set()
    for seed in range(100):
        chosen.add(pick_sfx("punch", "light", seed=seed))
    assert len(chosen) >= 2, (
        f"Expected pick_sfx to vary across seeds for 3-option bucket; "
        f"got {chosen}"
    )


def test_pick_sfx_returns_valid_candidate() -> None:
    """Result is always one of the declared candidates for the bucket."""
    valid_names = {"pop_short", "pop_high", "tick_soft"}
    for seed in range(50):
        p = pick_sfx("punch", "light", seed=seed)
        assert p.stem in valid_names, f"{p.stem} not in {valid_names}"


# ─── 3. pick_sfx error paths ─────────────────────────────────────────────────


def test_pick_sfx_invalid_category_raises() -> None:
    """Unknown category is a KeyError."""
    with pytest.raises(KeyError):
        pick_sfx("notarealcategory", "light", seed=0)  # type: ignore[arg-type]


def test_pick_sfx_invalid_intensity_raises() -> None:
    """Unknown intensity (within a valid category) is a KeyError."""
    with pytest.raises(KeyError):
        pick_sfx("cut", "medium", seed=0)  # type: ignore[arg-type]


# ─── 4. mix_sfx_into_audio — mocked ffmpeg ───────────────────────────────────


def _fake_completed(returncode: int = 0):
    """Return a minimal ``subprocess.CompletedProcess`` stand-in."""
    from subprocess import CompletedProcess

    return CompletedProcess(args=[], returncode=returncode)


def test_mix_sfx_into_audio_mocked(tmp_path: Path) -> None:
    """Mock ``subprocess.run``; verify the amix argv is well-formed."""
    audio = str(tmp_path / "voice.wav")
    out = str(tmp_path / "out.wav")
    Path(audio).write_bytes(b"RIFFfake")  # presence-only stub

    events = [
        SfxEvent(t_seconds=0.50, category="punch", intensity="light"),
        SfxEvent(t_seconds=1.75, category="reveal", intensity="heavy"),
        SfxEvent(t_seconds=3.125, category="cut", intensity="light"),
    ]

    target = "audio.sfx.subprocess.run"
    try:
        with patch(target) as mock_run:
            mock_run.return_value = _fake_completed()
            result = mix_sfx_into_audio(audio, events, out, seed=7)
    except (ModuleNotFoundError, AttributeError):
        with patch("scripts.audio.sfx.subprocess.run") as mock_run:
            mock_run.return_value = _fake_completed()
            result = mix_sfx_into_audio(audio, events, out, seed=7)

    assert result == out
    assert mock_run.call_count == 1
    argv = mock_run.call_args.args[0]

    # ffmpeg binary + overwrite flag + voice input.
    assert argv[0] == "ffmpeg"
    assert "-y" in argv
    assert argv.index("-i") < argv.index(audio)
    assert argv[-1] == out

    # One ``-i`` per SFX, plus one for the voiceover = 4 total.
    assert argv.count("-i") == 1 + len(events)

    # filter_complex string carries the expected structure.
    fc_idx = argv.index("-filter_complex")
    filter_complex = argv[fc_idx + 1]

    # Each event gets its own adelay with both channels set to the same ms.
    expected_delays_ms = [500, 1750, 3125]
    for i, ms in enumerate(expected_delays_ms, start=1):
        assert f"[{i}]adelay={ms}|{ms}[a{i}]" in filter_complex, (
            f"missing adelay for event {i} @ {ms}ms in: {filter_complex}"
        )

    # amix has N = events + 1 inputs, and weights lists voice first.
    assert f"amix=inputs={len(events) + 1}" in filter_complex
    expected_weights = " ".join(
        [f"{VOICE_WEIGHT}"] + [f"{SFX_WEIGHT}"] * len(events)
    )
    assert f"weights={expected_weights}" in filter_complex
    assert "duration=first" in filter_complex
    assert "normalize=0" in filter_complex

    # Output map pulls the labelled amix bus.
    map_idx = argv.index("-map")
    assert argv[map_idx + 1] == "[out]"


def test_mix_sfx_into_audio_no_events_passthrough(tmp_path: Path) -> None:
    """Empty event list → voiceover passthrough ffmpeg call."""
    audio = str(tmp_path / "voice.wav")
    out = str(tmp_path / "out.wav")
    Path(audio).write_bytes(b"RIFFfake")

    try:
        with patch("audio.sfx.subprocess.run") as mock_run:
            mock_run.return_value = _fake_completed()
            result = mix_sfx_into_audio(audio, [], out, seed=0)
    except (ModuleNotFoundError, AttributeError):
        with patch("scripts.audio.sfx.subprocess.run") as mock_run:
            mock_run.return_value = _fake_completed()
            result = mix_sfx_into_audio(audio, [], out, seed=0)

    assert result == out
    argv = mock_run.call_args.args[0]
    assert argv[0] == "ffmpeg"
    # Passthrough uses ``-c:a copy`` — no filter_complex.
    assert "-filter_complex" not in argv
    assert "-c:a" in argv
    assert argv[argv.index("-c:a") + 1] == "copy"


# ─── 5. NamedTuple semantics ─────────────────────────────────────────────────


def test_sfx_event_namedtuple_immutable() -> None:
    """SfxEvent is a NamedTuple — field assignment raises AttributeError."""
    ev = SfxEvent(t_seconds=1.0, category="cut", intensity="light")
    # Field access works.
    assert ev.t_seconds == 1.0
    assert ev.category == "cut"
    assert ev.intensity == "light"
    # Indexing works (tuple behaviour).
    assert ev[0] == 1.0
    # Assignment does not.
    with pytest.raises(AttributeError):
        ev.t_seconds = 2.0  # type: ignore[misc]


# ─── 6. Event seed derivation is stable ──────────────────────────────────────


def test_derive_event_seed_is_deterministic() -> None:
    """Same inputs → same derived seed across calls."""
    a = _derive_event_seed(42, 0, "cut", "light")
    b = _derive_event_seed(42, 0, "cut", "light")
    assert a == b


def test_derive_event_seed_varies_by_index() -> None:
    """Different event indices (same master seed) yield different seeds."""
    a = _derive_event_seed(42, 0, "cut", "light")
    b = _derive_event_seed(42, 1, "cut", "light")
    assert a != b


# ─── 7. _build_amix_cmd direct unit test ─────────────────────────────────────


def test_build_amix_cmd_direct() -> None:
    """Bench the filter graph builder without running ffmpeg."""
    events = [
        SfxEvent(t_seconds=0.0, category="punch", intensity="light"),
        SfxEvent(t_seconds=2.25, category="cut", intensity="heavy"),
    ]
    paths = [SFX_DIR / "pop_short.wav", SFX_DIR / "cut_swoop.wav"]
    argv = _build_amix_cmd("in.wav", events, paths, "out.wav")
    # Correct number of inputs: 1 voice + 2 SFX.
    assert argv.count("-i") == 3
    fc = argv[argv.index("-filter_complex") + 1]
    assert "[1]adelay=0|0[a1]" in fc
    assert "[2]adelay=2250|2250[a2]" in fc
    assert "amix=inputs=3" in fc
    # t=0 event is still delayed=0; voice is unchanged input 0.
