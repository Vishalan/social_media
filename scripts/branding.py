"""CommonCreed brand tokens — single source of truth.

Exposes the brand color palette and a deterministic font-resolution helper
used by the b-roll, thumbnail, and caption layers. Fonts ship in-repo under
``assets/fonts/`` (Inter, SIL OFL) and are resolved against the project
root so the module works regardless of the caller's CWD. System fallbacks
preserve the original ``headline_burst.py`` behavior on developer laptops
where Inter is not installed globally.

This module is import-side-effect-free and has no external dependencies
beyond the standard library.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


# ─── Brand palette ────────────────────────────────────────────────────────────
# Source: wordmark + MEMORY.md (project_commoncreed_brand_palette.md).

NAVY: str = "#1E3A8A"
SKY_BLUE: str = "#5C9BFF"
WHITE: str = "#FFFFFF"


# ─── Font candidates ──────────────────────────────────────────────────────────
# First entry is the in-repo Inter TTF (resolved against project root by
# ``find_font``). Remaining entries are system fallbacks — kept verbatim from
# the original ``scripts/broll_gen/headline_burst.py`` so dev machines still
# work without running any install step.

BOLD_FONT_CANDIDATES: list[str] = [
    "assets/fonts/Inter-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]

REGULAR_FONT_CANDIDATES: list[str] = [
    "assets/fonts/Inter-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

SEMIBOLD_FONT_CANDIDATES: list[str] = [
    "assets/fonts/Inter-SemiBold.ttf",
    # SemiBold is rarely available system-wide; fall back to Bold then Regular
    # so a ``find_font("semibold")`` call never hard-fails on a dev machine.
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


# ``branding.py`` lives at ``scripts/branding.py``; project root is its parent's
# parent. Resolved once at import time for determinism.
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

_WEIGHT_CANDIDATES: dict[str, list[str]] = {
    "bold": BOLD_FONT_CANDIDATES,
    "regular": REGULAR_FONT_CANDIDATES,
    "semibold": SEMIBOLD_FONT_CANDIDATES,
}


def _resolve(candidate: str) -> Path:
    """Return an absolute path. Relative candidates resolve against project root."""
    p = Path(candidate)
    if p.is_absolute():
        return p
    return _PROJECT_ROOT / p


def find_font(weight: Literal["bold", "regular", "semibold"]) -> str:
    """Return the first existing font path for the requested weight.

    Args:
        weight: One of ``"bold"``, ``"regular"``, ``"semibold"``.

    Returns:
        Absolute filesystem path to a font file that exists on disk.

    Raises:
        ValueError: If ``weight`` is not a known weight.
        FileNotFoundError: If no candidate for the weight exists on disk.
    """
    candidates = _WEIGHT_CANDIDATES.get(weight)
    if candidates is None:
        raise ValueError(
            f"unknown font weight {weight!r}; "
            f"expected one of {sorted(_WEIGHT_CANDIDATES)}"
        )
    for candidate in candidates:
        resolved = _resolve(candidate)
        if resolved.exists():
            return str(resolved)
    raise FileNotFoundError(
        f"no font found for weight {weight!r}; tried {candidates!r}. "
        f"Expected in-repo TTF at {_PROJECT_ROOT / candidates[0]!s} — "
        "if missing, re-download Inter from https://github.com/rsms/inter "
        "or install a system fallback."
    )


_HEX_RE = re.compile(r"^#?[0-9A-Fa-f]{6}$")


def to_ass_color(hex_str: str) -> str:
    """Convert a ``#RRGGBB`` hex string to an ASS subtitle color token.

    ASS (Advanced SubStation Alpha) encodes colors as ``&HAABBGGRR&`` with
    byte order reversed (BGR) and a leading alpha byte. This helper emits the
    opaque form (``AA = 00``) used by our caption renderer.

    Examples:
        >>> to_ass_color("#5C9BFF")
        '&H00FF9B5C&'
        >>> to_ass_color("#1E3A8A")
        '&H008A3A1E&'
        >>> to_ass_color("#FFFFFF")
        '&H00FFFFFF&'

    Args:
        hex_str: A 6-digit hex color, optionally prefixed with ``#``.

    Returns:
        ASS color token string.

    Raises:
        ValueError: If ``hex_str`` is not a 6-digit hex color.
    """
    if not isinstance(hex_str, str) or not _HEX_RE.match(hex_str):
        raise ValueError(
            f"invalid hex color {hex_str!r}; expected '#RRGGBB' (6 hex digits)"
        )
    stripped = hex_str.lstrip("#").upper()
    rr, gg, bb = stripped[0:2], stripped[2:4], stripped[4:6]
    return f"&H00{bb}{gg}{rr}&"
