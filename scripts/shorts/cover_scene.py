"""Build the cover as a SCENE, not a frame with type on it.

Read off a grid of the owner's best posts, which share a composition far more
specific than "photo plus headline":

* The presenter sits in the RIGHT of the frame, from mid-torso up, turned
  slightly in. They never fill the middle.
* An ARTIFACT occupies the lower left — a printed sheet, a card, a laptop —
  carrying the subject's mark. It is the thing the post is about, made
  physical, and it is what stops the cover being a photograph of a person.
* The HEADLINE takes the top left, in a display serif, caps, cream.
* The whole frame is graded WARM. Sampling one reference cell returns
  #301800 and #483018 in the shadows and #C0A890 in the midtones — warm
  brown throughout, never neutral black. That grade is the channel's
  signature and it is the same in every post regardless of subject.

The subject's colour only enters through its own mark. Everything else is
the channel's palette, which is what makes a grid of these read as one
account rather than as fifteen unrelated posts.
"""
from __future__ import annotations

import logging
import math
import subprocess
from pathlib import Path
from typing import Optional

from .color import to_rgb

logger = logging.getLogger(__name__)

FONTS = "/opt/commoncreed/assets/fonts"
DISPLAY = f"{FONTS}/PlayfairDisplay-Black.ttf"
DISPLAY_IT = f"{FONTS}/PlayfairDisplay-BlackItalic.ttf"

# The channel's constants, measured from the reference grid rather than
# chosen. Changing these changes every future cover, which is the point.
SHADOW = (0x2A, 0x1C, 0x12)
MID = (0xC0, 0xA8, 0x90)
CREAM = (0xF2, 0xEC, 0xDE)
INK = (0x1A, 0x14, 0x0E)


def _cutout(frame: str, out_png: str) -> Optional[str]:
    """Separate the presenter from their background.

    Without this the presenter cannot be MOVED, and moving them is the whole
    composition — every reference cover has them off to one side with the
    type in the space they are not in. A raw frame is a centred close-up and
    no amount of grading makes room in it.
    """
    try:
        from rembg import remove, new_session
        from PIL import Image
        img = Image.open(frame).convert("RGBA")
        # Try several matting models and keep the one that actually cut
        # something. u2net_human_seg left 77% of a tight close-up opaque —
        # the person fills the frame, so "keep the human" keeps almost
        # everything. A matte that removes nothing is worse than none: it
        # composites the original room back in as a hard-edged rectangle.
        best, best_clear = None, 0.0
        for name in ("isnet-general-use", "u2net", "u2net_human_seg"):
            try:
                cut = remove(img, session=new_session(name))
            except Exception:                       # noqa: BLE001 — try next
                continue
            a = cut.split()[3]
            hist = a.histogram()
            clear = sum(hist[:16]) / max(1, sum(hist))
            logger.info("matte %s: %.0f%% removed", name, clear * 100)
            if clear > best_clear:
                best, best_clear = cut, clear
            if clear > 0.30:
                break
        if best is None or best_clear < 0.12:
            logger.info("no usable matte (best removed %.0f%%) — composing on "
                        "the raw frame", best_clear * 100)
            return None
        best.save(out_png)
        return out_png
    except Exception as exc:                        # noqa: BLE001 — optional
        logger.info("cutout unavailable (%s) — composing on the raw frame",
                    str(exc)[:100])
        return None


def _warm(img):
    """The channel grade: warm shadows, lifted tan midtones, cream highs."""
    from PIL import Image
    px = img.convert("RGB")
    r, g, b = px.split()
    # A per-channel curve. Warming by adding a flat tint muddies the whites;
    # curving each channel keeps highlights clean while the shadows go brown.
    r = r.point(lambda v: min(255, int(v * 1.06 + 10)))
    g = g.point(lambda v: min(255, int(v * 1.00 + 4)))
    b = b.point(lambda v: min(255, int(v * 0.92 + 0)))
    return Image.merge("RGB", (r, g, b))


def _bokeh_ground(w: int, h: int, seed_img=None):
    """The room behind everything: warm, soft, and out of focus."""
    from PIL import Image, ImageFilter, ImageDraw
    import random
    # BUILT, not borrowed. Blurring the source frame produced a muddy smear
    # carrying the subject's own shape as a ghost behind them — the reference
    # rooms are soft but they are still rooms, with light falling off from a
    # lamp. A constructed gradient is cleaner and, more usefully, identical
    # from post to post, which is what makes a grid read as one channel.
    g = Image.new("RGB", (w, h), SHADOW)
    d0 = ImageDraw.Draw(g)
    warm_hi = (0x6B, 0x4A, 0x2E)
    for i in range(h):
        # Light source high on the subject's side, falling off down and left.
        t = i / h
        k = (1 - t) ** 1.7
        d0.line([(0, i), (w, i)],
                fill=(int(SHADOW[0] + (warm_hi[0] - SHADOW[0]) * k),
                      int(SHADOW[1] + (warm_hi[1] - SHADOW[1]) * k),
                      int(SHADOW[2] + (warm_hi[2] - SHADOW[2]) * k)))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dg = ImageDraw.Draw(glow)
    rr = int(w * 0.62)
    dg.ellipse([int(w * 0.52) - rr, int(h * 0.10) - rr,
                int(w * 0.52) + rr, int(h * 0.10) + rr],
               fill=(255, 196, 130, 46))
    g = Image.alpha_composite(g.convert("RGBA"),
                              glow.filter(ImageFilter.GaussianBlur(w // 7))
                              ).convert("RGB")
    d = ImageDraw.Draw(g, "RGBA")
    # A vertical warm falloff, brighter behind the subject's side.
    for i in range(80):
        y0 = int(h * i / 80)
        a = int(120 * (i / 80) ** 1.6)
        d.rectangle([0, y0, w, y0 + h // 80 + 1], fill=SHADOW + (a,))
    rnd = random.Random(7)
    # Bokeh highlights, as a warm lamp in a room produces.
    for _ in range(14):
        rr = rnd.randint(int(w * 0.04), int(w * 0.11))
        cx, cy = rnd.randint(0, w), rnd.randint(0, int(h * 0.62))
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  fill=(255, 214, 160, rnd.randint(8, 20)))
    return g.filter(ImageFilter.GaussianBlur(w // 90))


def _draw_artifact(img, x: int, y: int, w: int, h: int, *,
                   text: str, icon: Optional[str]) -> None:
    """Draw the printed card straight onto the cover.

    Composed in place rather than built as a layer and pasted. Two earlier
    versions built the card separately and lost its paper on the way in:
    PIL's `paste` with an RGBA image as its own mask does not composite alpha
    the way it reads as though it should, and the card arrived 3% opaque —
    a logo and some text floating on the background with no card behind them.
    Drawing directly has no compositing step to get wrong.
    """
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    # Shadow first, on its own layer so it can be blurred without touching
    # anything else, then merged under the card.
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(
        [x + int(w * 0.03), y + int(h * 0.035), x + w + int(w * 0.03),
         y + h + int(h * 0.035)],
        radius=int(w * 0.02), fill=(18, 11, 5, 165))
    sh = sh.filter(ImageFilter.GaussianBlur(int(w * 0.055)))
    img.alpha_composite(sh)

    d = ImageDraw.Draw(img, "RGBA")
    # Paper: warm off-white, never pure, with a hairline edge.
    d.rounded_rectangle([x, y, x + w, y + h], radius=int(w * 0.018),
                        fill=(250, 247, 241, 255),
                        outline=(222, 213, 197, 255), width=2)
    # A soft top-lit falloff, so the card is lit by the same lamp as the room.
    for i in range(h):
        a = int(14 * (i / h) ** 1.5)
        d.line([(x + 2, y + i), (x + w - 2, y + i)], fill=(198, 176, 150, a))

    cy = y + int(h * 0.16)
    if icon and Path(icon).is_file():
        try:
            side = int(min(w, h) * 0.34)
            ic = Image.open(icon).convert("RGBA").resize((side, side), Image.LANCZOS)
            img.alpha_composite(ic, (x + (w - side) // 2, cy))
            cy += side + int(h * 0.05)
        except Exception:                           # noqa: BLE001 — cosmetic
            pass
    if text:
        size = int(h * 0.13)
        while size > 12:
            f = ImageFont.truetype(DISPLAY, size)
            if d.textlength(text, font=f) <= w * 0.84:
                break
            size -= 2
        f = ImageFont.truetype(DISPLAY, size)
        d.text((x + (w - d.textlength(text, font=f)) / 2, cy), text,
               font=f, fill=INK + (255,))


def typeset(*, photo: str, out_path: str, headline: str, sub: str = "",
            kicker: str = "", icon: Optional[str] = None, domain: str = "",
            width: int = 1080, height: int = 1920) -> str:
    """Set the cover type over a finished photograph.

    The generated photo already contains the room, the person and the object
    they are presenting — everything the composited path had to fake. What it
    deliberately does NOT contain is a single readable word: the sheet in
    frame is blank, and the prompt forbids text and logos, because diffusion
    models still misspell display type and inventing a wrong brand mark on a
    cover is worse than having none.

    So the words are set here, with the stack that is already measured,
    contrast-checked and width-fitted, over a photograph that was composed to
    leave room for them.
    """
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    img = Image.open(photo).convert("RGB")
    if img.size != (width, height):
        # Fill the cover's frame, cropping from the TOP. The generator places
        # the subject low and centre, so height is taken off the ceiling
        # rather than the face.
        scale = max(width / img.width, height / img.height)
        img = img.resize((int(img.width * scale), int(img.height * scale)),
                         Image.LANCZOS)
        left = (img.width - width) // 2
        img = img.crop((left, 0, left + width, height))

    # A scrim only where the type goes. The reference covers are lit so the
    # headline sits on wall or ceiling, but a generated room varies, and cream
    # type on a bright lamp is unreadable.
    scrim = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    sd = ImageDraw.Draw(scrim)
    band = int(height * 0.42)
    for i in range(band):
        sd.line([(0, i), (width, i)],
                fill=(20, 14, 8, int(150 * (1 - i / band) ** 1.25)))
    img = Image.alpha_composite(img.convert("RGBA"),
                                scrim.filter(ImageFilter.GaussianBlur(2))
                                ).convert("RGB")

    d = ImageDraw.Draw(img, "RGBA")
    pad = int(width * 0.062)
    max_w = width * 0.80
    y = int(height * 0.052)

    if kicker:
        kf = ImageFont.truetype(f"{FONTS}/Inter-Black.ttf", int(height * 0.0145))
        d.text((pad, y), " ".join(kicker.upper()[:24]), font=kf, fill=MID + (255,))
        y += int(height * 0.033)

    words = headline.upper().split()
    size = int(height * 0.080)
    lines: list[str] = []
    while size > 42:
        f = ImageFont.truetype(DISPLAY, size)
        lines, cur = [], ""
        for w_ in words:
            t = f"{cur} {w_}".strip()
            if d.textlength(t, font=f) <= max_w or not cur:
                cur = t
            else:
                lines.append(cur); cur = w_
        if cur:
            lines.append(cur)
        if len(lines) <= 3:
            break
        size -= 5
    f = ImageFont.truetype(DISPLAY, size)
    # Leading is a fraction of the point size, which is the right tightness
    # for display type. The BOTTOM of the block is not: a 0.92 advance sits
    # well above the last line's descenders, so anything set from that y
    # lands inside the headline. Track the real ink bottom for the handoff.
    ink_bottom = y
    for ln in lines:
        for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            d.text((pad + ox, y + oy), ln, font=f, fill=(22, 15, 8, 105))
        d.text((pad, y), ln, font=f, fill=CREAM + (255,))
        ink_bottom = y + f.getbbox(ln)[3]
        y += int(size * 0.92)

    if sub:
        sf = ImageFont.truetype(DISPLAY_IT, int(size * 0.42))
        # getbbox()'s top is the ascent gap above the ink; subtract it so the
        # gap below the headline is the gap you actually see.
        y = ink_bottom + int(size * 0.20) - sf.getbbox(sub)[1]
        d.text((pad + int(size * 0.04), y), sub, font=sf, fill=MID + (250,))

    if domain:
        df = ImageFont.truetype(f"{FONTS}/Inter-SemiBold.ttf", int(height * 0.0135))
        by = height - int(height * 0.042)
        bx = pad
        if icon and Path(icon).is_file():
            try:
                side = int(height * 0.023)
                ic = Image.open(icon).convert("RGBA").resize((side, side), Image.LANCZOS)
                img.paste(ic, (bx, by - 4), ic)
                bx += int(height * 0.031)
            except Exception:                       # noqa: BLE001 — cosmetic
                pass
        d.text((bx, by), domain.upper(), font=df, fill=(206, 194, 176, 225))

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=95)
    logger.info("Typeset cover: %s (%d lines @ %dpx)", out_path, len(lines), size)
    return out_path


def build(*, frame: str, out_path: str, headline: str, sub: str = "",
          kicker: str = "", artifact_text: str = "", icon: Optional[str] = None,
          accent: str = "#C0A890", domain: str = "",
          width: int = 1080, height: int = 1920) -> str:
    from PIL import (Image, ImageDraw, ImageFont, ImageFilter,
                     ImageChops)

    src = Image.open(frame).convert("RGB")
    ground = _bokeh_ground(width, height, src)
    canvas = ground.convert("RGBA")

    # --- the presenter, moved to the right ---------------------------------
    cut = _cutout(frame, str(Path(out_path).with_suffix(".cut.png")))
    subj_w = int(width * 0.78)
    if cut:
        person = Image.open(cut).convert("RGBA")
        # Trim to the visible subject so placement is about the PERSON and
        # not about how much empty alpha the frame happened to include.
        # The ALPHA channel's bounds. getbbox() on an RGBA image considers
        # every channel, and RGB is non-zero across the whole frame, so it
        # always returned the full rectangle and the crop did nothing.
        bbox = person.split()[3].getbbox()
        if bbox:
            person = person.crop(bbox)
        ph = int(height * 0.62)
        pw = int(person.width * ph / person.height)
        person = person.resize((pw, ph), Image.LANCZOS)
        a = person.split()[3]
        # FEATHER the matte. A hard alpha edge against a soft ground is the
        # tell that gives a cutout away — the first build had a visible halo
        # tracing the head. One pixel of blur on the mask reads as depth of
        # field instead of as a mistake.
        # A GENEROUS feather, plus a falloff toward the matte's own edges.
        #
        # isnet removes about a third of a tight close-up, so the third it
        # keeps includes some of the room — which arrives as a hard-edged
        # rectangle of the original background sitting on the new ground. A
        # single pixel of blur hides a jagged edge; it does not hide a
        # straight one. Fading the alpha toward the bounding box dissolves
        # whatever the matte failed to remove into the ground behind it.
        a = a.filter(ImageFilter.GaussianBlur(3.0))
        fade = Image.new("L", a.size, 255)
        fd = ImageDraw.Draw(fade)
        edge = max(8, int(min(a.size) * 0.09))
        for i in range(edge):
            v = int(255 * (i / edge) ** 0.8)
            fd.rectangle([i, i, a.size[0] - 1 - i, a.size[1] - 1 - i],
                         outline=v)
        a = ImageChops.multiply(a, fade)
        person = Image.merge("RGBA", (*_warm(person).split(), a))
        # Right-anchored, kept fully inside the frame.
        px = min(width - pw, int(width * 0.44))
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        layer.paste(person, (max(px, width - pw), height - ph), person)
        canvas = Image.alpha_composite(canvas, layer)
    else:
        warm = _warm(src).resize((subj_w, int(subj_w * src.height / src.width)))
        canvas.alpha_composite(warm.convert("RGBA"),
                               (width - subj_w, height - warm.height))

    # --- the artifact, lower left -----------------------------------------
    if artifact_text or icon:
        aw = int(width * 0.38)
        ah = int(aw * 1.20)
        _draw_artifact(canvas, int(width * 0.055), int(height * 0.555),
                       aw, ah, text=artifact_text, icon=icon)

    img = canvas.convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")

    # --- type, top left ----------------------------------------------------
    pad = int(width * 0.062)
    max_w = width * 0.72
    y = int(height * 0.055)

    if kicker:
        kf = ImageFont.truetype(f"{FONTS}/Inter-Black.ttf", int(height * 0.0145))
        d.text((pad, y), " ".join(kicker.upper()[:24]), font=kf,
               fill=MID + (255,))
        y += int(height * 0.032)

    words = headline.upper().split()
    size = int(height * 0.082)
    lines: list[str] = []
    while size > 42:
        f = ImageFont.truetype(DISPLAY, size)
        lines, cur = [], ""
        for w_ in words:
            t = f"{cur} {w_}".strip()
            if d.textlength(t, font=f) <= max_w or not cur:
                cur = t
            else:
                lines.append(cur); cur = w_
        if cur:
            lines.append(cur)
        if len(lines) <= 3:
            break
        size -= 5
    f = ImageFont.truetype(DISPLAY, size)
    for ln in lines:
        # A soft dark halo, so cream type survives a bright bokeh highlight
        # drifting behind it.
        for ox, oy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            d.text((pad + ox, y + oy), ln, font=f, fill=(26, 18, 10, 90))
        d.text((pad, y), ln, font=f, fill=CREAM + (255,))
        y += int(size * 0.93)

    if sub:
        ss = int(size * 0.40)
        sf = ImageFont.truetype(DISPLAY_IT, ss)
        y += int(size * 0.10)
        d.text((pad + int(size * 0.05), y), sub, font=sf, fill=MID + (250,))

    if domain:
        df = ImageFont.truetype(f"{FONTS}/Inter-SemiBold.ttf", int(height * 0.0135))
        d.text((pad, height - int(height * 0.042)), domain.upper(), font=df,
               fill=(196, 182, 162, 220))

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=95)
    for junk in (Path(out_path).with_suffix(".cut.png"),):
        junk.unlink(missing_ok=True)
    logger.info("Cover scene: %s (%d lines @ %dpx, cutout=%s)",
                out_path, len(lines), size, bool(cut))
    return out_path
