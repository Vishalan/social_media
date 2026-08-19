"""Render designed motion graphics with Remotion.

Replaces the HyperFrames path, in which `claude -p` authored brand-new
animation code for every graphic. That approach could not hold a quality bar,
and the reasons were structural rather than fixable by prompting:

* Every clip was a one-off, so nothing was consistent between them — each
  invented its own type scale, spacing and rhythm.
* Nothing tied the animation to the clip length, so graphics froze. Measured on
  shipped output: a 2.6s stats card whose last motion was at 0.52s.
* Nothing enforced legibility, so content filled 26-29% of the panel at type
  too small to read on a phone.
* Each graphic cost roughly ten minutes, plus a vision review and often a
  re-render.

Remotion inverts the split. The COMPOSITIONS are hand-built React components,
written once and reviewed once, where timing and type scale are structural: the
build phase is a fraction of the clip, sizes derive from the canvas, and text is
fitted by measuring the real font. The model supplies only DATA.

Measured against the previous path on the same host: 8 graphics in 35 seconds,
versus roughly 10 minutes each.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Where the Remotion project lives on the render host. Overridable so the same
# code runs from a checkout or a deployed copy.
PROJECT_DIR = os.environ.get("REMOTION_PROJECT", "/home/vishalan/remotion-broll")
ENTRY = "src/index.ts"


class RemotionError(RuntimeError):
    """Raised when a composition cannot be rendered."""


# Slot kind -> (composition id, required prop names).
#
# The required list is checked before rendering: Remotion would otherwise render
# a card with `undefined` where a figure should be, which produces a clip that
# looks fine to a duration check and is nonsense on screen.
COMPOSITIONS: dict[str, tuple[str, tuple[str, ...]]] = {
    "stats_card": ("StatCard", ("value",)),
    "headline_burst": ("HeadlineBurst", ("headline",)),
    "mechanism": ("Mechanism", ("steps",)),
    "split_screen": ("SplitScreen", ("left", "right")),
    "code_walkthrough": ("CodeWalkthrough", ("lines",)),
    "cinematic_chart": ("CinematicChart", ("bars",)),
    "tweet_reveal": ("QuoteCard", ("quote", "author")),
    "lockup": ("Lockup", ("title",)),
    # The presenter-span bed: one source sentence as a pull-quote.
    # An app window on a full-bleed brand field — an OBJECT, not a card.
    "window_scene": ("WindowScene", ("title", "lines")),
    # A real diagram: nodes, drawn connectors, a token travelling the path.
    "flow_scene": ("FlowScene", ("stages",)),
    "source_pull": ("SourcePull", ("sentence",)),
    # The call to action, placed where it is spoken.
    "cta": ("CtaCard", ("action",)),
}


def _empty(value: Any) -> bool:
    """Whether a prop is missing in a way that would render a broken graphic.

    Checks INSIDE containers, not just for their presence. SplitScreen's `left`
    and `right` are dicts, so a truthiness test passed a side whose `value` was
    an empty string and shipped a comparison card with one column blank —
    exactly the kind of half-rendered frame that reads as a bug to a viewer.
    A list of empty strings fails for the same reason.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, dict):
        return not value or any(_empty(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        items = [v for v in value if not _empty(v)]
        return not items
    return False


def available() -> bool:
    """Whether Remotion can render on this host."""
    entry = Path(PROJECT_DIR) / ENTRY
    modules = Path(PROJECT_DIR) / "node_modules" / "remotion"
    return entry.is_file() and modules.is_dir()


def render(
    *,
    kind: str,
    props: dict[str, Any],
    out_path: str,
    duration_s: float,
    width: int = 1080,
    height: int = 998,
    fps: int = 25,
    palette: Optional[list[str]] = None,
    timeout_s: int = 600,
) -> str:
    """Render one composition to ``out_path``.

    Args:
        kind: a b-roll slot kind; mapped to a composition via COMPOSITIONS.
        props: the composition's own data (value, headline, steps, ...).
        duration_s: clip length. The composition scales its whole build to this,
            so the same graphic works at 2.6s or 6s without freezing.
    """
    if kind not in COMPOSITIONS:
        raise RemotionError(f"no composition for kind {kind!r}")
    comp, required = COMPOSITIONS[kind]

    missing = [k for k in required if _empty(props.get(k))]
    if missing:
        raise RemotionError(
            f"{comp} needs {', '.join(missing)} — refusing to render a graphic "
            f"with empty content")

    payload = {
        **props,
        "palette": palette or ["#0B0D11", "#FFFFFF", "#22D3EE"],
        "width": width,
        "height": height,
        "fps": fps,
        "durationInSeconds": round(float(duration_s), 3),
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    cmd = ["npx", "remotion", "render", ENTRY, comp, os.path.abspath(out_path),
           "--props", json.dumps(payload, ensure_ascii=False),
           "--log", "error"]
    r = subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=True, text=True,
                       timeout=timeout_s)
    if r.returncode != 0 or not os.path.exists(out_path):
        raise RemotionError(
            f"{comp} render failed: {(r.stderr or r.stdout or '')[-400:]}")
    logger.info("Remotion %s -> %s (%.2fs)", comp, Path(out_path).name,
                duration_s)
    return out_path
