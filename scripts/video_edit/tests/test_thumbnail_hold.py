"""Regression + behavior tests for the prepended thumbnail hold frame.

The CRITICAL invariant: `_compute_avatar_windows()` must NOT know about
the thumbnail hold. Avatar lip-sync windows are computed against the
speech-only timeline; the hold offset is applied only when constructing
the FINAL make_frame and audio. See:
docs/solutions/integration-issues/avatar-lip-sync-desync-across-segments-2026-04-05.md
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

# Make `scripts/` importable as a package root
_SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


def test_compute_avatar_windows_signature_stable():
    """The function MUST NOT take a thumbnail parameter — the speech
    timeline is sacred and the function shouldn't even know about the hold.
    """
    from smoke_e2e import _compute_avatar_windows

    sig = inspect.signature(_compute_avatar_windows)
    params = list(sig.parameters.keys())
    assert params == ["audio_duration"], (
        f"_compute_avatar_windows signature changed to {params}; "
        "it MUST only take audio_duration. Adding a thumbnail parameter "
        "would couple the speech timeline to the hold and risk breaking "
        "frame-accurate avatar lip-sync."
    )
    for name in params:
        assert "thumb" not in name.lower()


@pytest.mark.parametrize("duration", [45.0, 55.0, 64.37, 72.75, 90.0])
def test_compute_avatar_windows_deterministic(duration):
    """Calling the function twice for the same duration must yield identical
    windows. (Idempotency stand-in for "regardless of thumbnail downstream".)
    """
    from smoke_e2e import _compute_avatar_windows

    a = _compute_avatar_windows(duration)
    b = _compute_avatar_windows(duration)
    assert a == b
    # Sanity: hook always starts at 0.0 (NOT shifted by hold)
    assert a[0][0] == 0.0


def test_thumbnail_hold_constant_exists_and_is_half_second():
    from video_edit import video_editor

    assert hasattr(video_editor, "_THUMBNAIL_HOLD_S"), (
        "_THUMBNAIL_HOLD_S module constant missing from video_editor.py"
    )
    assert video_editor._THUMBNAIL_HOLD_S == 0.5


def test_wrap_with_thumbnail_hold_helper_exists():
    from video_edit import video_editor

    assert hasattr(video_editor, "_wrap_with_thumbnail_hold")
    sig = inspect.signature(video_editor._wrap_with_thumbnail_hold)
    params = list(sig.parameters.keys())
    # (make_frame_fn, thumbnail_array, hold_s)
    assert len(params) == 3


def test_wrap_with_thumbnail_hold_returns_thumbnail_then_delegates():
    """At t=0 we get the thumbnail; at t>=hold we get the underlying frame
    with t shifted back by hold_s."""
    import numpy as np

    from video_edit.video_editor import _THUMBNAIL_HOLD_S, _wrap_with_thumbnail_hold

    H, W = 8, 6
    thumb = np.full((H, W, 3), 200, dtype=np.uint8)

    captured = {}

    def inner(t):
        captured["last_t"] = t
        return np.full((H, W, 3), 50, dtype=np.uint8)

    wrapped = _wrap_with_thumbnail_hold(inner, thumb, _THUMBNAIL_HOLD_S)

    # During hold: thumbnail pixels, inner NOT called
    captured.clear()
    f0 = wrapped(0.0)
    assert (f0 == 200).all()
    assert "last_t" not in captured

    f_mid = wrapped(_THUMBNAIL_HOLD_S - 0.01)
    assert (f_mid == 200).all()

    # After hold: inner is called with t shifted back
    f_after = wrapped(_THUMBNAIL_HOLD_S + 0.1)
    assert (f_after == 50).all()
    assert captured["last_t"] == pytest.approx(0.1, abs=1e-9)

    # Exactly at hold boundary -> inner with t=0
    captured.clear()
    f_at = wrapped(_THUMBNAIL_HOLD_S)
    assert (f_at == 50).all()
    assert captured["last_t"] == pytest.approx(0.0, abs=1e-9)


def test_assemble_broll_body_accepts_thumbnail_path_kwarg():
    """Backwards-compatible signature: thumbnail_path defaults to None."""
    from video_edit.video_editor import VideoEditor

    sig = inspect.signature(VideoEditor._assemble_broll_body)
    assert "thumbnail_path" in sig.parameters
    assert sig.parameters["thumbnail_path"].default is None
