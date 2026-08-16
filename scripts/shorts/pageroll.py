"""Page-roll b-roll: footage made from the source itself.

Generic stock footage actively hurts a story. A clip of two strangers in a
coworking space, dropped into a piece about a GitHub repository, tells the
viewer nothing and signals that the video is assembled rather than made. The
source page — the actual README, the actual article, the actual product UI —
is both more relevant and more interesting to look at.

This module captures the source URL in headless Chrome at device-pixel-ratio 2
and produces vertical clips from it:

``scroll``   slow vertical travel down the page, the way a reader scans it
``pan``      a held region drifting slowly (Ken Burns without the zoom cliche)
``zoom``     a slow push into a specific region — used for a named artifact

Requires Chrome on the rendering host. Falls back cleanly: if capture fails the
caller gets an empty list and the pipeline proceeds without page-roll rather
than dying.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

RollKind = Literal["scroll", "pan", "zoom"]


class PageRollError(RuntimeError):
    """Raised when a page cannot be captured."""


@dataclass
class RollClip:
    path: str
    kind: RollKind
    duration: float
    source_url: str
    region: str = ""


def _chrome_binary() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    raise PageRollError(
        "no Chrome/Chromium on PATH — page-roll needs a headless browser")


def capture_page(url: str, out_png: str, *, width: int = 1280,
                 max_height: int = 12000, timeout_s: int = 90,
                 dark: bool = True) -> str:
    """Full-page screenshot at DPR 2.

    Dark mode by default: a full-white page against a vertical video is a
    brightness slam, and most source sites (GitHub, docs, product pages) offer
    a dark theme that sits far better next to a talking head.
    """
    chrome = _chrome_binary()
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    # --user-data-dir and --disable-dev-shm-usage are not optional on a headless
    # server: without a writable profile dir Chrome hangs indefinitely rather
    # than erroring, and the default /dev/shm is too small for real pages.
    profile = Path(out_png).parent / "_chrome_profile"
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
        "--disable-dev-shm-usage", "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={profile}",
        "--hide-scrollbars", "--force-device-scale-factor=2",
        f"--window-size={width},{min(max_height, 3000)}",
        "--screenshot=" + out_png,
        "--virtual-time-budget=8000",   # let webfonts and lazy images settle
    ]
    if dark:
        cmd.append("--force-dark-mode")
        cmd.append("--enable-features=WebContentsForceDark")
    cmd.append(url)

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    if not os.path.exists(out_png) or os.path.getsize(out_png) == 0:
        raise PageRollError(
            f"chrome produced no screenshot for {url}: {r.stderr[-400:]}")
    logger.info("Captured %s (%d KB)", url, os.path.getsize(out_png) // 1024)
    return out_png


def _probe_png(path: str) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def make_scroll(png: str, out_mp4: str, *, duration: float = 3.0,
                width: int = 1080, height: int = 1920, fps: int = 25,
                start_frac: float = 0.0, end_frac: float = 0.6,
                content_zoom: float = 1.0) -> str:
    """Slow vertical travel over the captured page.

    ``content_zoom`` magnifies before cropping. Fitting the full 1280px page
    width into a 1080px panel renders body text at roughly 8px — legible on a
    desktop monitor, unreadable on a phone, which made the page-roll look like
    generic texture rather than a specific page. Zooming in trades width the
    viewer cannot read for text they can.

    Travel is linear and slow: eased or fast scrolling reads as a transition
    effect rather than as reading.
    """
    src_w, src_h = _probe_png(png)
    eff_w = int(width * content_zoom)
    scaled_h = int(src_h * (eff_w / src_w))
    frames = max(2, int(duration * fps))

    travel = max(0, scaled_h - height)
    y0 = int(travel * max(0.0, min(1.0, start_frac)))
    y1 = int(travel * max(0.0, min(1.0, end_frac)))
    if y1 == y0:
        y1 = min(travel, y0 + height // 2)

    # crop y is expressed per-frame via `n`; linear interpolation between y0/y1.
    expr = f"{y0}+({y1}-{y0})*n/{frames - 1}"
    # Crop x is centred on the content column, not on the page: sites lay out a
    # centred body with wide empty gutters, and cropping from x=0 would show
    # mostly margin.
    x = max(0, (eff_w - width) // 2)
    vf = (f"scale={eff_w}:-2:flags=lanczos,"
          f"crop={width}:{height}:{x}:'{expr}',"
          f"format=yuv420p")
    cmd = ["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", str(fps),
           "-t", f"{duration:.3f}", "-i", png, "-vf", vf, "-r", str(fps),
           "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out_mp4]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise PageRollError(f"scroll render failed: {r.stderr[-500:]}")
    return out_mp4


def make_zoom(png: str, out_mp4: str, *, duration: float = 3.0,
              width: int = 1080, height: int = 1920, fps: int = 25,
              focus_frac: float = 0.15, zoom_from: float = 1.0,
              zoom_to: float = 1.18, content_zoom: float = 1.0) -> str:
    """Slow push into a region of the page.

    zoompan is applied to an already-scaled still, so the motion is smooth
    rather than stepping between integer crop positions.
    """
    src_w, src_h = _probe_png(png)
    eff_w = int(width * content_zoom)
    scaled_h = int(src_h * (eff_w / src_w))
    frames = max(2, int(duration * fps))
    y = int(max(0, min(scaled_h - height, scaled_h * focus_frac)))
    x = max(0, (eff_w - width) // 2)

    # d=1, NOT d=frames. `d` is output frames PER INPUT FRAME, and the input is
    # a still looped at `fps`, so d=frames produced frames^2 (5625 for a 3s
    # clip) and a video 75x too long. With d=1 the `on` counter still ramps
    # across the whole clip, so the zoom is unchanged.
    vf = (f"scale={eff_w}:-2:flags=lanczos,"
          f"crop={width}:{height}:{x}:{y},"
          f"zoompan=z='{zoom_from}+({zoom_to}-{zoom_from})*on/{frames}':"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
          f"d=1:s={width}x{height}:fps={fps},format=yuv420p")
    cmd = ["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", str(fps),
           "-t", f"{duration:.3f}", "-i", png, "-vf", vf, "-r", str(fps),
           "-frames:v", str(frames),
           "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out_mp4]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise PageRollError(f"zoom render failed: {r.stderr[-500:]}")
    return out_mp4


def build_rolls(url: str, out_dir: str, *, count: int = 4,
                duration: float = 3.0, width: int = 1080, height: int = 1920,
                fps: int = 25, half_height: Optional[int] = None,
                content_zoom: float = 1.9) -> list[RollClip]:
    """Capture the page once and cut several distinct clips from it.

    Each clip covers a different band of the page, so four cut-ins are four
    different parts of the source rather than the same header four times.

    half_height: when the avatar occupies the lower half of frame, render at
    that height instead — the clip only ever occupies the top panel, and
    rendering it full-height then cropping would throw away resolution.
    """
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    png = os.path.join(out_dir, "page.png")
    try:
        capture_page(url, png)
    except (PageRollError, subprocess.TimeoutExpired) as exc:
        logger.warning("page-roll capture failed for %s: %s", url, exc)
        return []

    h = half_height or height
    clips: list[RollClip] = []
    # Walk successive bands. The first is the top of the page (the part a
    # reader actually lands on); later ones move down through the body.
    bands = [(0.00, 0.18), (0.16, 0.38), (0.36, 0.60), (0.55, 0.85),
             (0.80, 1.00)][:count]
    for i, (a, b) in enumerate(bands):
        out = os.path.join(out_dir, f"roll_{i}.mp4")
        try:
            if i % 3 == 2:
                make_zoom(png, out, duration=duration, width=width, height=h,
                          fps=fps, focus_frac=a, content_zoom=content_zoom)
                kind: RollKind = "zoom"
            else:
                make_scroll(png, out, duration=duration, width=width, height=h,
                            fps=fps, start_frac=a, end_frac=b,
                            content_zoom=content_zoom)
                kind = "scroll"
        except PageRollError as exc:
            logger.warning("roll %d failed: %s", i, exc)
            continue
        clips.append(RollClip(path=out, kind=kind, duration=duration,
                              source_url=url, region=f"{a:.0%}-{b:.0%}"))
        logger.info("page-roll %d: %s over %s of the page", i, kind,
                    clips[-1].region)
    return clips
