"""Colour maths shared by everything that draws.

Exists because legibility is a property of a PAIR, and that has to be computed
the same way everywhere. Two separate ad-hoc "is this colour too dark" checks
had grown up here — one in the thumbnail, one in the brand extractor — and both
asked about a single colour in isolation, which cannot answer the question.
The Remotion side has a matching implementation in `theme.ts`; the duplication
across the language boundary is unavoidable, so the thresholds are named
identically in both to make them findable together.
"""
from __future__ import annotations

# WCAG AA: 4.5:1 for body text, 3:1 for large display type.
MIN_TEXT = 4.5
MIN_LARGE = 3.0


def to_rgb(hexstr: str, fallback: tuple[int, int, int] = (11, 13, 17)
           ) -> tuple[int, int, int]:
    """Parse #rrggbb. Returns `fallback` rather than raising."""
    try:
        h = str(hexstr).strip().lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) != 6:
            return fallback
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except (ValueError, AttributeError, TypeError):
        return fallback


def rel_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG relative luminance.

    Linearises sRGB first. A plain 0-255 average is what let a 1.2:1 pair pass
    an earlier brightness check — the eye's response is not linear in the
    encoded value.
    """
    out = []
    for v in rgb:
        c = v / 255
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """1 (identical) to 21 (black on white)."""
    la, lb = rel_luminance(a), rel_luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def readable_on(bg: tuple[int, int, int],
                dark: tuple[int, int, int] = (11, 13, 17),
                light: tuple[int, int, int] = (255, 255, 255)
                ) -> tuple[int, int, int]:
    """Whichever of ink or paper reads on `bg`."""
    return light if contrast_ratio(light, bg) >= contrast_ratio(dark, bg) else dark


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % rgb


def vivid(hexstr: str, *, lo: float = 0.16, hi: float = 0.42,
          min_sat: float = 0.55) -> str:
    """A version of a colour that reads on BOTH a light and a dark backdrop.

    Display captions sit over moving footage, so there is no single background
    to measure against — the sky behind a word at one frame is a rocket at the
    next. `contrast_ratio` answers the question for a known pair and cannot
    answer this one.

    What survives both is a colour held in a middle luminance band and pushed
    to high saturation: dark enough to read on cream, bright enough to read on
    near-black, and saturated enough that it is unmistakably an accent rather
    than grey. The reference's coral is exactly that. A story palette often
    is not — the accent picked for the Anthropic story rendered near-white
    over a bright sky and vanished.
    """
    import colorsys
    r, g, b = (c / 255 for c in to_rgb(hexstr))
    h, l, sat = colorsys.rgb_to_hls(r, g, b)
    sat = max(sat, min_sat)
    if rel_luminance(to_rgb(hexstr)) > hi:
        l = min(l, 0.56)
    if rel_luminance(to_rgb(hexstr)) < lo:
        l = max(l, 0.44)
    l = min(max(l, 0.42), 0.58)
    rr, gg, bb = colorsys.hls_to_rgb(h, l, sat)
    return to_hex((int(rr * 255), int(gg * 255), int(bb * 255)))
