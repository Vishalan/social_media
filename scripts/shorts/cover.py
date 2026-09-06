"""The cover frame, in the feed's own language.

Built against a grid of the owner's best-performing posts. What they share is
not a template but a grammar, and it is worth naming precisely because the
previous cover got every part of it backwards:

* DISPLAY SERIF, SET LARGE, AT THE TOP. A didone in caps, frequently with an
  italic lowercase line under it — "ISN'T BEHIND / they might be waiting",
  "PROFILE AUDIT / in 60 seconds". The old cover set a bold sans across the
  bottom, which is the YouTube-thumbnail idiom, not this one.
* THE PRESENTER IS OFF-CENTRE, and the type occupies the space they are not
  in. Centring the face leaves nowhere for type to go, so it ends up on top
  of the person.
* A WARM, FILMIC GRADE. Every frame in the grid is lit warm and graded soft.
  A raw camera frame beside them looks like a screenshot.
* AN ARTIFACT CARRIES THE BRAND — a printed sheet, a laptop, a card with the
  subject's mark on it. That is what makes a cover about a company rather
  than about a person talking.

Text is composited here rather than generated, deliberately. Image models
still misspell display type, and the pipeline already owns a typography stack
that is measured, contrast-checked and width-fitted. Generating the picture
and setting the words are different problems and only one of them is hard.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

from .branding import BRAND
from .color import contrast_ratio, to_rgb, readable_on

logger = logging.getLogger(__name__)

FONTS = "/opt/commoncreed/assets/fonts"
DISPLAY = f"{FONTS}/PlayfairDisplay-Black.ttf"
DISPLAY_IT = f"{FONTS}/PlayfairDisplay-BlackItalic.ttf"


def _grade(src: str, dst: str, w: int, h: int) -> str:
    """Warm, filmic, and darkened where the type will sit.

    Three things at once, all of which the reference frames have and a raw
    capture does not: a warm lift, a gentle S-curve for contrast, and a
    gradient scrim down from the top so display type has something to sit on
    whatever the room behind it happens to be doing.
    """
    # The presenter is pushed into the LOWER two-thirds, and the space above
    # is a blurred, darkened continuation of the same frame.
    #
    # The first version graded the frame in place and set the headline over
    # it, which put display type across the subject's eyes — there was no
    # negative space because a centred close-up has none. Every cover in the
    # grid keeps the type clear of the face, so the fix is compositional
    # rather than typographic: make the room the type needs.
    #
    # The upper field is derived from the frame itself rather than filled
    # flat, so it carries the room's own colour and the cover still reads as
    # one photograph instead of a banner glued to a picture.
    top = int(h * 0.34)
    sub_h = h - top
    vf = (
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        "colorbalance=rs=.04:gs=-.01:bs=-.05:rm=.05:gm=.01:bm=-.04,"
        "eq=contrast=1.10:saturation=0.92:gamma=1.02,split=2[base][bg];"
        # The field: same frame, blown out of focus and dimmed.
        f"[bg]crop={w}:{int(h*0.5)}:0:0,scale={w}:{top},"
        f"gblur=sigma={max(12, w//48)},eq=brightness=-0.10:saturation=0.80[field];"
        # The subject, scaled to the remaining height.
        # Fill BOTH axes before cropping. Scaling to the target height alone
        # gave a 713px-wide image for a 1080px crop and the graph failed
        # outright — a 9:16 source scaled to a shorter box is narrower, not
        # wider.
        f"[base]scale={w}:{sub_h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{sub_h}[subj];"
        f"[field][subj]vstack=inputs=2,"
        # A short feather across the seam so the two do not meet on a line.
        # A wide feather across the seam. The first pass used 26px and the
        # boundary was still a visible line, because the two halves differ in
        # focus and brightness as well as content — a narrow blend hides a
        # colour step but not a focus step.
        + ",".join(
            f"drawbox=x=0:y={top - 70 + i}:w={w}:h=2:"
            f"color=black@{0.13 * (1 - abs(i - 70) / 70):.3f}:t=fill"
            for i in range(0, 140, 2))
        + ",vignette=PI/5[out]"
    )
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src,
                    "-filter_complex", vf, "-map", "[out]",
                    "-frames:v", "1", dst], check=True)
    return dst


def _fit(text: str, font: str, max_w: float, start: int, floor: int = 40) -> int:
    from PIL import ImageFont
    size = start
    while size > floor:
        f = ImageFont.truetype(font, size)
        b = f.getbbox(text)
        if b[2] - b[0] <= max_w:
            return size
        size -= 4
    return size


def build(*, frame: str, out_path: str, headline: str, kicker: str = "",
          sub: str = "", accent: str = "#E8E2D4", width: int = 1080,
          height: int = 1920, icon: Optional[str] = None,
          domain: str = "") -> str:
    """Render one cover frame."""
    from PIL import Image, ImageDraw, ImageFont

    tmp = str(Path(out_path).with_suffix(".graded.jpg"))
    _grade(frame, tmp, width, height)
    img = Image.open(tmp).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")

    pad = int(width * 0.072)
    max_w = width - pad * 2
    cream = (242, 237, 227)

    # The accent must read on the scrim, which is dark by construction. A
    # palette accent that is itself dark disappears into it, so anything under
    # 3:1 falls back to the cream the reference uses for nearly every line.
    acc = to_rgb(accent)
    if contrast_ratio(acc, (26, 24, 22)) < 3.0:
        acc = cream

    y = int(height * 0.055)

    # Kicker: small, letterspaced, uppercase.
    if kicker:
        kf = ImageFont.truetype(BRAND.font_black, int(height * 0.0155))
        txt = " ".join(kicker.upper()[:26])          # tracked out by hand
        d.text((pad, y), txt, font=kf, fill=acc + (255,))
        y += int(height * 0.036)

    # HEADLINE — display serif, caps, up to three lines.
    #
    # Wrapped by measurement and then fitted, because the grid's headlines run
    # from two words to six and a fixed size only suits one of those.
    words = headline.upper().split()
    size = int(height * 0.078)
    lines: list[str] = []
    while size > 44:
        f = ImageFont.truetype(DISPLAY, size)
        lines, cur = [], ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if f.getbbox(trial)[2] <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        if len(lines) <= 3:
            break
        size -= 6
    f = ImageFont.truetype(DISPLAY, size)
    lead = int(size * 0.94)                          # tight, as in the grid
    for ln in lines:
        d.text((pad, y), ln, font=f, fill=cream + (255,))
        y += lead

    # Sub-line: italic, lowercase, smaller — the grid's "they might be
    # waiting" / "in 60 seconds". It is what stops the cover reading as a
    # headline with nothing under it.
    if sub:
        ss = _fit(sub, DISPLAY_IT, max_w * 0.86, int(size * 0.44), 26)
        sf = ImageFont.truetype(DISPLAY_IT, ss)
        y += int(size * 0.10)
        d.text((pad + int(size * 0.06), y), sub, font=sf,
               fill=acc + (245,))
        y += int(ss * 1.2)

    # Source line, bottom-left, quiet.
    if domain:
        df = ImageFont.truetype(BRAND.font_semi, int(height * 0.0145))
        by = height - int(height * 0.052)
        bx = pad
        if icon and Path(icon).is_file():
            try:
                ic = Image.open(icon).convert("RGBA").resize(
                    (int(height * 0.022), int(height * 0.022)), Image.LANCZOS)
                img.paste(ic, (bx, by - 4), ic)
                bx += int(height * 0.030)
            except Exception:                        # noqa: BLE001 — cosmetic
                pass
        d.text((bx, by), domain.upper(), font=df, fill=(196, 190, 180, 230))

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=95)
    Path(tmp).unlink(missing_ok=True)
    logger.info("Cover: %s (%d lines at %dpx)", out_path, len(lines), size)
    return out_path


def prepend(video: str, cover: str, out_path: str, *, hold_s: float = 0.45,
            fps: int = 25) -> str:
    """Put the cover on the front of the video.

    Instagram and TikTok pick a cover from the opening frames, so a designed
    cover only becomes the cover if it is IN the video. The hold is short on
    purpose: long enough to be picked and to register as a title card, short
    enough that it is not a stall — a frozen second at the top of a short is
    paid for in retention.
    """
    still = str(Path(out_path).with_suffix(".cover.mp4"))
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", video],
        capture_output=True, text=True).stdout.strip().strip(",")
    w, h = (int(x) for x in probe.split(",")[:2])

    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", cover,
         "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono",
         "-t", f"{hold_s:.3f}",
         "-vf", (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                 f"crop={w}:{h},fps={fps}"),
         "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest", still], check=True)

    listing = str(Path(out_path).with_suffix(".concat.txt"))
    Path(listing).write_text(f"file '{still}'\nfile '{video}'\n")
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", listing, "-c", "copy", out_path],
        capture_output=True, text=True)
    if r.returncode != 0:
        # Streams differ enough that a stream copy will not splice them;
        # re-encode rather than shipping the video without its cover.
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", listing, "-c:v", "libx264", "-crf", "18",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
             out_path], check=True)
    Path(listing).unlink(missing_ok=True)
    Path(still).unlink(missing_ok=True)
    logger.info("Cover prepended (%.2fs) -> %s", hold_s, Path(out_path).name)
    return out_path
