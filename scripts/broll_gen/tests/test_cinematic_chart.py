"""Tests for Unit C2 — CinematicChartGenerator + selector numeric-density gating.

All external services are mocked:
  - ``httpx.AsyncClient`` is patched so no real HTTP is issued.
  - Claude Haiku (for ``extract_chart_spec``) uses an ``AsyncMock``.

Covers:
  1. ``test_generate_happy_path_mocked`` — mocked 200 response → returns
     the sidecar's output_path.
  2. ``test_http_error_raises_brollerror`` — mocked 500 → BrollError with
     the "remotion render failed" prefix.
  3. ``test_timeout_raises`` — mocked ``httpx.TimeoutException`` → BrollError.
  4. ``test_env_flag_gating_selector`` — with ``CINEMATIC_CHART_ENABLED``
     unset, the selector's chart-forced helper returns ``None`` even when
     a ``chart_spec`` is present.
  5. ``test_factory_wiring`` — ``make_broll_generator("cinematic_chart")``
     returns a ``CinematicChartGenerator`` instance.
  6. ``test_extract_chart_spec_returns_none_when_no_numbers`` — Haiku
     returns ``null`` for a purely narrative script.
  7. ``test_generate_missing_spec_raises`` — gate-down path: flag on but
     no ``chart_spec`` on the job → BrollError.
  8. ``test_selector_gating_prefers_chart_when_flag_on`` — with the env
     flag and ``chart_spec`` both set, the selector forces
     ``["cinematic_chart", "stats_card"]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Dual-import: prefer the bare ``broll_gen.*`` path (matches factory.py's
# imports so ``isinstance`` checks line up), fall back to ``scripts.*``.
try:
    from broll_gen import cinematic_chart as cc_module  # type: ignore[import-not-found]
    from broll_gen.base import BrollError  # type: ignore[import-not-found]
    from broll_gen.cinematic_chart import (  # type: ignore[import-not-found]
        CinematicChartGenerator,
        extract_chart_spec,
    )
    from broll_gen.factory import make_broll_generator  # type: ignore[import-not-found]
    from broll_gen.selector import BrollSelector  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — repo-root-only sys.path fallback
    from scripts.broll_gen import cinematic_chart as cc_module  # type: ignore[no-redef]
    from scripts.broll_gen.base import BrollError  # type: ignore[no-redef]
    from scripts.broll_gen.cinematic_chart import (  # type: ignore[no-redef]
        CinematicChartGenerator,
        extract_chart_spec,
    )
    from scripts.broll_gen.factory import make_broll_generator  # type: ignore[no-redef]
    from scripts.broll_gen.selector import BrollSelector  # type: ignore[no-redef]


# ─── Synthetic VideoJob ──────────────────────────────────────────────────────


@dataclass
class _FakeVideoJob:
    """Minimal VideoJob stand-in — only fields the generator reads."""

    topic: dict = field(default_factory=dict)
    script: dict = field(default_factory=dict)
    audio_url: str = ""
    chart_spec: Optional[dict] = None


def _valid_chart_spec() -> dict:
    return {
        "template": "bar_chart",
        "props": {
            "title": "Benchmark scores",
            "bars": [
                {"label": "GPT-5", "value": 92, "suffix": "%"},
                {"label": "GPT-4", "value": 78, "suffix": "%"},
            ],
        },
        "target_duration_s": 5.0,
    }


# ─── httpx mocking helpers ───────────────────────────────────────────────────


def _make_response(status_code: int, payload: dict) -> MagicMock:
    """Build a MagicMock that quacks like ``httpx.Response``."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=payload)
    resp.text = str(payload)
    return resp


class _AsyncClientCM:
    """Drop-in for ``httpx.AsyncClient(timeout=...)`` as an async context manager.

    The ``post`` method is an AsyncMock that the test can steer.
    """

    def __init__(self, *, post_return=None, post_side_effect=None) -> None:
        self.post = AsyncMock(return_value=post_return, side_effect=post_side_effect)
        self.init_kwargs: dict = {}

    async def __aenter__(self) -> "_AsyncClientCM":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _patch_async_client(client_cm: _AsyncClientCM):
    """Return a patch object that replaces ``httpx.AsyncClient`` with a factory
    returning ``client_cm``. Records the init kwargs so tests can assert the
    timeout was passed correctly."""
    def _factory(*args, **kwargs):
        client_cm.init_kwargs = kwargs
        return client_cm
    return patch.object(cc_module.httpx, "AsyncClient", side_effect=_factory)


# ─── 1. Happy path ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_happy_path_mocked(monkeypatch):
    """Mocked 200 response → generator returns the sidecar's output_path."""
    monkeypatch.setenv("CINEMATIC_CHART_ENABLED", "true")

    expected_path = "/app/output/1713400000000/cinematic_chart.mp4"
    resp = _make_response(
        200,
        {
            "output_path": expected_path,
            "render_time_ms": 1234,
            "duration_in_frames": 150,
            "fps": 30,
            "width": 1080,
            "height": 1920,
        },
    )
    client_cm = _AsyncClientCM(post_return=resp)

    gen = CinematicChartGenerator(base_url="http://test-remotion:3030")
    job = _FakeVideoJob(
        chart_spec=_valid_chart_spec(),
        audio_url="https://cdn.example.com/audio.mp3",
    )

    with _patch_async_client(client_cm):
        result = await gen.generate(job, target_duration_s=5.0, output_path="/unused")

    assert result == expected_path

    # Verify the payload went to the right endpoint with correct shape.
    client_cm.post.assert_awaited_once()
    call_args = client_cm.post.await_args
    assert call_args.args[0] == "http://test-remotion:3030/render"
    sent_payload = call_args.kwargs["json"]
    assert sent_payload["template_id"] == "bar_chart"
    assert sent_payload["audio_url"] == "https://cdn.example.com/audio.mp3"
    assert sent_payload["target_duration_s"] == 5.0
    assert sent_payload["props"]["bars"][0]["label"] == "GPT-5"


# ─── 2. HTTP error ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_http_error_raises_brollerror(monkeypatch):
    """500 response → BrollError whose message contains ``remotion render failed``."""
    monkeypatch.setenv("CINEMATIC_CHART_ENABLED", "true")

    resp = _make_response(500, {"error": "bundle failed"})
    client_cm = _AsyncClientCM(post_return=resp)

    gen = CinematicChartGenerator(base_url="http://test-remotion:3030")
    job = _FakeVideoJob(chart_spec=_valid_chart_spec())

    with _patch_async_client(client_cm):
        with pytest.raises(BrollError, match="remotion render failed"):
            await gen.generate(job, target_duration_s=4.0, output_path="/unused")


# ─── 3. Timeout ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timeout_raises(monkeypatch):
    """httpx.TimeoutException → BrollError (wrapped with a useful message)."""
    monkeypatch.setenv("CINEMATIC_CHART_ENABLED", "true")

    client_cm = _AsyncClientCM(
        post_side_effect=httpx.TimeoutException("deadline exceeded")
    )

    gen = CinematicChartGenerator(base_url="http://test-remotion:3030", timeout_s=5.0)
    job = _FakeVideoJob(chart_spec=_valid_chart_spec())

    with _patch_async_client(client_cm):
        with pytest.raises(BrollError, match="timed out"):
            await gen.generate(job, target_duration_s=4.0, output_path="/unused")


# ─── 4. Env-flag gating (selector level, no chart preferred) ─────────────────


def test_env_flag_gating_selector(monkeypatch):
    """With ``CINEMATIC_CHART_ENABLED`` unset, the chart-forced helper returns
    ``None`` even when a chart_spec is present. The selector therefore falls
    through to the other gating regions (article / tweet / split)."""
    monkeypatch.delenv("CINEMATIC_CHART_ENABLED", raising=False)

    assert BrollSelector._compute_chart_forced_candidates(_valid_chart_spec()) is None

    # Also: explicitly false is a no-op.
    monkeypatch.setenv("CINEMATIC_CHART_ENABLED", "false")
    assert BrollSelector._compute_chart_forced_candidates(_valid_chart_spec()) is None

    # And: flag on but no chart_spec → None (nothing to route to).
    monkeypatch.setenv("CINEMATIC_CHART_ENABLED", "true")
    assert BrollSelector._compute_chart_forced_candidates(None) is None
    assert BrollSelector._compute_chart_forced_candidates({}) is None


# ─── 5. Factory wiring ───────────────────────────────────────────────────────


def test_factory_wiring():
    """make_broll_generator("cinematic_chart") returns CinematicChartGenerator."""
    gen = make_broll_generator("cinematic_chart")
    assert isinstance(gen, CinematicChartGenerator)


# ─── 6. extract_chart_spec returns None for purely narrative scripts ─────────


@pytest.mark.asyncio
async def test_extract_chart_spec_returns_none_when_no_numbers():
    """Haiku returns ``chart_spec=null`` for a narrative script → function
    returns ``None``."""
    client = MagicMock()
    # Simulate Claude's JSON-schema output: chart_spec is null.
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text='{"chart_spec": null}')]
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=fake_response)

    script = (
        "OpenAI released a new model today that focuses on better reasoning "
        "and safety. The release notes highlight qualitative improvements "
        "without publishing concrete benchmarks."
    )
    result = await extract_chart_spec(client, script, topic={"title": "OpenAI release"})
    assert result is None


# ─── 7. Missing chart_spec on job ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_missing_spec_raises(monkeypatch):
    """Flag on + no ``chart_spec`` on the job → BrollError (no HTTP issued)."""
    monkeypatch.setenv("CINEMATIC_CHART_ENABLED", "true")
    gen = CinematicChartGenerator(base_url="http://test-remotion:3030")
    job = _FakeVideoJob(chart_spec=None)

    with pytest.raises(BrollError, match="cinematic_chart requires job.chart_spec"):
        await gen.generate(job, target_duration_s=4.0, output_path="/unused")


@pytest.mark.asyncio
async def test_generate_env_flag_off_raises(monkeypatch):
    """Flag off → BrollError even with a valid chart_spec (defensive guard —
    the selector should have gated this out, but the generator never taxes the
    sidecar on its own)."""
    monkeypatch.delenv("CINEMATIC_CHART_ENABLED", raising=False)
    gen = CinematicChartGenerator(base_url="http://test-remotion:3030")
    job = _FakeVideoJob(chart_spec=_valid_chart_spec())

    with pytest.raises(BrollError, match="cinematic_chart disabled"):
        await gen.generate(job, target_duration_s=4.0, output_path="/unused")


# ─── 8. Selector gating: chart preferred when flag+spec both present ─────────


def test_selector_gating_prefers_chart_when_flag_on(monkeypatch):
    """With ``CINEMATIC_CHART_ENABLED=true`` + non-null chart_spec, the
    selector's chart gating region returns ``["cinematic_chart", "stats_card"]``
    — the primary-ordering guarantee that other Wave-2 units rely on."""
    monkeypatch.setenv("CINEMATIC_CHART_ENABLED", "true")

    forced = BrollSelector._compute_chart_forced_candidates(_valid_chart_spec())
    assert forced == ["cinematic_chart", "stats_card"]
