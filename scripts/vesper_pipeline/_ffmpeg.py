"""Shared ffmpeg binary resolver for the Vesper pipeline.

Prefers ``imageio_ffmpeg``'s bundled static binary over the system
``ffmpeg`` on $PATH. This defends against brew/apt dependency drift
(e.g., Homebrew ffmpeg SIGABRT'ing on a stale libvpx) without
requiring the operator to reinstall.

Every Vesper module that shells out to ffmpeg consults :func:`ffmpeg_bin`
instead of hard-coding the string ``"ffmpeg"``.
"""

from __future__ import annotations

import logging
import os
import shutil

logger = logging.getLogger(__name__)

_cached: str | None = None


def ffmpeg_bin() -> str:
    """Return a usable ffmpeg binary path.

    Resolution order:
      1. ``imageio_ffmpeg.get_ffmpeg_exe()`` — bundled static binary.
      2. Whatever ``ffmpeg`` is on $PATH.

    Cached after the first resolve so repeated calls are cheap.
    """
    global _cached
    if _cached is not None:
        return _cached

    try:
        import imageio_ffmpeg  # type: ignore
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            _cached = exe
            return _cached
    except ImportError:
        pass

    sys_ffmpeg = shutil.which("ffmpeg")
    if sys_ffmpeg:
        _cached = sys_ffmpeg
        return _cached

    # Fall back to the literal string so the caller's subprocess call
    # surfaces the familiar "ffmpeg not found" error if nothing is
    # available at all.
    _cached = "ffmpeg"
    return _cached


__all__ = ["ffmpeg_bin"]
