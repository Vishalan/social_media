"""Tests for Unit B2 — SplitScreenGenerator (A/B composer).

Covers:

  1. ``test_happy_path_mocked`` — mock both sub-generators and the FFmpeg
     subprocess; assert the composer returns the output path.
  2. ``test_missing_split_pair_raises`` — VideoJob without
     ``split_screen_pair`` → ``BrollError("split_screen requires ...")``.
  3. ``test_width_override_browser_visit`` — BrowserVisitGenerator with
     ``width_override=540`` uses 540 in the Playwright viewport config.
  4. ``test_width_override_headline_burst`` — HeadlineBurstGenerator renders
     a 540-wide canvas when ``width_override=540``.
  5. ``test_factory_wiring`` — ``make_broll_generator("split_screen", ...)``
     returns a ``SplitScreenGenerator`` instance.
  6. ``test_concurrent_sub_generators`` — ``asyncio.gather`` is used and
     both sides are awaited concurrently.

All network / subprocess / Playwright / PIL I/O is mocked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Dual-import so tests pass whether pytest is invoked from the repo root
# (``python -m pytest scripts/...``) or from ``scripts/`` directly.
try:
    from scripts.broll_gen.base import BrollError
    from scripts.broll_gen.factory import make_broll_generator
    from scripts.broll_gen.headline_burst import HeadlineBurstGenerator
    from scripts.broll_gen.split_screen import (
        _FULL_H,
        _FULL_W,
        _HALF_W,
        SplitScreenGenerator,
    )
except ImportError:  # pragma: no cover — fallback when cwd is scripts/
    from broll_gen.base import BrollError  # type: ignore[no-redef]
    from broll_gen.factory import make_broll_generator  # type: ignore[no-redef]
    from broll_gen.headline_burst import HeadlineBurstGenerator  # type: ignore[no-redef]
    from broll_gen.split_screen import (  # type: ignore[no-redef]
        _FULL_H,
        _FULL_W,
        _HALF_W,
        SplitScreenGenerator,
    )


# ─── Factory-patch helper ────────────────────────────────────────────────────
#
# ``split_screen._render_side`` dual-imports the factory:
#     try:    from scripts.broll_gen.factory import make_broll_generator
#     except: from broll_gen.factory       import make_broll_generator
#
# Which module is actually resolved depends on the pytest invocation cwd
# (``scripts/`` vs repo root). We probe for the usable form once and patch
# only that one — patching a non-importable module path would itself raise.


def _patch_factory(side_effect):
    """Return a contextmanager that patches whichever factory module is importable.

    Both dual-import aliases point at the same underlying function, so
    patching a single one is sufficient: when the function is looked up via
    ``from X import make_broll_generator`` at call time, the patched binding
    is picked up on either alias.
    """
    try:
        import scripts.broll_gen.factory  # noqa: F401 — import probe only
        target = "scripts.broll_gen.factory.make_broll_generator"
    except ImportError:
        target = "broll_gen.factory.make_broll_generator"
    return patch(target, side_effect=side_effect)


# ─── Minimal VideoJob stubs ──────────────────────────────────────────────────


@dataclass
class _BaseJob:
    """Minimal VideoJob stand-in covering the fields SplitScreen reads."""

    topic: dict = field(default_factory=lambda: {"title": "A vs B", "url": ""})
    script: dict = field(default_factory=lambda: {"script": "Comparison script."})
    split_screen_pair: dict | None = None


# ─── 1. Happy path ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_mocked(tmp_path):
    """Two mocked sub-generators + mocked FFmpeg → composer returns output path."""

    output_path = str(tmp_path / "broll.mp4")

    # Mock sub-generator instances — each has an async generate() that just
    # writes a placeholder file so the hstack step has inputs to reference.
    left_gen = MagicMock()
    right_gen = MagicMock()

    async def _fake_generate(job, target_duration_s, output_path):
        # Touch the output path so any downstream file checks pass.
        from pathlib import Path
        Path(output_path).write_bytes(b"\x00mp4-stub")
        return output_path

    left_gen.generate = AsyncMock(side_effect=_fake_generate)
    right_gen.generate = AsyncMock(side_effect=_fake_generate)

    # Factory stub that hands back the correct instance per type and records
    # the kwargs it was called with (so we can assert width_override=540).
    factory_calls: list[tuple[str, dict]] = []

    def _fake_factory(type_name: str, **kwargs):
        factory_calls.append((type_name, kwargs))
        return {"browser_visit": left_gen, "stats_card": right_gen}[type_name]

    job = _BaseJob(
        split_screen_pair={
            "left": {"generator_type": "browser_visit", "params": {}},
            "right": {"generator_type": "stats_card",
                      "params": {"anthropic_client": MagicMock()}},
        }
    )

    gen = SplitScreenGenerator()

    # Patch the factory symbol at the module level (the one actually imported
    # inside ``_render_side``) and the subprocess hop that ffmpeg goes through.
    # Both path prefixes are patched because the dual-import inside
    # ``_render_side`` may bind either depending on the pytest invocation cwd.
    with _patch_factory(_fake_factory), patch(
        "broll_gen.split_screen.asyncio.to_thread",
        new_callable=AsyncMock,
    ) as mock_to_thread:
        ffmpeg_ok = MagicMock()
        ffmpeg_ok.returncode = 0
        mock_to_thread.return_value = ffmpeg_ok

        result = await gen.generate(job, target_duration_s=6.0, output_path=output_path)

    assert result == output_path

    # Both factory calls forced width_override=540
    assert len(factory_calls) == 2, f"expected 2 factory calls, got {factory_calls}"
    types_called = {c[0] for c in factory_calls}
    assert types_called == {"browser_visit", "stats_card"}
    for _, kwargs in factory_calls:
        assert kwargs.get("width_override") == _HALF_W, (
            f"width_override must be {_HALF_W}; got {kwargs}"
        )

    # FFmpeg hstack was invoked and targeted the output path
    assert mock_to_thread.call_count == 1
    cmd: list = mock_to_thread.call_args.args[1]
    assert cmd[0].endswith("ffmpeg") or "ffmpeg" in cmd[0]
    assert output_path in cmd
    # And the filter_complex carries hstack + the correct half-width scale
    filter_idx = cmd.index("-filter_complex") + 1
    filter_str = cmd[filter_idx]
    assert "hstack" in filter_str
    assert f"scale={_HALF_W}:{_FULL_H}" in filter_str


# ─── 2. Missing split_screen_pair ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_split_pair_raises(tmp_path):
    """VideoJob without ``split_screen_pair`` must raise BrollError with the spec message."""
    gen = SplitScreenGenerator()
    job = _BaseJob(split_screen_pair=None)

    with pytest.raises(BrollError, match="split_screen requires job.split_screen_pair"):
        await gen.generate(job, target_duration_s=5.0,
                           output_path=str(tmp_path / "broll.mp4"))


# ─── 3. width_override plumbing — BrowserVisit ────────────────────────────────


def test_width_override_browser_visit():
    """BrowserVisitGenerator(width_override=540) stores and uses 540 for viewport.

    Rather than driving the full Playwright flow (which requires the
    playwright package to be installed), we assert two things:

      1. The constructor records 540 on ``self._viewport_w``.
      2. The Playwright viewport dict inside ``_capture_sections`` is built
         from ``self._viewport_w`` — verified by AST-scanning the method
         body for the literal expression. This catches a regression where
         someone accidentally wires back to the module-level ``_VIEWPORT_W``
         constant.
    """
    try:
        from scripts.broll_gen.browser_visit import BrowserVisitGenerator
    except ImportError:  # pragma: no cover
        from broll_gen.browser_visit import BrowserVisitGenerator  # type: ignore[no-redef]

    # (1) Constructor stores the override.
    bv_override = BrowserVisitGenerator(width_override=540)
    assert bv_override._viewport_w == 540, (
        f"width_override=540 did not set self._viewport_w; "
        f"got {bv_override._viewport_w}"
    )

    # And the default path is preserved.
    bv_default = BrowserVisitGenerator()
    assert bv_default._viewport_w == 1080, (
        f"Default BrowserVisitGenerator should keep _viewport_w=1080; "
        f"got {bv_default._viewport_w}"
    )

    # (2) The viewport dict in _capture_sections uses self._viewport_w.
    # AST scan instead of running Playwright — simpler, dependency-free.
    import ast
    import inspect
    import textwrap
    raw = inspect.getsource(BrowserVisitGenerator._capture_sections)
    dedented = textwrap.dedent(raw)
    tree = ast.parse(dedented)
    viewport_call_sources: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            # Collect every dict literal's source that has a "width" key.
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            if "width" in keys:
                viewport_call_sources.append(ast.unparse(node))
    assert any(
        "self._viewport_w" in s for s in viewport_call_sources
    ), (
        f"Expected _capture_sections to build viewport dict from "
        f"self._viewport_w; found: {viewport_call_sources}"
    )


# ─── 4. width_override plumbing — HeadlineBurst ───────────────────────────────


def test_width_override_headline_burst():
    """_render_line_frame(canvas_w=540) produces a 540-wide PIL image."""
    try:
        from scripts.broll_gen.headline_burst import _render_line_frame
    except ImportError:  # pragma: no cover
        from broll_gen.headline_burst import _render_line_frame  # type: ignore[no-redef]

    img_default = _render_line_frame("Hello", 0, 0, 1, (20, 30, 200))
    img_narrow = _render_line_frame(
        "Hello", 0, 0, 1, (20, 30, 200), canvas_w=540,
    )

    assert img_default.size == (1080, 960), (
        f"Default canvas size regressed: {img_default.size}"
    )
    assert img_narrow.size == (540, 960), (
        f"canvas_w=540 override did not apply; got {img_narrow.size}"
    )

    # And HeadlineBurstGenerator(width_override=540) records the override.
    gen = HeadlineBurstGenerator(anthropic_client=MagicMock(), width_override=540)
    assert gen._canvas_w == 540


# ─── 5. Factory wiring ────────────────────────────────────────────────────────


def test_factory_wiring():
    """make_broll_generator('split_screen') returns a SplitScreenGenerator."""
    gen = make_broll_generator("split_screen")
    assert isinstance(gen, SplitScreenGenerator)


# ─── 6. Concurrent sub-generator invocation via asyncio.gather ────────────────


@pytest.mark.asyncio
async def test_concurrent_sub_generators(tmp_path):
    """Both sides are awaited concurrently via ``asyncio.gather``.

    We prove concurrency two ways:
      (a) ``asyncio.gather`` is called exactly once in the composer.
      (b) Both sub-generators' ``generate`` coroutines are awaited before
          the FFmpeg hstack pass begins.
    """
    left_gen = MagicMock()
    right_gen = MagicMock()

    call_order: list[str] = []

    async def _left_generate(job, target_duration_s, output_path):
        call_order.append("left_enter")
        await asyncio.sleep(0)  # yield control so the other side can run
        call_order.append("left_exit")
        from pathlib import Path
        Path(output_path).write_bytes(b"L")
        return output_path

    async def _right_generate(job, target_duration_s, output_path):
        call_order.append("right_enter")
        await asyncio.sleep(0)
        call_order.append("right_exit")
        from pathlib import Path
        Path(output_path).write_bytes(b"R")
        return output_path

    left_gen.generate = AsyncMock(side_effect=_left_generate)
    right_gen.generate = AsyncMock(side_effect=_right_generate)

    def _factory(type_name: str, **kwargs):
        return {"browser_visit": left_gen, "image_montage": right_gen}[type_name]

    job = _BaseJob(
        split_screen_pair={
            "left": {"generator_type": "browser_visit", "params": {}},
            "right": {"generator_type": "image_montage", "params": {}},
        }
    )

    gen = SplitScreenGenerator()
    output_path = str(tmp_path / "broll.mp4")

    ffmpeg_ok = MagicMock()
    ffmpeg_ok.returncode = 0

    with _patch_factory(_factory), patch(
        "broll_gen.split_screen.asyncio.gather",
        wraps=asyncio.gather,
    ) as mock_gather, patch(
        "broll_gen.split_screen.asyncio.to_thread",
        new_callable=AsyncMock,
    ) as mock_to_thread:
        mock_to_thread.return_value = ffmpeg_ok
        await gen.generate(job, target_duration_s=4.0, output_path=output_path)

    # (a) gather was called exactly once with two awaitables
    assert mock_gather.call_count == 1
    gather_args = mock_gather.call_args.args
    assert len(gather_args) == 2, (
        f"asyncio.gather must be called with both sub-generator coroutines; "
        f"got {len(gather_args)} args"
    )

    # (b) both sub-generators were awaited
    assert left_gen.generate.await_count == 1
    assert right_gen.generate.await_count == 1

    # (c) concurrency evidence: the other side entered before the first
    # finished. With single-threaded asyncio.gather + ``await asyncio.sleep(0)``,
    # entry order is [left_enter, right_enter, *, *] — never
    # [left_enter, left_exit, right_enter, right_exit] (which would be serial).
    assert call_order.index("right_enter") < call_order.index("left_exit"), (
        f"sub-generators did not run concurrently: {call_order!r}"
    )
