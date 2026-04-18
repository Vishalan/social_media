"""
B-roll type registry — single source of truth for which b-roll types exist,
whether they need the GPU pod, and which optional VideoJob field gates them.

The registry is consumed by:
  * commoncreed_pipeline.py — to decide whether any topic needs the GPU pod (Phase 2).
  * smoke_e2e.py            — mirror of the pipeline routing logic.
  * broll_gen.selector       — to cross-check that _VALID_TYPES covers the registry.
  * unit tests               — to assert classification has not drifted.

Existing 7 types (pre Unit 0.5) are classified from the `cpu_types` /
`gpu_types` split that previously lived inline in commoncreed_pipeline.py
(``cpu_types = [t for t in types if t != "ai_video"]``). The only GPU-bound
type is ``ai_video``; everything else is CPU-only.

Unit 0.5 adds four new CPU-bound types that are gated by optional VideoJob
fields; the real generator implementations land in Wave 2 (A1 / B1 / B2 / C2).
Until then, ``factory.make_broll_generator`` raises ``NotImplementedError`` for
the four new types.
"""

from __future__ import annotations

from typing import NamedTuple


class BrollMeta(NamedTuple):
    """Catalog metadata for a single b-roll type.

    Attributes:
        needs_gpu: True when generation requires the ComfyUI / Wan2.1 pod
            (drives Phase 2 pod lifecycle in the daily pipeline).
        blocked_by_field_missing: Name of the optional ``VideoJob`` field that
            gates this type. ``None`` when the type is always available.
        description: One-line description reused by the selector's system
            prompt and for humans debugging the catalog.
    """

    needs_gpu: bool
    blocked_by_field_missing: str | None
    description: str


BROLL_REGISTRY: dict[str, BrollMeta] = {
    # ── Existing types (classification preserved from pre-registry routing) ──
    "browser_visit": BrollMeta(
        needs_gpu=False,
        blocked_by_field_missing=None,
        description=(
            "topic has a real article URL worth visiting (not YouTube/Twitter/social)"
        ),
    ),
    "image_montage": BrollMeta(
        needs_gpu=False,
        blocked_by_field_missing=None,
        description=(
            "general tech news, product reveal, company story; good fallback when "
            "Pexels key is available"
        ),
    ),
    "code_walkthrough": BrollMeta(
        needs_gpu=False,
        blocked_by_field_missing=None,
        description=(
            "topic involves API, model, framework, SDK, \"how to use X\", or a code release"
        ),
    ),
    "stats_card": BrollMeta(
        needs_gpu=False,
        blocked_by_field_missing=None,
        description=(
            "script has 2+ NUMERIC stats/benchmarks (e.g. \"15x faster\", \"60% cheaper\", "
            "\"82 tokens/s\")"
        ),
    ),
    "headline_burst": BrollMeta(
        needs_gpu=False,
        blocked_by_field_missing=None,
        description=(
            "topic is a major announcement, dramatic claim, or \"breaking news\" — great "
            "for viral impact"
        ),
    ),
    "stock_video": BrollMeta(
        needs_gpu=False,
        blocked_by_field_missing=None,
        description=(
            "cinematic real-world footage for emotional or context-setting beats; use for "
            "topics involving data centers, smartphones, keyboards, server rooms, or any "
            "scene where cinematic real-world footage reinforces the mood"
        ),
    ),
    "ai_video": BrollMeta(
        needs_gpu=True,
        blocked_by_field_missing=None,
        description="only for abstract/speculative topics with zero concrete visuals",
    ),
    # ── Unit 0.5 new types (real implementations land in Wave 2) ─────────────
    "phone_highlight": BrollMeta(
        needs_gpu=False,
        blocked_by_field_missing="extracted_article",
        description=(
            "Vertical phone mockup of the article being narrated, with the spoken "
            "phrase highlighted in real time."
        ),
    ),
    "tweet_reveal": BrollMeta(
        needs_gpu=False,
        blocked_by_field_missing="tweet_quote",
        description=(
            "CommonCreed-branded tweet card with animated like counter. Select when "
            "source article quotes a named person."
        ),
    ),
    "split_screen": BrollMeta(
        needs_gpu=False,
        blocked_by_field_missing="split_screen_pair",
        description=(
            "Vertical 50/50 split-screen comparison with center wipe. Select for "
            "A-vs-B topics."
        ),
    ),
    "cinematic_chart": BrollMeta(
        needs_gpu=False,
        blocked_by_field_missing=None,
        description=(
            "Animated bar chart / number ticker / line chart rendered by the Remotion "
            "sidecar. Gated by CINEMATIC_CHART_ENABLED env flag and numeric-density signal."
        ),
    ),
}


def cpu_types() -> frozenset[str]:
    """Return the set of b-roll types that run without the GPU pod."""
    return frozenset(name for name, meta in BROLL_REGISTRY.items() if not meta.needs_gpu)


def gpu_types() -> frozenset[str]:
    """Return the set of b-roll types that require the GPU pod (Phase 2)."""
    return frozenset(name for name, meta in BROLL_REGISTRY.items() if meta.needs_gpu)


def valid_types() -> frozenset[str]:
    """Return all registered b-roll type names (CPU + GPU)."""
    return frozenset(BROLL_REGISTRY.keys())
