"""Unit 0.3 — SFX picker + voiceover mix helper.

Public surface:

* ``SfxCategory``        — Literal type: ``"cut" | "punch" | "reveal" | "tick"``.
* ``SfxEvent``           — NamedTuple ``(t_seconds, category, intensity)``.
* ``pick_sfx``           — deterministic, seed-keyed file selection.
* ``mix_sfx_into_audio`` — single-pass ffmpeg ``amix`` over the voiceover
                           with per-event ``adelay`` and a -18 dB weight
                           applied to every SFX leg.

The module is voiceover-agnostic: it does not read/write the voiceover
(that happens inside ffmpeg).  All randomness flows through ``pick_sfx``
which takes an explicit ``seed``, so the whole pipeline stays reproducible
for a given story.
"""

from __future__ import annotations

import logging
import random
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Literal, NamedTuple

__all__ = [
    "SfxCategory",
    "SfxEvent",
    "SfxPack",
    "pick_sfx",
    "mix_sfx_into_audio",
    "register_pack",
    "SFX_DIR",
    "SFX_WEIGHT",
]

log = logging.getLogger(__name__)

# ─── Types ────────────────────────────────────────────────────────────────────

SfxCategory = Literal["cut", "punch", "reveal", "tick"]
SfxIntensity = Literal["light", "heavy"]


class SfxEvent(NamedTuple):
    """One SFX hit to drop into the voiceover timeline."""

    t_seconds: float
    category: SfxCategory
    intensity: SfxIntensity


# ─── Library layout ──────────────────────────────────────────────────────────

# ``<repo>/assets/sfx`` — relative to this file, regardless of CWD.
# Retained as a module-level export for backwards compatibility: callers
# that previously imported ``SFX_DIR`` still see the CommonCreed pack root.
SFX_DIR: Path = Path(__file__).resolve().parents[2] / "assets" / "sfx"

# Category → intensity → candidate filenames (without .wav extension).
# These names map to the whoosh/pop/ding/tick CommonCreed SFX generator
# (see ``_generate_sfx.py``). Vesper registers its own pack with a
# separate category_files map (drones/sub-bass/risers/reverb-tails/etc.)
# — see Unit 5 + the Vesper pre-launch sourcing step.
_COMMONCREED_CATEGORY_FILES: dict[SfxCategory, dict[SfxIntensity, list[str]]] = {
    "cut": {
        "light": ["cut_whoosh", "cut_swish"],
        "heavy": ["cut_swoop", "whoosh_long"],
    },
    "punch": {
        "light": ["pop_short", "pop_high", "tick_soft"],
        "heavy": ["pop_low", "thud_soft", "thud_dramatic"],
    },
    "reveal": {
        "light": ["ding_clean", "swipe_in"],
        "heavy": ["ding_chime", "swipe_out"],
    },
    "tick": {
        "light": ["tick_soft"],
        "heavy": ["tick_hard"],
    },
}


@dataclass(frozen=True)
class SfxPack:
    """A named SFX asset pack rooted at a filesystem directory.

    Packs live under ``assets/<pack>/sfx/`` (or, for the legacy
    CommonCreed pack, directly at ``assets/sfx/``). ``category_files``
    maps the stable category/intensity axes onto pack-specific filenames
    (without ``.wav`` extension). Each channel profile declares which
    pack to use via ``SfxPack.name``.
    """

    name: str
    root_dir: Path
    category_files: Dict[SfxCategory, Dict[SfxIntensity, list[str]]]


# Default CommonCreed pack — keeps existing callers working byte-identical.
_COMMONCREED_PACK = SfxPack(
    name="commoncreed",
    root_dir=SFX_DIR,
    category_files=_COMMONCREED_CATEGORY_FILES,
)

# Pack registry. Additional channels (Vesper etc.) register their pack
# via :func:`register_pack` during pipeline init.
_PACKS: dict[str, SfxPack] = {"commoncreed": _COMMONCREED_PACK}


def register_pack(pack: SfxPack) -> None:
    """Register a pack by name. Safe to call multiple times (last one wins)."""
    _PACKS[pack.name] = pack
    log.info("Registered SFX pack %r (root=%s)", pack.name, pack.root_dir)


def _get_pack(name: str) -> SfxPack:
    try:
        return _PACKS[name]
    except KeyError as exc:
        raise KeyError(
            f"Unknown SFX pack: {name!r} — known packs: {sorted(_PACKS)}"
        ) from exc


# Backwards-compat alias for tests / external callers that referenced the
# legacy flat dict.
_CATEGORY_FILES = _COMMONCREED_CATEGORY_FILES

# -18 dB relative to the voiceover (amplitude ratio 10 ** (-18/20) ≈ 0.1259).
# The origin plan recommends ~0.18; we follow that empirical value so SFX
# punctuates without clipping the voice.
SFX_WEIGHT: float = 0.18
VOICE_WEIGHT: float = 1.0


# ─── pick_sfx ────────────────────────────────────────────────────────────────


def pick_sfx(
    category: SfxCategory,
    intensity: SfxIntensity,
    seed: int,
    pack: str = "commoncreed",
) -> Path:
    """Deterministic, seed-keyed SFX selection.

    Same ``(category, intensity, seed, pack)`` → same ``Path``, regardless
    of process or platform.  Different seeds may (but are not guaranteed
    to) pick different files.

    Parameters
    ----------
    category, intensity, seed:
        Stable axes for deterministic selection.
    pack:
        Pack name registered via :func:`register_pack`. Default
        ``"commoncreed"`` — backward-compatible with pre-Unit-3 callers.

    Raises
    ------
    KeyError
        If ``pack`` is unknown or ``(category, intensity)`` is not a
        known library bucket within that pack.
    FileNotFoundError
        If the candidate name maps to a missing .wav on disk. (Sanity
        check — CommonCreed's generator in ``_generate_sfx.py`` populates
        every name in its pack; Vesper's pack must be pre-sourced.)
    """
    sfx_pack = _get_pack(pack)
    if category not in sfx_pack.category_files:
        raise KeyError(
            f"Unknown SFX category: {category!r} in pack {sfx_pack.name!r}"
        )
    bucket = sfx_pack.category_files[category]
    if intensity not in bucket:
        raise KeyError(
            f"Unknown intensity {intensity!r} for category {category!r} "
            f"in pack {sfx_pack.name!r}"
        )
    candidates = bucket[intensity]
    if not candidates:  # pragma: no cover — config sanity
        raise KeyError(
            f"Empty SFX bucket for category={category!r} intensity={intensity!r} "
            f"in pack {sfx_pack.name!r}"
        )
    rng = random.Random(seed)
    name = rng.choice(candidates)
    path = sfx_pack.root_dir / f"{name}.wav"
    if not path.exists():
        raise FileNotFoundError(
            f"SFX file missing on disk: {path} (pack={sfx_pack.name!r}) — "
            f"repopulate pack before running the pipeline"
        )
    return path


# ─── mix_sfx_into_audio ──────────────────────────────────────────────────────


def _build_amix_cmd(
    audio_path: str,
    sfx_events: list[SfxEvent],
    sfx_paths: list[Path],
    output_path: str,
) -> list[str]:
    """Assemble the ffmpeg argv for a single ``amix`` pass.

    Structure:

        ffmpeg -y -i <voice> -i <sfx1> -i <sfx2> … \\
               -filter_complex \\
                 "[1]adelay=<ms1>|<ms1>[a1]; \\
                  [2]adelay=<ms2>|<ms2>[a2]; \\
                  [0][a1][a2]amix=inputs=N:weights=1.0 0.18 0.18:duration=first:normalize=0[out]" \\
               -map "[out]" <output_path>

    The voiceover is input 0 with weight 1.0; each SFX is weight 0.18
    and gets its own ``adelay`` before feeding into ``amix``.
    ``duration=first`` keeps the output length equal to the voiceover
    (SFX past the end are clipped).  ``normalize=0`` disables amix's
    implicit 1/N scaling so our weights control absolute levels.
    """
    if len(sfx_events) != len(sfx_paths):  # pragma: no cover — caller guard
        raise ValueError("events/paths length mismatch")

    cmd: list[str] = ["ffmpeg", "-y", "-i", audio_path]
    for p in sfx_paths:
        cmd.extend(["-i", str(p)])

    # Build filter_complex.  adelay wants per-channel delays — we duplicate
    # the millisecond value so mono SFX delay correctly regardless of
    # channel layout ffmpeg infers.
    parts: list[str] = []
    amix_inputs = ["[0]"]  # voiceover
    for i, ev in enumerate(sfx_events, start=1):
        delay_ms = max(int(round(ev.t_seconds * 1000)), 0)
        label = f"a{i}"
        parts.append(f"[{i}]adelay={delay_ms}|{delay_ms}[{label}]")
        amix_inputs.append(f"[{label}]")

    n_inputs = len(sfx_events) + 1
    weights = " ".join(
        [f"{VOICE_WEIGHT}"] + [f"{SFX_WEIGHT}"] * len(sfx_events)
    )
    amix_clause = (
        f"{''.join(amix_inputs)}amix=inputs={n_inputs}"
        f":weights={weights}"
        f":duration=first:normalize=0[out]"
    )
    parts.append(amix_clause)
    filter_complex = "; ".join(parts)

    cmd.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            output_path,
        ]
    )
    return cmd


def _voiceover_passthrough_cmd(audio_path: str, output_path: str) -> list[str]:
    """Zero-SFX fallback: copy the voiceover to output_path via ffmpeg.

    We still go through ffmpeg so callers get a consistent output
    container + sample layout, no matter whether any events fired.
    """
    return [
        "ffmpeg",
        "-y",
        "-i",
        audio_path,
        "-c:a",
        "copy",
        output_path,
    ]


def mix_sfx_into_audio(
    audio_path: str,
    sfx_events: Iterable[SfxEvent],
    output_path: str,
    seed: int = 0,
    pack: str = "commoncreed",
) -> str:
    """Mix all ``sfx_events`` into ``audio_path``, writing ``output_path``.

    One ``subprocess.run`` → one ffmpeg invocation → one output file.
    Each event is resolved via :func:`pick_sfx` using a per-event seed
    derived from ``(seed, event index, category, intensity)`` so the
    choice is stable but varies across events.

    Parameters
    ----------
    audio_path : str
        Source voiceover (any ffmpeg-decodable format).
    sfx_events : Iterable[SfxEvent]
        Events to drop onto the timeline.  Order does not matter — we
        preserve iteration order for reproducibility but each event
        carries its own absolute ``t_seconds``.
    output_path : str
        Destination path.  Extension determines the container.
    seed : int
        Master RNG seed.  Derived per-event so the full pipeline stays
        deterministic for a given story.
    pack : str
        SFX pack name. Default ``"commoncreed"``. Vesper and other
        channels pass their own pack name (registered via
        :func:`register_pack`).

    Returns
    -------
    str
        ``output_path`` on success (subprocess returncode 0).

    Raises
    ------
    subprocess.CalledProcessError
        If ffmpeg exits non-zero.
    """
    events = list(sfx_events)

    if not events:
        log.info("mix_sfx_into_audio: no events → voiceover passthrough (pack=%s)", pack)
        cmd = _voiceover_passthrough_cmd(audio_path, output_path)
        subprocess.run(cmd, check=True)
        return output_path

    # Resolve every SFX path up-front so ffmpeg -i order matches the
    # filter_complex labels.
    sfx_paths: list[Path] = []
    for i, ev in enumerate(events):
        event_seed = _derive_event_seed(seed, i, ev.category, ev.intensity)
        sfx_paths.append(pick_sfx(ev.category, ev.intensity, event_seed, pack=pack))

    cmd = _build_amix_cmd(audio_path, events, sfx_paths, output_path)
    log.info(
        "mix_sfx_into_audio: %d events (pack=%s) cmd=%s",
        len(events), pack, shlex.join(cmd),
    )
    subprocess.run(cmd, check=True)
    return output_path


def _derive_event_seed(
    master_seed: int,
    index: int,
    category: str,
    intensity: str,
) -> int:
    """Deterministic cross-process seed mixer.

    ``hash()`` is process-salted for strings on CPython, so we avoid it
    here.  Instead we fold the inputs through a tiny multiplicative mix.
    """
    # FNV-1a-ish; any stable mixer works — we only need determinism, not
    # cryptographic strength.
    acc = (master_seed ^ 0x9E3779B1) & 0xFFFFFFFF
    acc = (acc * 16777619 + index) & 0xFFFFFFFF
    for ch in category:
        acc = (acc ^ ord(ch)) & 0xFFFFFFFF
        acc = (acc * 16777619) & 0xFFFFFFFF
    for ch in intensity:
        acc = (acc ^ ord(ch)) & 0xFFFFFFFF
        acc = (acc * 16777619) & 0xFFFFFFFF
    return acc
