"""Vision review: let the model look at what was produced.

Two jobs, both of which need eyes rather than metadata:

``select_regions``   given the page's content windows as thumbnails and the
                     narration, decide which window illustrates which beat —
                     the difference between showing the commit list while the
                     narration explains the file format, and showing the file
                     format.

``review_design``    look at a rendered graphic and say whether it is broken:
                     overlapping text, an element covering another, a caption
                     that contradicts the visual, a label sitting on a glyph.
                     Automated layout checks pass things a person would call
                     obviously wrong.

Both shell out to ``claude -p`` with Read enabled so the model can open the
images. Costs subscription time, not API credit.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


class VisionError(RuntimeError):
    """Raised when a vision pass cannot be completed."""


def _claude(prompt: str, *, cwd: str, model: str = "sonnet",
            timeout_s: int = 420) -> str:
    """Run claude -p with Read/Glob enabled so it can open images."""
    binary = shutil.which("claude")
    if binary is None:
        raise VisionError("claude CLI not on PATH")
    cmd = [binary, "-p", prompt,
           # Read is required — this is the whole point. No Write/Edit/Bash:
           # a review pass has no business changing anything.
           "--allowedTools", "Read,Glob",
           "--model", model, "--output-format", "json"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd,
                       timeout=timeout_s)
    if r.returncode != 0:
        err = (r.stderr or "").strip()
        out = (r.stdout or "").strip()
        raise VisionError(f"claude -p exited {r.returncode}: "
                          f"{' | '.join(x for x in (err[-400:], out[-400:]) if x)}")
    try:
        env = json.loads(r.stdout)
        text = env.get("result", "") if isinstance(env, dict) else r.stdout
    except json.JSONDecodeError:
        text = r.stdout
    m = _FENCE.match(text.strip())
    return (m.group(1) if m else text).strip()


def make_region_thumbs(png: str, regions: list, out_dir: str, *,
                       width: int = 640) -> list[str]:
    """Write one thumbnail per detected page window, for the model to look at."""
    from PIL import Image

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    im = Image.open(png).convert("RGB")
    paths = []
    for r in regions:
        crop = im.crop((r.left, r.top, r.right, r.bottom))
        h = int(crop.height * (width / max(1, crop.width)))
        crop = crop.resize((width, max(1, h)), Image.LANCZOS)
        p = os.path.join(out_dir, f"region_{r.index:02d}.png")
        crop.save(p, quality=88)
        paths.append(p)
    return paths


def select_regions(*, thumbs: list[str], script: str, beats: list[dict],
                   work_dir: str, model: str = "sonnet") -> list[dict]:
    """Match page windows to narration beats.

    Args:
        thumbs: region thumbnail paths, index-aligned to detected regions.
        script: the full narration.
        beats: [{"start": float, "end": float, "text": str}] — the gaps to fill.

    Returns:
        [{"beat": i, "region": j, "why": str}] — one per beat it could match.
        A beat with no good match is simply absent rather than force-fitted.
    """
    if not thumbs or not beats:
        return []

    listing = "\n".join(f"  region {i}: {os.path.basename(p)}"
                        for i, p in enumerate(thumbs))
    beat_lines = "\n".join(
        f"  beat {i} ({b['start']:.1f}-{b['end']:.1f}s): \"{b['text']}\""
        for i, b in enumerate(beats))

    prompt = f"""Look at the page screenshots in ./regions/ and match them to
narration beats.

REGIONS (open each with Read):
{listing}

NARRATION BEATS to illustrate:
{beat_lines}

FULL NARRATION for context:
{script}

For each beat, pick the region that ACTUALLY shows what the narration is
talking about at that moment. A commit list under narration about file format
is a mismatch; the file tree or a code block is a match.

Rules:
- Do not reuse a region for more than one beat unless nothing else fits.
- If no region genuinely illustrates a beat, omit that beat. A missing match
  is better than a misleading one.
- "why" must name what is visible in the region, not restate the narration.

Reply with ONLY a JSON array:
[{{"beat": 0, "region": 3, "why": "shows the SKILL.md file tree"}}]"""

    try:
        raw = _claude(prompt, cwd=work_dir, model=model)
        data = json.loads(raw)
    except (VisionError, json.JSONDecodeError) as exc:
        logger.warning("region selection failed (%s) — falling back to "
                       "even spread down the page", str(exc)[:200])
        return []

    out = []
    used = set()
    for item in data if isinstance(data, list) else []:
        try:
            b, r = int(item["beat"]), int(item["region"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= b < len(beats) and 0 <= r < len(thumbs)):
            continue
        if r in used:
            continue
        used.add(r)
        out.append({"beat": b, "region": r, "why": str(item.get("why", ""))[:200]})
    for m in out:
        logger.info("beat %d -> region %d (%s)", m["beat"], m["region"], m["why"])
    return out


def review_design(*, video: str, brief: dict, work_dir: str,
                  model: str = "sonnet") -> dict:
    """Look at a rendered graphic and judge whether it is usable.

    Extracts frames and asks for a verdict. This exists because automated
    layout checks pass things a person calls obviously broken: a supporting
    label rendered on top of the hero numeral, a terminal block cursor sitting
    over the first letter of the word it precedes, a card whose content has
    nothing to do with the beat it plays under.
    """
    frames_dir = os.path.join(work_dir, "review_frames")
    Path(frames_dir).mkdir(parents=True, exist_ok=True)
    base = Path(video).stem
    shots = []
    for i, frac in enumerate((0.45, 0.7, 0.95)):
        out = os.path.join(frames_dir, f"{base}_{i}.png")
        dur = _duration(video)
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{dur * frac:.2f}",
             "-i", video, "-vframes", "1", out],
            capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(out):
            shots.append(os.path.relpath(out, work_dir))
    if not shots:
        return {"ok": True, "note": "no frames extracted; not reviewed"}

    prompt = f"""Review this motion graphic. Open these frames with Read:
{chr(10).join('  ' + s for s in shots)}

It is meant to show:
  headline: "{brief.get('headline', '')}"
  support:  "{brief.get('support', '')}"
  context:  "{brief.get('context', '')}"
  purpose:  {brief.get('rationale', '')}

Judge it as a viewer sees it on a phone. Fail it for any of:
- text overlapping other text or an element covering another
- the hero being hard to read at a glance
- a label or cursor sitting on top of a glyph it should sit beside
- content that does not match the stated purpose
- anything cut off by the frame edge
- TYPE TOO SMALL to read comfortably at about 6cm tall — body labels, diagram
  step captions, code lines and chart ticks included. This panel is half a phone
  screen, not a slide.
- THE FRAME MOSTLY EMPTY: content floating in a large field of background
  instead of filling the canvas. Shipped clips had content spanning only about a
  quarter of the panel height, which is the main reason they held no attention.
- THE LAST FRAME LOOKING IDENTICAL to the middle one. The three frames given to
  you are from 45%, 70% and 95% of the clip; if the final two are the same
  picture, the graphic froze and the rest of its screen time is a still image.

Do NOT fail it for taste — only for defects a viewer would notice as wrong.

Reply with ONLY JSON:
{{"ok": true/false, "problems": ["..."], "worst": "one line"}}"""

    try:
        raw = _claude(prompt, cwd=work_dir, model=model, timeout_s=300)
        verdict = json.loads(raw)
    except (VisionError, json.JSONDecodeError) as exc:
        logger.warning("design review failed for %s: %s", base, str(exc)[:160])
        return {"ok": True, "note": f"review unavailable: {str(exc)[:120]}"}

    if not verdict.get("ok"):
        logger.warning("design %s REJECTED: %s", base, verdict.get("worst", ""))
        for p in verdict.get("problems", [])[:4]:
            logger.warning("    - %s", p)
    return verdict


def _duration(path: str) -> float:
    try:
        return float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip())
    except (ValueError, subprocess.SubprocessError):
        return 3.0
