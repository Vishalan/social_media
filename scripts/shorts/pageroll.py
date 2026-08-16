"""Page-roll b-roll: footage made from the source page itself.

Generic stock footage hurts a story — strangers in a coworking space, dropped
into a piece about a repository, tell the viewer nothing. The source page is
both more relevant and more interesting to look at.

Two things make this work rather than merely function:

REGION DETECTION, not blind cropping. A first version scaled the page to panel
width and cropped the centre. Measured against a real GitHub capture, that
discarded 606px of content from the left, because the page is laid out edge to
edge rather than as a centred column. This version finds actual content blocks
— contiguous bands of non-background pixels — and fits each one to the panel,
so a region is shown whole instead of sliced.

SCRIPT ALIGNMENT, not arbitrary order. Regions are returned with their bounds
so a caller can match them to the narration beat they illustrate. Showing the
commit list while the narration explains the file format is as disconnected as
stock footage.

Requires Chrome on the rendering host. Falls back cleanly: on failure the
caller gets an empty list and the pipeline proceeds without page-roll.
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

RollKind = Literal["scroll", "hold"]


class PageRollError(RuntimeError):
    """Raised when a page cannot be captured or rendered."""


@dataclass
class Region:
    """A coherent block of page content."""
    top: int
    bottom: int
    left: int
    right: int
    density: float          # fraction of pixels differing from background
    index: int = 0

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def width(self) -> int:
        return self.right - self.left


@dataclass
class RollClip:
    path: str
    kind: RollKind
    duration: float
    source_url: str
    region: str = ""
    region_index: int = 0


def _chrome_binary() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    raise PageRollError("no Chrome/Chromium on PATH")


def capture_page(url: str, out_png: str, *, width: int = 1280,
                 max_height: int = 12000, timeout_s: int = 180,
                 dark: bool = True, attempts: int = 2,
                 reuse: bool = True) -> str:
    """Full-page screenshot at DPR 2.

    Retries once: headless Chrome occasionally hangs on a slow third-party
    asset and a second run usually lands. An existing capture is reused rather
    than re-fetched, which also keeps re-runs of later stages cheap.
    """
    if reuse and os.path.exists(out_png) and os.path.getsize(out_png) > 0:
        logger.info("Reusing existing capture %s", out_png)
        return out_png
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _capture_once(url, out_png, width=width,
                                 max_height=max_height, timeout_s=timeout_s,
                                 dark=dark)
        except (PageRollError, subprocess.TimeoutExpired) as exc:
            last = exc
            logger.warning("capture attempt %d/%d failed: %s",
                           attempt, attempts, str(exc)[:160])
    raise PageRollError(f"capture failed after {attempts} attempts: {last}")


def _capture_once(url: str, out_png: str, *, width: int,
                  max_height: int, timeout_s: int, dark: bool) -> str:
    chrome = _chrome_binary()
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    # --user-data-dir and --disable-dev-shm-usage are not optional headless:
    # without them Chrome hangs indefinitely rather than erroring.
    profile = Path(out_png).parent / "_chrome_profile"
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
        "--disable-dev-shm-usage", "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={profile}",
        "--hide-scrollbars", "--force-device-scale-factor=2",
        f"--window-size={width},{min(max_height, 3000)}",
        "--screenshot=" + out_png,
        "--virtual-time-budget=8000",
    ]
    if dark:
        cmd += ["--force-dark-mode", "--enable-features=WebContentsForceDark"]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    if not os.path.exists(out_png) or os.path.getsize(out_png) == 0:
        raise PageRollError(f"no screenshot for {url}: {r.stderr[-300:]}")
    logger.info("Captured %s (%d KB)", url, os.path.getsize(out_png) // 1024)
    return out_png


def detect_regions(png: str, *, panel_aspect: float = 998 / 1080,
                   max_regions: int = 14, overlap: float = 0.5) -> list[Region]:
    """Slice the page into panel-shaped windows and rank them by content.

    A first version looked for whitespace gaps between blocks. That works on
    article pages and fails completely on an application UI: a GitHub file
    listing has no blank rows, so the whole 6000px page came back as one
    region and the clip was a squeezed full-page smear.

    Windows are sized so that scaling the page's full width to the panel width
    fills the panel height exactly — the region is a natural screenful, shown
    at the page's own proportions, with nothing cropped off the sides.
    """
    from PIL import Image
    import numpy as np

    im = Image.open(png).convert("RGB")
    a = np.asarray(im)
    h, w = a.shape[:2]
    bg = np.median(a.reshape(-1, 3), axis=0)
    dev = np.abs(a.astype(np.int16) - bg.astype(np.int16)).sum(axis=2)
    active = dev > 34
    rowact = active.mean(axis=1)

    win = max(200, int(w * panel_aspect))          # page px per screenful
    # A 6000px page holds only ~2.5 screenfuls, so windows overlap heavily —
    # otherwise there are not enough distinct regions to cover a 60s video.
    step = max(1, int(win * (1.0 - overlap)))

    windows: list[Region] = []
    for top in range(0, max(1, h - win), step):
        bottom = min(h, top + win)
        density = float(rowact[top:bottom].mean())
        # Ignore near-empty windows: page footers and long blank tails.
        if density < 0.012:
            continue
        windows.append(Region(top=top, bottom=bottom, left=0, right=w,
                              density=density))

    if not windows:
        windows = [Region(top=0, bottom=min(h, win), left=0, right=w,
                          density=float(rowact[:win].mean()))]

    # Keep the densest, then restore document order so the clips read as a
    # progression down the page rather than a jumble.
    windows.sort(key=lambda r: -r.density)
    windows = windows[:max_regions]
    windows.sort(key=lambda r: r.top)
    for i, r in enumerate(windows):
        r.index = i
    logger.info("Detected %d content windows (%dpx each) in %s",
                len(windows), win, Path(png).name)
    return windows


def render_region(png: str, region: Region, out_mp4: str, *,
                  duration: float, width: int, height: int,
                  fps: int) -> RollKind:
    """Fit one region to the panel and move gently within it.

    The region is scaled so its FULL WIDTH fits the panel — nothing is cropped
    horizontally, which is what previously sliced content off both edges. If
    the scaled region is taller than the panel the crop window travels down it;
    otherwise it is centred, padded, and given a slow push.
    """
    frames = max(2, int(duration * fps))
    scale = width / max(1, region.width)
    scaled_h = int(region.height * scale)

    pre = (f"crop={region.width}:{region.height}:{region.left}:{region.top},"
           f"scale={width}:-2:flags=lanczos")

    if scaled_h > height + 20:
        travel = scaled_h - height
        # At most one panel-height of travel per clip: faster and the eye
        # cannot read anything on the way past.
        y1 = min(travel, height)
        vf = (f"{pre},crop={width}:{height}:0:'0+({y1})*n/{frames - 1}',"
              f"format=yuv420p")
        kind: RollKind = "scroll"
    else:
        pad_y = max(0, (height - scaled_h) // 2)
        vf = (f"{pre},pad={width}:{height}:0:{pad_y}:color=0x0D1117,"
              f"zoompan=z='1.0+0.06*on/{frames}':x='iw/2-(iw/zoom/2)':"
              f"y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps={fps},"
              f"format=yuv420p")
        kind = "hold"

    cmd = ["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", str(fps),
           "-t", f"{duration:.3f}", "-i", png, "-vf", vf, "-r", str(fps),
           "-frames:v", str(frames),
           "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out_mp4]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise PageRollError(f"region render failed: {r.stderr[-500:]}")
    return kind


def build_rolls(url: str, out_dir: str, *, count: int = 4,
                duration: float = 3.0, width: int = 1080, height: int = 1920,
                fps: int = 25, half_height: Optional[int] = None,
                pick: Optional[list[int]] = None) -> list[RollClip]:
    """Capture the page and render one clip per selected content region.

    ``pick`` chooses region indices, letting a caller align regions to script
    beats. Without it, regions are spread evenly down the page.
    """
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    png = os.path.join(out_dir, "page.png")
    try:
        capture_page(url, png)
    except (PageRollError, subprocess.TimeoutExpired) as exc:
        logger.warning("page-roll capture failed for %s: %s", url, exc)
        return []

    try:
        regions = detect_regions(png, panel_aspect=(half_height or height) / width)
    except Exception as exc:                      # noqa: BLE001 — optional stage
        logger.warning("region detection failed: %s", exc)
        return []
    if not regions:
        logger.warning("no content regions found in %s", url)
        return []

    json.dump([{"index": r.index, "top": r.top, "bottom": r.bottom,
                "left": r.left, "right": r.right, "height": r.height,
                "width": r.width, "density": round(r.density, 4)}
               for r in regions],
              open(os.path.join(out_dir, "regions.json"), "w"), indent=2)

    if pick:
        chosen = [regions[i] for i in pick if 0 <= i < len(regions)][:count]
    else:
        step = max(1, len(regions) // max(1, count))
        chosen = regions[::step][:count]

    h = half_height or height
    clips: list[RollClip] = []
    for i, reg in enumerate(chosen):
        out = os.path.join(out_dir, f"roll_{i}.mp4")
        try:
            kind = render_region(png, reg, out, duration=duration, width=width,
                                 height=h, fps=fps)
        except PageRollError as exc:
            logger.warning("region %d failed: %s", reg.index, exc)
            continue
        clips.append(RollClip(path=out, kind=kind, duration=duration,
                              source_url=url, region_index=reg.index,
                              region=f"y{reg.top}-{reg.bottom}"))
        logger.info("page-roll %d: %s region %d (%dx%d at y=%d)",
                    i, kind, reg.index, reg.width, reg.height, reg.top)
    return clips
