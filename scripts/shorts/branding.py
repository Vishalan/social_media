"""Channel-constant visual identity: thumbnail template and caption style.

Everything here is deliberately CONSTANT across videos, and is the opposite of
the per-story identity in `design/`. Those two do different jobs:

* `design.renderer` borrows the SOURCE's look, so each story's graphics feel
  like they came from that story.
* this module holds the CHANNEL's look, so a viewer recognises the video as
  yours before reading a word.

Changing a value here changes every future video, which is the point — it is
the one place a channel restyle happens.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FONTS = "/opt/commoncreed/assets/fonts"


@dataclass(frozen=True)
class Brand:
    """The channel's constants."""

    # Near-black rather than pure black: pure black crushes against OLED phone
    # bezels and loses the frame edge entirely.
    ink: str = "#0B0D11"
    paper: str = "#FFFFFF"
    accent: str = "#22D3EE"
    accent_warm: str = "#F59E0B"
    muted: str = "#9AA7B4"

    font_black: str = f"{FONTS}/Inter-Black.ttf"
    font_bold: str = f"{FONTS}/Inter-Bold.ttf"
    font_semi: str = f"{FONTS}/Inter-SemiBold.ttf"

    width: int = 1080
    height: int = 1920

    def rgb(self, hexstr: str) -> tuple[int, int, int]:
        h = hexstr.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


BRAND = Brand()


# --------------------------------------------------------------- captions
@dataclass(frozen=True)
class CaptionStyle:
    """How burned-in captions look.

    Measured against the two reference shorts (2026-08-17): their captions are
    far quieter than ours were. 2-4 words per cue, roughly 3.5% of frame height,
    white on a black pill at ~70% opacity, bottom-centre. No karaoke, no
    word-colouring, no bounce.

    Ours were 58px (5.4% of a 1080-wide frame at 1920 tall) carrying up to 28
    characters. The content panel is supposed to be doing the talking; a caption
    competing with it splits attention.
    """

    font: str = BRAND.font_bold
    # ~3.5% of a 1920-tall frame, matching the references. Was 58.
    size: int = 44
    color: str = "white"
    box: bool = True
    # Slightly lighter than before: the reference pill reads as a scrim, not a
    # solid block punched through the footage.
    box_color: str = "0x0B0D11@0.70"
    box_pad: int = 18
    y_frac: float = 0.615
    shadow_color: str = "black@0.35"
    shadow_x: int = 0
    shadow_y: int = 2
    # The references run 2-4 words. 2 words at 18 chars proved too tight —
    # it forced "and core" / "on GitHub" fragments because there was no budget
    # left to reach a natural phrase end. 3 words at 24 chars allows a phrase
    # while still fitting one line at 44px.
    max_chars: int = 24
    words_per_cue: int = 3

    def drawtext(self, text: str, start: float, end: float, *,
                 y_frac: Optional[float] = None) -> str:
        """One drawtext filter for a single cue."""
        esc = (text.replace("\\", "\\\\").replace(":", "\\:")
                   .replace("'", "’").replace("%", "\\%"))
        yf = self.y_frac if y_frac is None else y_frac
        parts = [
            f"drawtext=fontfile={self.font}",
            f"text='{esc}'",
            f"fontsize={self.size}",
            f"fontcolor={self.color}",
            f"x=(w-text_w)/2",
            f"y=h*{yf}",
            f"shadowcolor={self.shadow_color}",
            f"shadowx={self.shadow_x}",
            f"shadowy={self.shadow_y}",
            f"enable='between(t,{start:.3f},{end:.3f})'",
        ]
        if self.box:
            parts += ["box=1", f"boxcolor={self.box_color}",
                      f"boxborderw={self.box_pad}"]
        return ":".join(parts)


CAPTIONS = CaptionStyle()


# -------------------------------------------------------------- thumbnail
def _rel_lum(rgb: tuple[int, int, int]) -> float:
    """WCAG relative luminance from 8-bit sRGB."""
    out = []
    for v in rgb:
        c = v / 255
        out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """WCAG contrast ratio between two colours, 1 to 21."""
    la, lb = _rel_lum(a), _rel_lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def make_thumbnail(*, title: str, kicker: str, avatar_frame: str,
                   out_path: str, brand: Brand = BRAND,
                   accent: Optional[str] = None,
                   source_icon: Optional[str] = None,
                   source_domain: str = "") -> str:
    """Render the channel-standard cover frame.

    Template, fixed across every video:

        +--------------------------------+
        |  [ KICKER ]        accent pill  |   top 12%
        |                                 |
        |        presenter, bled          |   middle
        |        into a dark scrim        |
        |                                 |
        |  BIG TITLE                      |   lower third
        |  ---- accent rule               |
        +--------------------------------+

    The presenter is always in it — a face is the strongest thumbnail element
    available, and this is a channel fronted by a person. The scrim exists so
    white type stays legible over whatever the frame happens to contain.

    A cover frame is NOT the video's first frame. The first frame of a talking
    head is whatever the camera caught mid-blink, which is how the last video
    opened on a dark, downward-looking frame.
    """
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

    # The story palette's first entries are its BACKGROUND and body colours, so
    # passing one through as "accent" painted a near-black pill with near-black
    # text on it and an invisible rule under the title. An accent has to contrast
    # with both the dark scrim and the white type, so anything close to black or
    # white falls back to the channel accent.
    # Legibility is a property of a PAIR, not of a colour.
    #
    # The old test asked only whether the accent was mid-bright in absolute
    # terms, which cannot answer "will this be readable here". The same blind
    # spot in the Remotion theme picked a subject's background colour as its
    # own accent and rendered display type invisibly on itself. Here the accent
    # carries the kicker pill and the rule over a dark scrim, so it is measured
    # against that scrim.
    acc = brand.accent
    if accent:
        try:
            cand = brand.rgb(accent)
            scrim = brand.rgb(brand.ink)
            ratio = contrast_ratio(cand, scrim)
            if ratio >= 3.0:
                acc = accent
            else:
                logger.info("Thumbnail accent %s reads at only %.1f:1 against "
                            "the scrim — using the channel accent", accent, ratio)
        except (ValueError, IndexError):
            pass
    W, H = brand.width, brand.height

    base = Image.open(avatar_frame).convert("RGB").resize((W, H), Image.LANCZOS)

    # Vertical scrim: transparent across the face, deepening toward the type.
    scrim = Image.new("L", (1, H))
    for y in range(H):
        f = y / H
        if f < 0.36:
            a = int(120 * (1 - f / 0.36) + 40)      # slight top darkening
        elif f < 0.55:
            a = 40
        else:
            a = int(40 + 205 * ((f - 0.55) / 0.45) ** 1.4)
        scrim.putpixel((0, y), min(255, a))
    scrim = scrim.resize((W, H))
    dark = Image.new("RGB", (W, H), brand.rgb(brand.ink))
    img = Image.composite(dark, base, scrim.point(lambda v: v))
    img = Image.blend(base, img, 1.0)
    img = Image.composite(dark, base, scrim)

    d = ImageDraw.Draw(img, "RGBA")

    # --- kicker pill, top-left ---
    f_kick = ImageFont.truetype(brand.font_semi, 34)
    ktext = kicker.upper()[:26]
    kb = d.textbbox((0, 0), ktext, font=f_kick)
    kw, kh = kb[2] - kb[0], kb[3] - kb[1]
    px, py = 64, int(H * 0.075)
    d.rounded_rectangle([px, py, px + kw + 56, py + kh + 34], radius=10,
                        fill=brand.rgb(acc) + (255,))
    # Ink on the pill is only right when the pill is light. A dark accent got
    # near-black text on a near-black pill.
    pill_rgb = brand.rgb(acc)
    label = (brand.rgb(brand.ink)
             if contrast_ratio(brand.rgb(brand.ink), pill_rgb)
             >= contrast_ratio(brand.rgb(brand.paper), pill_rgb)
             else brand.rgb(brand.paper))
    d.text((px + 28 - kb[0], py + 17 - kb[1]), ktext, font=f_kick,
           fill=label + (255,))

    # --- title, lower third, wrapped and FITTED ---
    #
    # Shrink to fit rather than truncating. At a fixed 96px this title wrapped to
    # four lines and the fourth was dropped, so the cover read "X Just Open
    # Sourced The Algorithm That" — cutting "'Shadowbans' You", which is the
    # entire hook. A thumbnail that ends mid-clause is worse than a smaller one.
    max_w = W - 128
    max_lines = 4

    def wrap(font) -> list[str]:
        out, cur = [], ""
        for w in title.split():
            trial = f"{cur} {w}".strip()
            if d.textlength(trial, font=font) <= max_w or not cur:
                cur = trial
            else:
                out.append(cur)
                cur = w
        if cur:
            out.append(cur)
        return out

    size = 96
    f_title = ImageFont.truetype(brand.font_black, size)
    lines = wrap(f_title)
    while len(lines) > max_lines and size > 58:
        size -= 6
        f_title = ImageFont.truetype(brand.font_black, size)
        lines = wrap(f_title)
    if len(lines) > max_lines:
        # Still too long at the floor: drop whole words from the end rather than
        # a whole line, so the cut lands on a word boundary and is logged.
        logger.warning("Thumbnail title too long even at %dpx — trimming: %r",
                       size, title)
        lines = lines[:max_lines]
    if size != 96:
        logger.info("Thumbnail title fitted at %dpx across %d lines",
                    size, len(lines))

    line_h = int(size * 1.17)
    block_h = line_h * len(lines)
    ty = int(H * 0.78) - block_h
    for i, ln in enumerate(lines):
        d.text((64, ty + i * line_h), ln, font=f_title,
               fill=brand.rgb(brand.paper) + (255,))

    # --- accent rule under the title ---
    ry = ty + block_h + 26
    d.rounded_rectangle([64, ry, 64 + 190, ry + 11], radius=6,
                        fill=brand.rgb(acc) + (255,))

    # --- source badge: the publication's own mark, bottom-left ---
    #
    # A cover that names its source is doing two jobs: it says the claim is
    # reported rather than opinion, and it borrows the source's recognition.
    # The mark is the site's real favicon, so it reads instantly to anyone who
    # knows the publication.
    if source_domain:
        f_src = ImageFont.truetype(brand.font_semi, 30)
        by = ry + 58
        bx = 64
        if source_icon and Path(source_icon).is_file():
            try:
                ic = Image.open(source_icon).convert("RGBA").resize(
                    (46, 46), Image.LANCZOS)
                img.paste(ic, (bx, by - 8), ic)
                bx += 60
            except Exception:                      # noqa: BLE001 — cosmetic
                pass
        d.text((bx, by), source_domain.upper(), font=f_src,
               fill=brand.rgb(brand.muted) + (235,))

    # --- accent wash, tying the cover to the story's palette ---
    wash = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    wd = ImageDraw.Draw(wash)
    r, g, b = brand.rgb(acc)
    for i in range(120):
        a = int(26 * (1 - i / 120))
        wd.rectangle([0, H - 1 - i * 4, W, H - i * 4], fill=(r, g, b, a))
    img = Image.alpha_composite(img.convert("RGBA"), wash).convert("RGB")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=95)
    logger.info("Thumbnail: %s", out_path)
    return out_path


def extract_best_frame(video: str, out_png: str, *, at_s: float = 2.0) -> str:
    """Pull a frame for the thumbnail.

    Deliberately not frame 0. The opening frame of a talking head is whatever
    the camera caught — in the last video that was a dark, downward-looking
    frame that made a poor cover.
    """
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", f"{at_s:.2f}", "-i", video,
         "-vframes", "1", out_png], capture_output=True, text=True)
    if r.returncode != 0 or not Path(out_png).exists():
        raise RuntimeError(f"could not extract thumbnail frame: {r.stderr[-300:]}")
    return out_png
