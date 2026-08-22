"""Stock footage as a b-roll kind.

Separated from `stages._fetch_stock`, which exists for a different job: that
one is a whole-slate FALLBACK provider used when the director cannot run at
all. This module serves a single planned slot, so the two differ in what they
take (one query vs a list), what they return (one conformed clip vs a slate)
and when they run. Merging them would mean one function with a mode flag.

Why this matters at all: real footage is the cheapest non-typographic b-roll
available. Generated video costs ~10 minutes of GPU per clip, and every
designed composition is ultimately a rectangle with text in it — this is the
only source of actual moving imagery that returns in seconds and costs nothing.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from .net import BROWSER_UA as _UA

logger = logging.getLogger(__name__)

# Cloudflare answers default library agents with 403 "error code: 1010", so the
# request has to look like a browser. This is not optional and not cosmetic.

_API = "https://api.pexels.com/videos/search"


class StockError(RuntimeError):
    """Raised when no usable clip can be obtained."""


def available() -> bool:
    return bool(os.environ.get("PEXELS_API_KEY", "").strip())


def search(query: str, *, limit: int = 8) -> list[dict]:
    """Portrait video candidates for a query, best first."""
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        raise StockError("PEXELS_API_KEY is not set")
    url = f"{_API}?" + urllib.parse.urlencode(
        {"query": query, "per_page": limit, "orientation": "portrait",
         "size": "medium"})
    req = urllib.request.Request(url, headers={
        "Authorization": key, "User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("videos", []) or []


def _best_file(video: dict, want_h: int) -> Optional[dict]:
    """The rendition closest to the panel without being smaller than it.

    Upscaling stock footage is visible immediately — it is real imagery beside
    crisp vector type, so any softness reads as a mistake rather than a style.
    Prefer the smallest file that still meets the height, and only fall back to
    a smaller one when nothing else exists.
    """
    files = [f for f in (video.get("video_files") or [])
             if (f.get("height") or 0) > 0 and f.get("link")]
    if not files:
        return None
    big = [f for f in files if f["height"] >= want_h]
    if big:
        return min(big, key=lambda f: f["height"])
    return max(files, key=lambda f: f["height"])


def fetch(query: str, out_path: str, *, duration_s: float,
          width: int, height: int, fps: int = 25,
          min_source_s: float = 3.0) -> str:
    """Download one clip for `query` and conform it to the panel.

    Conforming rather than trusting: stock is 4K, 30fps and any aspect ratio,
    while the panel is a fixed size the assembler concatenates without
    re-encoding. A clip that arrives at the wrong geometry does not fail — it
    silently changes the video's dimensions partway through.
    """
    vids = [v for v in search(query)
            if (v.get("duration") or 0) >= min_source_s]
    if not vids:
        raise StockError(f"no usable stock footage for {query!r}")

    last: Optional[Exception] = None
    for v in vids[:3]:
        f = _best_file(v, height)
        if not f:
            continue
        raw = str(Path(out_path).with_suffix(".src.mp4"))
        try:
            req = urllib.request.Request(f["link"], headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=120) as r, open(raw, "wb") as fh:
                fh.write(r.read())
        except Exception as exc:                   # noqa: BLE001 — try the next
            last = exc
            continue

        # Start a little way in: stock clips often open on a static frame
        # before the motion begins, and a b-roll cut that starts on a freeze
        # reads as a still image.
        src_len = float(v.get("duration") or 0)
        start = min(0.8, max(0.0, (src_len - duration_s) / 2))
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.2f}", "-i", raw,
             "-t", f"{duration_s:.3f}",
             "-vf", (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                     f"crop={width}:{height},fps={fps}"),
             "-an", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
             out_path],
            capture_output=True, text=True)
        Path(raw).unlink(missing_ok=True)
        if r.returncode == 0 and Path(out_path).exists():
            logger.info("Stock %r -> %s (%.1fs, from %dx%d)", query,
                        Path(out_path).name, duration_s,
                        f.get("width", 0), f.get("height", 0))
            return out_path
        last = RuntimeError(r.stderr[-200:])

    raise StockError(f"could not conform any clip for {query!r}: {last}")
