"""Generate the 15 CommonCreed SFX .wav files in ``assets/sfx/``.

Two-tier sourcing strategy (see ``assets/sfx/LICENSE.md``):

  * Tier 1 — CC0 download.  Attempts to fetch each clip from a curated
    list of CC0 sources (Pixabay, Mixkit) via ``urllib.request``.  Most
    of these sites block hotlinking, so the download typically fails
    with an HTTP 403 or a network error.  That is expected.

  * Tier 2 — synthesize in-repo.  If Tier 1 fails (for any reason: no
    network, 403, non-WAV content, file too big), the clip is
    synthesized deterministically from numpy with the recipes below.
    All synthesized output is CC0-licensed to this repository.

Run as a module to (re)populate the directory::

    python -m scripts.audio._generate_sfx

The script is idempotent: it overwrites any existing .wav files and
reports what it did.  Commit the resulting binaries.
"""

from __future__ import annotations

import argparse
import logging
import struct
import sys
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Callable

import numpy as np

# ─── Configuration ───────────────────────────────────────────────────────────

SAMPLE_RATE = 44100
INT16_MAX = 32767
# Peak-normalize to -3 dB → 10 ** (-3/20) ≈ 0.7079 of int16 full scale.
PEAK_AMPLITUDE = int(0.7079 * INT16_MAX)  # ≈ 23200

SFX_DIR = Path(__file__).resolve().parents[2] / "assets" / "sfx"

# Tier 1 hotlinks.  Left empty by default — even if the user wants to try a
# CC0 fetch, most of these hosts 403 unauthenticated curls.  The map is
# kept in place so future maintainers can paste URLs without refactoring.
#
# Format: ``name → (url, expected_content_type_prefix)``.
TIER1_URLS: dict[str, tuple[str, str]] = {}


log = logging.getLogger(__name__)


# ─── Core helpers ────────────────────────────────────────────────────────────


def _envelope_exp(n: int, tau_samples: float) -> np.ndarray:
    """Exponential decay envelope: ``exp(-t/tau)``."""
    t = np.arange(n, dtype=np.float64)
    return np.exp(-t / max(tau_samples, 1.0))


def _hann(n: int) -> np.ndarray:
    """Full Hann window of length n."""
    if n <= 1:
        return np.ones(n, dtype=np.float64)
    return 0.5 * (1.0 - np.cos(2.0 * np.pi * np.arange(n) / (n - 1)))


def _sweep_sine(duration_s: float, f_start: float, f_end: float) -> np.ndarray:
    """Linear-frequency-swept sine wave."""
    n = int(duration_s * SAMPLE_RATE)
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    # Linear frequency ramp: instantaneous frequency ``f(t) = f0 + k*t``.
    # Phase is the integral: ``phi(t) = 2π*(f0*t + 0.5*k*t²)``.
    k = (f_end - f_start) / duration_s
    phase = 2.0 * np.pi * (f_start * t + 0.5 * k * t * t)
    return np.sin(phase)


def _box_filter(y: np.ndarray, width: int) -> np.ndarray:
    """Simple moving-average low-pass via numpy convolve."""
    if width <= 1:
        return y
    kernel = np.ones(width, dtype=np.float64) / width
    return np.convolve(y, kernel, mode="same")


def _peak_normalize(y: np.ndarray, target: int = PEAK_AMPLITUDE) -> np.ndarray:
    """Peak-normalize to ``target`` int16 amplitude and return int16 array."""
    if y.size == 0:
        return np.zeros(0, dtype=np.int16)
    peak = float(np.max(np.abs(y)))
    if peak < 1e-9:
        return np.zeros(y.shape, dtype=np.int16)
    scaled = (y / peak) * float(target)
    # Clamp defensively; rounding ensures no int16 overflow.
    scaled = np.clip(scaled, -INT16_MAX, INT16_MAX)
    return np.round(scaled).astype(np.int16)


def _write_wav(path: Path, samples_int16: np.ndarray) -> None:
    """Write mono 16-bit PCM WAV at SAMPLE_RATE."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(SAMPLE_RATE)
        # ``struct`` avoids an optional scipy dep; numpy.tobytes also works
        # but wave.writeframes is happy with a bytes buffer.
        wf.writeframes(samples_int16.tobytes())


# ─── Recipes ─────────────────────────────────────────────────────────────────


def _recipe_cut_whoosh() -> np.ndarray:
    """100ms white-noise burst, 10ms attack + 40ms exp decay, gentle LPF."""
    rng = np.random.default_rng(seed=1001)
    n = int(0.100 * SAMPLE_RATE)
    noise = rng.standard_normal(n)
    attack_n = int(0.010 * SAMPLE_RATE)
    env = np.ones(n, dtype=np.float64)
    env[:attack_n] = np.linspace(0.0, 1.0, attack_n)
    tau = 0.040 * SAMPLE_RATE
    env[attack_n:] *= _envelope_exp(n - attack_n, tau)
    return _box_filter(noise * env, width=50)


def _recipe_cut_swoop() -> np.ndarray:
    """180ms swept sine 800→200 Hz with 80ms Hann window."""
    y = _sweep_sine(0.180, 800.0, 200.0)
    # Apply 80ms Hann to the tail (the "swoop" fades out).
    win_n = int(0.080 * SAMPLE_RATE)
    env = np.ones(len(y), dtype=np.float64)
    hann_tail = _hann(2 * win_n)[win_n:]  # second half: 1 → 0
    env[-win_n:] = hann_tail[: len(env[-win_n:])]
    return y * env


def _recipe_cut_swish() -> np.ndarray:
    """120ms filtered noise burst, exp decay — lighter than whoosh."""
    rng = np.random.default_rng(seed=1002)
    n = int(0.120 * SAMPLE_RATE)
    noise = rng.standard_normal(n)
    env = _envelope_exp(n, 0.045 * SAMPLE_RATE)
    return _box_filter(noise * env, width=30)


def _half_cycle_sine(duration_s: float, freq_hz: float) -> np.ndarray:
    """Single positive half-cycle of a sine at ``freq_hz``, over duration."""
    n = int(duration_s * SAMPLE_RATE)
    if n <= 0:
        return np.zeros(0, dtype=np.float64)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    return np.sin(2.0 * np.pi * freq_hz * t)


def _recipe_pop_short() -> np.ndarray:
    """40ms half-cycle 800Hz × exp decay tau=20ms."""
    n = int(0.040 * SAMPLE_RATE)
    y = _half_cycle_sine(0.040, 800.0)
    env = _envelope_exp(n, 0.020 * SAMPLE_RATE)
    return y * env


def _recipe_pop_high() -> np.ndarray:
    n = int(0.035 * SAMPLE_RATE)
    y = _half_cycle_sine(0.035, 1200.0)
    env = _envelope_exp(n, 0.015 * SAMPLE_RATE)
    return y * env


def _recipe_pop_low() -> np.ndarray:
    n = int(0.050 * SAMPLE_RATE)
    y = _half_cycle_sine(0.050, 400.0)
    env = _envelope_exp(n, 0.030 * SAMPLE_RATE)
    return y * env


def _recipe_ding_clean() -> np.ndarray:
    """300ms single-tone 1500Hz × exp decay tau=150ms."""
    n = int(0.300 * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    y = np.sin(2.0 * np.pi * 1500.0 * t)
    env = _envelope_exp(n, 0.150 * SAMPLE_RATE)
    return y * env


def _recipe_ding_chime() -> np.ndarray:
    """300ms sum of 1000Hz + 1500Hz sines × exp decay."""
    n = int(0.300 * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    y = np.sin(2.0 * np.pi * 1000.0 * t) + np.sin(2.0 * np.pi * 1500.0 * t)
    env = _envelope_exp(n, 0.160 * SAMPLE_RATE)
    return y * env


def _recipe_tick_soft() -> np.ndarray:
    """25ms narrow-band click: 2kHz sine × 20ms Hann (zero-padded)."""
    n = int(0.025 * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    y = np.sin(2.0 * np.pi * 2000.0 * t)
    hann_n = int(0.020 * SAMPLE_RATE)
    env = np.zeros(n, dtype=np.float64)
    env[:hann_n] = _hann(hann_n)
    return y * env


def _recipe_tick_hard() -> np.ndarray:
    """20ms noise burst, high-pass via first-difference (``y[1:] - y[:-1]``)."""
    rng = np.random.default_rng(seed=1003)
    n = int(0.020 * SAMPLE_RATE)
    noise = rng.standard_normal(n)
    # First-difference = discrete derivative ≈ +6 dB/oct high-pass.
    hp = np.concatenate([[0.0], noise[1:] - noise[:-1]])
    env = _envelope_exp(n, 0.010 * SAMPLE_RATE)
    return hp * env


def _recipe_thud_soft() -> np.ndarray:
    """200ms 80Hz sine × exp decay tau=100ms."""
    n = int(0.200 * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    y = np.sin(2.0 * np.pi * 80.0 * t)
    env = _envelope_exp(n, 0.100 * SAMPLE_RATE)
    return y * env


def _recipe_thud_dramatic() -> np.ndarray:
    """250ms 60Hz sine × exp decay; peak-normalization bumps it to full -3 dB."""
    n = int(0.250 * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    y = np.sin(2.0 * np.pi * 60.0 * t)
    env = _envelope_exp(n, 0.120 * SAMPLE_RATE)
    return y * env


def _recipe_whoosh_long() -> np.ndarray:
    """400ms swept filtered noise: low band → mid band."""
    rng = np.random.default_rng(seed=1004)
    n = int(0.400 * SAMPLE_RATE)
    noise = rng.standard_normal(n)
    # Sweep the filter width linearly: wide box (low-pass heavy) → narrow
    # box (more high-freq content).  We emulate this by mixing a heavily
    # smoothed copy with a lightly smoothed copy via a linear crossfade.
    heavy = _box_filter(noise, width=80)
    light = _box_filter(noise, width=15)
    ramp = np.linspace(0.0, 1.0, n)
    mixed = (1.0 - ramp) * heavy + ramp * light
    # Overall Hann-ish envelope to avoid clicks at start/end.
    env = _hann(n)
    return mixed * env


def _recipe_swipe_in() -> np.ndarray:
    """220ms rising swept sine 300→1200 Hz with Hann window."""
    y = _sweep_sine(0.220, 300.0, 1200.0)
    return y * _hann(len(y))


def _recipe_swipe_out() -> np.ndarray:
    """220ms falling swept sine 1200→300 Hz with Hann window."""
    y = _sweep_sine(0.220, 1200.0, 300.0)
    return y * _hann(len(y))


RECIPES: dict[str, Callable[[], np.ndarray]] = {
    "cut_whoosh": _recipe_cut_whoosh,
    "cut_swoop": _recipe_cut_swoop,
    "cut_swish": _recipe_cut_swish,
    "pop_short": _recipe_pop_short,
    "pop_high": _recipe_pop_high,
    "pop_low": _recipe_pop_low,
    "ding_clean": _recipe_ding_clean,
    "ding_chime": _recipe_ding_chime,
    "tick_soft": _recipe_tick_soft,
    "tick_hard": _recipe_tick_hard,
    "thud_soft": _recipe_thud_soft,
    "thud_dramatic": _recipe_thud_dramatic,
    "whoosh_long": _recipe_whoosh_long,
    "swipe_in": _recipe_swipe_in,
    "swipe_out": _recipe_swipe_out,
}

# Names must match the SfxCategory mapping in scripts/audio/sfx.py.
SFX_NAMES: tuple[str, ...] = tuple(RECIPES.keys())
assert len(SFX_NAMES) == 15, "Spec demands exactly 15 SFX files"


# ─── Tier 1 / Tier 2 orchestration ───────────────────────────────────────────


def _try_tier1(name: str, out_path: Path) -> bool:
    """Best-effort CC0 download.  Returns True on success, False otherwise."""
    entry = TIER1_URLS.get(name)
    if entry is None:
        return False
    url, _ctype_prefix = entry
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:  # noqa: BLE001
        log.info("Tier 1 fetch failed for %s: %s", name, exc)
        return False
    # Only accept if it looks like a RIFF WAVE file and is reasonably small.
    if not data.startswith(b"RIFF") or b"WAVE" not in data[:12]:
        log.info("Tier 1 response for %s was not a WAV", name)
        return False
    if len(data) > 50_000:
        log.info("Tier 1 WAV for %s exceeds 50KB budget", name)
        return False
    out_path.write_bytes(data)
    return True


def _synthesize_sfx(name: str) -> np.ndarray:
    """Generate a single SFX as an int16 mono array at SAMPLE_RATE."""
    recipe = RECIPES[name]
    raw = recipe()
    return _peak_normalize(raw)


def _generate_one(name: str, out_dir: Path) -> tuple[str, int, str]:
    """Produce ``name``.wav in ``out_dir`` via Tier 1 or Tier 2.

    Returns (name, size_bytes, source) for reporting.
    """
    out_path = out_dir / f"{name}.wav"
    if _try_tier1(name, out_path):
        return (name, out_path.stat().st_size, "tier1_cc0")
    samples = _synthesize_sfx(name)
    _write_wav(out_path, samples)
    size = out_path.stat().st_size
    if size > 50_000:
        raise RuntimeError(
            f"{name}.wav is {size} bytes — exceeds 50KB budget"
        )
    return (name, size, "tier2_synth")


def generate_all(out_dir: Path = SFX_DIR) -> list[tuple[str, int, str]]:
    """Generate all 15 SFX files; returns per-file (name, size, source)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, int, str]] = []
    for name in SFX_NAMES:
        rows.append(_generate_one(name, out_dir))
    return rows


# ─── CLI ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=SFX_DIR,
        help=f"Output directory (default: {SFX_DIR})",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Log per-file details"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    rows = generate_all(args.out)
    for name, size, source in rows:
        print(f"  {name:<16s} {size:>6d} bytes  [{source}]")
    total = sum(r[1] for r in rows)
    print(f"\n{len(rows)} files generated, total {total} bytes")
    return 0


if __name__ == "__main__":  # pragma: no cover — script entrypoint
    sys.exit(main())
