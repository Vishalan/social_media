"""Tests for Unit 0.5 — selector/catalog/VideoJob/factory extension.

These tests cover:
  1. ``_VALID_TYPES`` includes the four new Unit 0.5 types.
  2. ``_RESPONSE_SCHEMA`` primary/fallback enums stay in sync with ``_VALID_TYPES``.
  3. ``BROLL_REGISTRY`` is a superset of ``_VALID_TYPES`` (single source of truth).
  4. Short-circuit: article URL + extracted article → phone_highlight first.
  5. Short-circuit: article URL without extract → browser_visit only.
  6. ``VideoJob`` constructs with required fields only and leaves the four
     new optional fields at their declared defaults.
  7. ``make_broll_generator`` raises ``NotImplementedError`` (with the unit
     label) for each of the four placeholder branches.
  8. CPU/GPU classification matches the pre-registry split for the seven
     existing factory types (no regressions for existing routing).

All external services are mocked; no real HTTP / LLM calls are made.
"""

from __future__ import annotations

import pytest

# Dual-import: run from repo root (scripts.broll_gen...) or from scripts/.
try:
    from scripts.broll_gen.factory import make_broll_generator
    from scripts.broll_gen.registry import (
        BROLL_REGISTRY,
        cpu_types,
        gpu_types,
        valid_types,
    )
    from scripts.broll_gen.selector import (
        _RESPONSE_SCHEMA,
        _VALID_TYPES,
        BrollSelector,
    )
except ImportError:  # pragma: no cover — fallback when cwd is scripts/
    from broll_gen.factory import make_broll_generator  # type: ignore[no-redef]
    from broll_gen.registry import (  # type: ignore[no-redef]
        BROLL_REGISTRY,
        cpu_types,
        gpu_types,
        valid_types,
    )
    from broll_gen.selector import (  # type: ignore[no-redef]
        _RESPONSE_SCHEMA,
        _VALID_TYPES,
        BrollSelector,
    )


_NEW_TYPES_UNIT_05 = {
    "phone_highlight",
    "tweet_reveal",
    "split_screen",
    "cinematic_chart",
}

# Pre-registry classification: ``cpu_types = [t for t in types if t != "ai_video"]``
# — everything in the factory chain except ``ai_video`` is CPU-routed.
_EXISTING_FACTORY_TYPES = {
    "browser_visit",
    "image_montage",
    "code_walkthrough",
    "stats_card",
    "headline_burst",
    "stock_video",
    "ai_video",
}
_PRE_REGISTRY_GPU = {"ai_video"}
_PRE_REGISTRY_CPU = _EXISTING_FACTORY_TYPES - _PRE_REGISTRY_GPU


# ── 1. _VALID_TYPES includes the four new types ───────────────────────────────

def test_valid_types_includes_new_four() -> None:
    missing = _NEW_TYPES_UNIT_05 - set(_VALID_TYPES)
    assert not missing, f"_VALID_TYPES missing new Unit 0.5 types: {missing}"


# ── 2. Response schema enums stay in sync with _VALID_TYPES ───────────────────

def test_response_schema_enums_in_sync() -> None:
    primary_enum = set(_RESPONSE_SCHEMA["properties"]["primary"]["enum"])
    fallback_enum = set(_RESPONSE_SCHEMA["properties"]["fallback"]["enum"])
    assert primary_enum == fallback_enum, (
        "primary and fallback enums must be identical — selector requires "
        "both sides to allow the same set of types."
    )
    assert primary_enum == set(_VALID_TYPES), (
        f"_RESPONSE_SCHEMA enum is out of sync with _VALID_TYPES: "
        f"enum={primary_enum} valid={set(_VALID_TYPES)}"
    )


# ── 3. Registry covers every catalog-eligible type ────────────────────────────

def test_registry_covers_all_valid_types() -> None:
    uncovered = set(_VALID_TYPES) - set(BROLL_REGISTRY)
    assert not uncovered, (
        f"BROLL_REGISTRY is missing entries for types in _VALID_TYPES: {uncovered}"
    )
    # Spot-check: metadata descriptions are non-empty strings.
    for name in _VALID_TYPES:
        meta = BROLL_REGISTRY[name]
        assert isinstance(meta.description, str) and meta.description.strip(), (
            f"BROLL_REGISTRY[{name!r}] has empty description"
        )


# ── 4. Short-circuit: article + extract → phone_highlight first ───────────────

def test_short_circuit_article_with_extract_prefers_phone_highlight() -> None:
    extracted = {
        "title": "Some article",
        "lead_paragraph": "Lead para.",
        "body_paragraphs": [
            "First body paragraph discussing the new model.",
            "Second body paragraph with more detail and quotes.",
            "Third body paragraph expanding the argument.",
        ],
    }
    candidates = BrollSelector._compute_forced_primary_candidates(
        topic_url="https://example.com/some-article",
        extracted_article=extracted,
    )
    assert candidates == ["phone_highlight", "browser_visit"], (
        "With a real article URL and ≥2 body paragraphs, Haiku must be biased "
        "toward phone_highlight first, browser_visit second."
    )


# ── 5. Short-circuit without extract → browser_visit only ─────────────────────

def test_short_circuit_article_without_extract_falls_back() -> None:
    candidates_none = BrollSelector._compute_forced_primary_candidates(
        topic_url="https://example.com/some-article",
        extracted_article=None,
    )
    assert candidates_none == ["browser_visit"], (
        "Without an extracted article, only browser_visit should be forced."
    )

    # Sanity: an extract with <2 body paragraphs is equivalent to None here.
    candidates_thin = BrollSelector._compute_forced_primary_candidates(
        topic_url="https://example.com/some-article",
        extracted_article={"body_paragraphs": ["only one paragraph"]},
    )
    assert candidates_thin == ["browser_visit"]

    # Sanity: social URLs short-circuit to None (Haiku picks freely).
    for social in (
        "https://www.youtube.com/watch?v=abc",
        "https://twitter.com/user/status/1",
        "https://x.com/user/status/1",
        "https://www.reddit.com/r/ml/comments/xyz",
    ):
        assert (
            BrollSelector._compute_forced_primary_candidates(social, None) is None
        ), f"social URL {social!r} must NOT force any candidate list"


# ── 6. VideoJob defaults for the four new optional fields ─────────────────────

def test_videojob_new_fields_default_values() -> None:
    # Import inside the test so that test collection does not fail on systems
    # where the full pipeline's sibling imports are unavailable — but in this
    # worktree they are available, so the import succeeds.
    from commoncreed_pipeline import VideoJob

    job = VideoJob(
        topic={"title": "t", "url": "https://example.com/x"},
        script={"script": "hello"},
        trimmed_audio_path="/tmp/a.mp3",
        avatar_path="/tmp/a.mp4",
    )
    assert job.extracted_article is None
    assert job.tweet_quote is None
    assert job.split_screen_pair is None
    assert job.keyword_punches == []


# ── 7. Factory placeholder branches raise NotImplementedError ─────────────────

@pytest.mark.parametrize(
    ("type_name", "expected_unit", "wired"),
    [
        # Unit A1 is now wired — factory returns a real generator instead of
        # raising NotImplementedError. The `wired` flag flips this test's
        # assertion so the parametrize row still runs (keeping the count
        # stable) and the positive-path contract is covered here, alongside
        # the deeper coverage in test_phone_highlight.py::test_factory_wiring.
        ("phone_highlight", "A1", True),
        ("tweet_reveal", "B1", False),
        ("split_screen", "B2", False),
        ("cinematic_chart", "C2", False),
    ],
)
def test_factory_raises_notimplemented_for_new_types(
    type_name: str, expected_unit: str, wired: bool
) -> None:
    if wired:
        # Type has been implemented — factory must return a BrollBase subclass
        # and NOT raise. Individual behavior is tested in the per-unit test
        # file (e.g. test_phone_highlight.py for A1).
        gen = make_broll_generator(type_name)
        from broll_gen.base import BrollBase  # type: ignore[import-not-found]
        assert isinstance(gen, BrollBase), (
            f"factory returned non-BrollBase for wired type {type_name!r}: {gen!r}"
        )
        return

    with pytest.raises(NotImplementedError) as excinfo:
        make_broll_generator(type_name)
    msg = str(excinfo.value)
    assert type_name in msg, f"NotImplementedError for {type_name} must name the type"
    assert expected_unit in msg, (
        f"NotImplementedError for {type_name} must mention the unit that wires it "
        f"(expected {expected_unit!r}): {msg!r}"
    )


# ── 8. Existing types keep their CPU/GPU classification ───────────────────────

def test_cpu_gpu_classification_unchanged_for_existing_types() -> None:
    existing_cpu_now = cpu_types() & _EXISTING_FACTORY_TYPES
    existing_gpu_now = gpu_types() & _EXISTING_FACTORY_TYPES
    assert existing_cpu_now == _PRE_REGISTRY_CPU, (
        f"CPU classification regressed for existing types. "
        f"before={_PRE_REGISTRY_CPU} now={existing_cpu_now}"
    )
    assert existing_gpu_now == _PRE_REGISTRY_GPU, (
        f"GPU classification regressed for existing types. "
        f"before={_PRE_REGISTRY_GPU} now={existing_gpu_now}"
    )
    # Also: valid_types() must include every existing factory type.
    assert _EXISTING_FACTORY_TYPES.issubset(valid_types())
