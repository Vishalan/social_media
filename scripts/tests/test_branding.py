"""Tests for Unit 0.1 — scripts.branding.

All tests are hermetic: no network, no real font downloads. They only assert
that the in-repo Inter TTFs (committed alongside this module) and the brand
constants line up with what the rest of the pipeline expects.
"""

from __future__ import annotations

import os
import re

import pytest

# Support dual-import: run from repo root (scripts.branding) or from scripts/.
try:
    from scripts.branding import (
        BOLD_FONT_CANDIDATES,
        NAVY,
        REGULAR_FONT_CANDIDATES,
        SEMIBOLD_FONT_CANDIDATES,
        SKY_BLUE,
        WHITE,
        find_font,
        to_ass_color,
    )
except ImportError:  # pragma: no cover — fallback when cwd is scripts/
    from branding import (  # type: ignore[no-redef]
        BOLD_FONT_CANDIDATES,
        NAVY,
        REGULAR_FONT_CANDIDATES,
        SEMIBOLD_FONT_CANDIDATES,
        SKY_BLUE,
        WHITE,
        find_font,
        to_ass_color,
    )


# ─── find_font ────────────────────────────────────────────────────────────────


def test_find_font_bold_exists():
    path = find_font("bold")
    assert os.path.exists(path), f"find_font('bold') returned non-existent {path}"


def test_find_font_regular_and_semibold():
    for weight in ("regular", "semibold"):
        path = find_font(weight)  # type: ignore[arg-type]
        assert os.path.exists(path), f"find_font({weight!r}) returned non-existent {path}"


def test_find_font_invalid_weight():
    with pytest.raises(ValueError):
        find_font("heavy")  # type: ignore[arg-type]


# ─── to_ass_color ─────────────────────────────────────────────────────────────


def test_to_ass_color_sky_blue():
    assert to_ass_color("#5C9BFF") == "&H00FF9B5C&"


def test_to_ass_color_navy():
    assert to_ass_color("#1E3A8A") == "&H008A3A1E&"


def test_to_ass_color_white():
    assert to_ass_color("#FFFFFF") == "&H00FFFFFF&"


def test_to_ass_color_invalid():
    with pytest.raises(ValueError):
        to_ass_color("not-hex")


# ─── Brand constants ──────────────────────────────────────────────────────────


def test_brand_constants_present():
    hex_re = re.compile(r"^#[0-9A-F]{6}$")
    for name, value in (("NAVY", NAVY), ("SKY_BLUE", SKY_BLUE), ("WHITE", WHITE)):
        assert hex_re.match(value), f"{name}={value!r} does not match ^#[0-9A-F]{{6}}$"


def test_candidate_lists_start_with_repo_inter():
    """Sanity check that the first candidate is always the in-repo Inter TTF.

    Protects against future refactors accidentally demoting the bundled font.
    """
    assert BOLD_FONT_CANDIDATES[0] == "assets/fonts/Inter-Bold.ttf"
    assert REGULAR_FONT_CANDIDATES[0] == "assets/fonts/Inter-Regular.ttf"
    assert SEMIBOLD_FONT_CANDIDATES[0] == "assets/fonts/Inter-SemiBold.ttf"
