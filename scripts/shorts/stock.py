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
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from .net import BROWSER_UA

logger = logging.getLogger(__name__)

# Cloudflare answers default library agents with 403 "error code: 1010", so the
# request has to look like a browser. This is not optional and not cosmetic.

_API = "https://api.pexels.com/videos/search"

# Subjects that are always wrong for this channel, checked against the
# library's own description of each result.
#
# The brief asks for business and news imagery; stock libraries answer literal
# keywords out of a lifestyle catalogue regardless. "private rocket ride"
# returned a child playing with a toy rocket for a story about a space
# company's share sale — perfectly matching the words and completely wrong.
# A prompt cannot enforce this on a third party's ranking, so the results are
# filtered on the way back.
_BANNED = (
    "child", "children", "kid", "kids", "baby", "toddler", "family",
    "toy", "playing", "playground", "birthday", "party", "celebration",
    "wedding", "bride", "kitchen", "cooking", "food", "meal", "restaurant",
    "yoga", "fitness", "gym", "beach", "vacation", "holiday", "pet", "dog",
    "cat", "smiling", "selfie", "couple", "romantic", "shopping", "cosmetic",
)


_BANNED_RE = re.compile(r"\b(" + "|".join(_BANNED) + r")\b", re.I)


def _is_usable(item: dict) -> bool:
    """Reject a result whose own description places it in lifestyle stock.

    Matched on WORD BOUNDARIES. A plain substring test rejected a
    candlestick-chart photograph because "cat" appears inside "indicating" —
    the guard has to be precise or it throws away the business imagery it
    exists to protect.

    Only the alt text is searched. The URL slug carries the photographer's
    name and site furniture, which produced the same class of false match.
    """
    return not _BANNED_RE.search(str(item.get("alt", "")))




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
        "Authorization": key, "User-Agent": BROWSER_UA, "Accept": "application/json"})
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
    raw = search(query)
    vids = [v for v in raw
            if (v.get("duration") or 0) >= min_source_s and _is_usable(v)]
    if raw and not vids:
        logger.info("All %d footage results for %r were rejected as lifestyle "
                    "stock or too short", len(raw), query)
    if not vids:
        raise StockError(f"no usable stock footage for {query!r}")

    last: Optional[Exception] = None
    for v in vids[:3]:
        f = _best_file(v, height)
        if not f:
            continue
        raw = str(Path(out_path).with_suffix(".src.mp4"))
        try:
            req = urllib.request.Request(f["link"], headers={"User-Agent": BROWSER_UA})
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


# ─── photographs ────────────────────────────────────────────────────────────
#
# A still is not b-roll until something moves. Photographs are far more
# plentiful than video for any given subject — a stock video search for a named
# company returns nothing, a photo search returns plenty — so animating a still
# reaches subjects that footage cannot, at the same zero cost.

_PHOTO_API = "https://api.pexels.com/v1/search"


def search_photos(query: str, *, limit: int = 8) -> list[dict]:
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        raise StockError("PEXELS_API_KEY is not set")
    url = f"{_PHOTO_API}?" + urllib.parse.urlencode(
        {"query": query, "per_page": limit, "orientation": "portrait"})
    req = urllib.request.Request(url, headers={
        "Authorization": key, "User-Agent": BROWSER_UA,
        "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("photos", []) or []


def fetch_photo(query: str, out_path: str, *, duration_s: float,
                width: int, height: int, fps: int = 25,
                move: str = "in") -> str:
    """One photograph for `query`, animated into a clip.

    The move is a slow push or pull with a slight drift, done with zoompan.
    Two details make the difference between a camera move and a wobble:

    * The source is upscaled BEFORE zoompan runs. zoompan samples from the
      input at integer pixel positions, so panning a frame at its final size
      makes the image visibly judder — the classic "Ken Burns jitter". Working
      at 3x and scaling down afterwards hides the quantisation.
    * The zoom is driven by `on` (the output frame index) over a fixed total,
      not by wall time, so the move always completes exactly at the cut rather
      than stopping early or being clipped mid-travel.
    """
    raw = search_photos(query)
    photos = [ph for ph in raw if _is_usable(ph)]
    if raw and not photos:
        logger.info("All %d photo results for %r were rejected as lifestyle "
                    "stock", len(raw), query)
    if not photos:
        raise StockError(f"no usable photograph for {query!r}")

    last: Optional[Exception] = None
    for ph in photos[:3]:
        src = (ph.get("src") or {})
        link = src.get("portrait") or src.get("large2x") or src.get("original")
        if not link:
            continue
        raw = str(Path(out_path).with_suffix(".src.jpg"))
        try:
            req = urllib.request.Request(link, headers={"User-Agent": BROWSER_UA})
            with urllib.request.urlopen(req, timeout=90) as r, open(raw, "wb") as fh:
                fh.write(r.read())
        except Exception as exc:                    # noqa: BLE001 — try next
            last = exc
            continue

        frames = max(2, int(round(duration_s * fps)))
        z0, z1 = (1.0, 1.14) if move == "in" else (1.14, 1.0)
        zexpr = f"{z0}+({z1}-{z0})*on/{frames}"
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", raw,
             "-t", f"{duration_s:.3f}",
             "-vf", (
                 f"scale={width*3}:{height*3}:force_original_aspect_ratio=increase,"
                 f"crop={width*3}:{height*3},"
                 f"zoompan=z='{zexpr}':d={frames}:s={width}x{height}:fps={fps}"
                 f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',"
                 f"format=yuv420p"),
             "-frames:v", str(frames),
             "-c:v", "libx264", "-crf", "18", out_path],
            capture_output=True, text=True)
        Path(raw).unlink(missing_ok=True)
        if r.returncode == 0 and Path(out_path).exists():
            logger.info("Photo %r -> %s (%.1fs, push-%s)", query,
                        Path(out_path).name, duration_s, move)
            return out_path
        last = RuntimeError(r.stderr[-200:])

    raise StockError(f"could not animate any photograph for {query!r}: {last}")


def fetch_any(query: str, out_path: str, **kw) -> str:
    """Footage if it exists for this subject, otherwise an animated still.

    Video coverage is thin and uneven — plentiful for generic scenes, absent
    for anything specific — so a video-only search fails exactly on the
    subjects a story is actually about. Falling through to a photograph keeps
    real imagery on screen instead of dropping back to another text card.
    """
    try:
        return fetch(query, out_path, **kw)
    except Exception as exc:                        # noqa: BLE001 — expected
        logger.info("No footage for %r (%s) — animating a photograph instead",
                    query, str(exc)[:80])
        kw.pop("min_source_s", None)
        return fetch_photo(query, out_path, **kw)
