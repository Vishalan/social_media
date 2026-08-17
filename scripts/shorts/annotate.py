"""Annotated and magnified views of a real page.

Two techniques taken from the reference shorts (see
docs/reference/2026-08-17-competitor-frame-analysis.md):

``box``    The real page with ONE phrase outlined and everything else dimmed.
           The reference does this with a *New England Journal of Medicine*
           page: body text greyed back, `97.5%` boxed. It turns a wall of text
           into a single readable claim, and it works because the proof is a
           primary source rather than a summary of one.

``macro``  An extreme push into one element — a button, a badge, a price — that
           starts wide enough to give context and lands tight enough to read.
           The reference pushes onto a single "Learn from demonstration" button.
           The asset is a static screenshot; the scale change is the motion.

Both need to locate a phrase in a rendered page, which means asking the browser
where the text is rather than guessing. Chrome is driven through the DevTools
protocol via Playwright, which can return an element's bounding box directly.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

Mode = Literal["box", "macro"]


class AnnotateError(RuntimeError):
    """Raised when the phrase cannot be located or the clip cannot be built."""


_JS_MARK = """
(args) => {
  const [phrase, colour] = args;
  const needle = phrase.trim().toLowerCase();
  if (!needle) return false;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const raw = node.nodeValue || '';
    const idx = raw.toLowerCase().indexOf(needle);
    if (idx < 0) continue;
    if (!node.parentElement) continue;
    const style = getComputedStyle(node.parentElement);
    if (style.display === 'none' || style.visibility === 'hidden') continue;
    const range = document.createRange();
    range.setStart(node, idx);
    range.setEnd(node, idx + needle.length);
    const mark = document.createElement('span');
    mark.setAttribute('data-hl', '1');
    // A flat, unmistakable fill: the finder locates this exact colour in the
    // rendered PNG, so it must not be blended, gradiented or anti-aliased away.
    mark.style.cssText = 'background:' + colour + ' !important;'
      + 'color:#000 !important;opacity:1 !important;'
      + 'padding:2px 4px;border-radius:3px;';
    try { range.surroundContents(mark); } catch (e) { return false; }
    mark.scrollIntoView({block: 'center'});
    return true;
  }
  return false;
}
"""

# A colour no page will contain by accident, used only as a locator.
_PROBE_RGB = (255, 0, 255)
_PROBE_CSS = "rgb(255,0,255)"


def _capture_marked(url: str, phrase: str, png_out: str, *,
                    width: int = 1280, dim_others: bool = False,
                    timeout_ms: int = 45000) -> None:
    """Inject a highlight around ``phrase``, then screenshot the page.

    Why the highlight goes into the DOM rather than being drawn afterwards from
    coordinates: two attempts at the coordinate route put the box on empty
    space. getBoundingClientRect and a full_page screenshot do not share a
    coordinate space reliably — the capture resizes the viewport and a
    responsive page reflows underneath the measurement. Marking the DOM and then
    locating the mark IN THE IMAGE cannot disagree with itself.
    """
    script = f'''
import sys
from playwright.sync_api import sync_playwright

url, phrase, out, width, dim, colour = sys.argv[1:7]
width = int(width); dim = dim == "1"
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
    pg = b.new_page(viewport={{"width": width, "height": 1400}},
                    device_scale_factor=2)
    # "networkidle" never fires on a news site — ads and analytics keep the
    # network busy, so goto times out on a page that rendered in two seconds.
    pg.goto(url, wait_until="domcontentloaded", timeout={timeout_ms})
    pg.wait_for_timeout(2500)
    pg.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    pg.wait_for_timeout(1200)
    pg.evaluate("() => window.scrollTo(0, 0)")
    pg.wait_for_timeout(600)
    if dim:
        # Dim by COLOUR, not opacity. Opacity is inherited multiplicatively and
        # creates a stacking context, so a highlight inside a 0.30-opacity
        # ancestor renders at 0.30 no matter what it declares for itself — the
        # injected mark became invisible and the locator could not find it.
        # Fading text colour leaves the mark's own background untouched.
        pg.add_style_tag(content=(
            "body *:not([data-hl]):not(:has([data-hl])) {{"
            "  color: rgba(140,140,150,0.42) !important;"
            "  border-color: rgba(140,140,150,0.2) !important; }}"
            "img, svg, video {{ filter: grayscale(1) opacity(0.35); }}"))
    ok = pg.evaluate({_JS_MARK!r}, [phrase, colour])
    if not ok:
        print("NOTFOUND"); b.close(); sys.exit(3)
    pg.wait_for_timeout(400)
    pg.screenshot(path=out, full_page=True)
    b.close()
print("OK")
'''
    r = subprocess.run(
        ["python3", "-c", script, url, phrase, png_out, str(width),
         "1" if dim_others else "0", _PROBE_CSS],
        capture_output=True, text=True, timeout=timeout_ms / 1000 + 90)
    if "NOTFOUND" in (r.stdout or ""):
        raise AnnotateError(f"phrase {phrase[:50]!r} not present on {url}")
    if r.returncode != 0 or not os.path.exists(png_out):
        raise AnnotateError(f"page capture failed: {r.stderr[-300:]}")


def _find_probe(png: str) -> dict:
    """Locate the injected highlight in the rendered image."""
    from PIL import Image
    import numpy as np

    a = np.asarray(Image.open(png).convert("RGB")).astype(np.int16)
    target = np.array(_PROBE_RGB, dtype=np.int16)
    hit = (np.abs(a - target).sum(axis=2) < 60)
    ys, xs = np.nonzero(hit)
    if len(xs) < 20:
        raise AnnotateError("highlight injected but not visible in the capture")
    return {"x": float(xs.min()), "y": float(ys.min()),
            "w": float(xs.max() - xs.min()), "h": float(ys.max() - ys.min())}


def _legible_accent(palette: Optional[list[str]]) -> str:
    """A highlight colour that reads as a highlight, not a redaction.

    This took palette[2] unconditionally. A palette's leading entries are the
    source's background and body colours — for the X story palette[2] was
    #0D1117, so the "highlight" painted a near-black bar over the phrase and the
    frame looked like a redacted document rather than an emphasised claim.

    Mid-luminance colours only, and never one so dark or so pale that black text
    on it disappears. Same reasoning as the thumbnail accent.
    """
    for c in reversed(palette or []):
        if not (isinstance(c, str) and c.startswith("#") and len(c) == 7):
            continue
        try:
            r, g, b = (int(c[k:k + 2], 16) for k in (1, 3, 5))
        except ValueError:
            continue
        if 70 < (r * 0.299 + g * 0.587 + b * 0.114) < 210:
            return c
    return "#FFD43B"          # amber: reads as a marker pen on any page


def _recolour(png: str, out_png: str, accent: str) -> str:
    """Repaint the locator colour as the story's accent."""
    from PIL import Image
    import numpy as np

    a = np.asarray(Image.open(png).convert("RGB")).copy()
    tgt = np.array(_PROBE_RGB, dtype=np.int16)
    mask = (np.abs(a.astype(np.int16) - tgt).sum(axis=2) < 60)
    h = accent.lstrip("#")
    a[mask] = [int(h[k:k + 2], 16) for k in (0, 2, 4)]
    Image.fromarray(a).save(out_png)
    return out_png


def build_annotated_clip(*, url: str, out_path: str, phrase: str, label: str,
                         mode: Mode, duration_s: float, width: int, height: int,
                         fps: int, work_dir: str,
                         palette: Optional[list[str]] = None) -> str:
    """Build a boxed or magnified clip centred on ``phrase``."""
    if not phrase.strip():
        raise AnnotateError(f"{mode} needs a phrase to locate")

    Path(work_dir).mkdir(parents=True, exist_ok=True)
    tag = abs(hash(phrase + mode)) % 10**8
    raw = os.path.join(work_dir, f"mark_{tag}.png")
    _capture_marked(url, phrase, raw, dim_others=(mode == "box"))
    box = _find_probe(raw)

    accent = _legible_accent(palette)
    png = _recolour(raw, os.path.join(work_dir, f"hl_{tag}.png"), accent)

    src_w, src_h = _probe(png)
    cx, cy = box["x"] + box["w"] / 2, box["y"] + box["h"] / 2
    frames = max(2, int(duration_s * fps))

    # How much context to keep around the highlight.
    #
    # Derived from READABILITY rather than a fixed multiple of the phrase. The
    # old rule took 1.35x the phrase width capped at 1500px, which on a real
    # headline — 'shadowbanned', 575x85 in a 2560px capture — produced a 776px
    # window and sliced the surrounding words mid-letter at both edges. The
    # frame showed "rces its ranking / etting users see if", which reads as a
    # broken render, and it defeats the point of the type: the claim is only
    # evidence if you can read the sentence it sits in.
    #
    # The phrase's own height is a good proxy for the type size around it. Keep
    # as much width as possible while the text still lands at MIN_TEXT_PX in the
    # panel: big heading type therefore gets the full page width and stays
    # whole, while body text still crops in far enough to be legible.
    MIN_TEXT_PX = 30.0
    line_h = max(box["h"], 8.0)
    readable_w = line_h * width / MIN_TEXT_PX
    if mode == "box":
        crop_w = int(min(src_w, max(readable_w, box["w"] * 1.35, 700)))
    else:
        # macro deliberately pushes in tighter than readability alone requires —
        # the point of that type is magnification.
        crop_w = int(min(src_w, max(box["w"] * 1.9, 700), readable_w * 0.75))
    crop_h = min(src_h, max(int(crop_w * height / width), 240))
    x0 = int(max(0, min(cx - crop_w / 2, src_w - crop_w)))
    y0 = int(max(0, min(cy - crop_h / 2, src_h - crop_h)))

    if mode == "box":
        vf = (f"crop={crop_w}:{crop_h}:{x0}:{y0},"
              f"scale={width}:-2:flags=lanczos,crop={width}:{height},"
              # A slow drift keeps a static page from feeling frozen.
              f"zoompan=z='1+0.05*on/{frames}':x='iw/2-(iw/zoom/2)':"
              f"y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps={fps},"
              f"format=yuv420p")
    else:
        wide_w = min(src_w, int(crop_w * 2.6))
        wide_h = min(src_h, max(int(wide_w * height / width), 240))
        wx = int(max(0, min(cx - wide_w / 2, src_w - wide_w)))
        wy = int(max(0, min(cy - wide_h / 2, src_h - wide_h)))
        zoom_to = max(1.15, wide_w / crop_w)
        vf = (f"crop={wide_w}:{wide_h}:{wx}:{wy},"
              f"scale={width}:-2:flags=lanczos,crop={width}:{height},"
              f"zoompan=z='1+({zoom_to - 1:.3f})*on/{frames}':"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
              f"d=1:s={width}x{height}:fps={fps},format=yuv420p")

    cmd = ["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", str(fps),
           "-t", f"{duration_s:.3f}", "-i", png, "-vf", vf, "-r", str(fps),
           "-frames:v", str(frames), "-c:v", "libx264", "-crf", "18",
           "-pix_fmt", "yuv420p", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise AnnotateError(f"{mode} render failed: {r.stderr[-400:]}")
    logger.info("%s: %r found at (%.0f,%.0f) %.0fx%.0f in a %dx%d capture",
                mode, phrase[:40], box["x"], box["y"], box["w"], box["h"],
                src_w, src_h)
    return out_path


def _probe(png: str) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", png],
        capture_output=True, text=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)
