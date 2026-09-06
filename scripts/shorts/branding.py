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

from .color import contrast_ratio, readable_on
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

    # BLACK, not Bold. One word alone on screen has no neighbours to give it
    # presence, so it has to carry weight by itself — at Bold it read as a
    # subtitle sitting on the video rather than as part of the design.
    font: str = BRAND.font_black
    # Up from 44. That number was set when a cue carried three words and had
    # to fit a line; a single word has the width to spare, and the reference's
    # single-word captions are proportionally larger than ours were.
    size: int = 56
    color: str = "white"
    box: bool = True
    # Slightly lighter than before: the reference pill reads as a scrim, not a
    # solid block punched through the footage.
    # Tighter and more opaque. A loose translucent pill reads as a caption
    # burned in by a tool; a snug near-solid one reads as a designed element,
    # which is the difference the reference lands.
    box_color: str = "0x0B0D11@0.82"
    box_pad: int = 14
    y_frac: float = 0.615
    shadow_color: str = "black@0.35"
    shadow_x: int = 0
    shadow_y: int = 2
    # The references run 2-4 words. 2 words at 18 chars proved too tight —
    # it forced "and core" / "on GitHub" fragments because there was no budget
    # left to reach a natural phrase end. 3 words at 24 chars allows a phrase
    # while still fitting one line at 44px.
    # ONE word per cue.
    #
    # The reference changes its caption roughly every 0.4s, one word at a
    # time — sampling it every 0.5s showed a different single word in every
    # frame. Three words at a time changes about once a second, and the
    # difference is not readability (a phrase is easier to read) but MOTION:
    # something on screen is always changing, which is what holds a thumb.
    max_chars: int = 16
    words_per_cue: int = 1

    # The caption face ALTERNATES cue to cue.
    #
    # Both reference shorts do this and it is their most distinctive device:
    # one cue is set in a serif italic in caps, the next in a bold sans in
    # lowercase, turn and turn about — "LINKEDIN," then "you figure out" then
    # "WHAT TO POST," then "when to post". A single face for every cue reads
    # as a subtitle track; alternating reads as an edit, because the change
    # itself marks the beat even when the words are ordinary.
    #
    # The serif is the display face already resolved for the story, so the
    # alternation stays inside the story's typography rather than importing a
    # second unrelated one.
    alt_font: str = f"{FONTS}/PlayfairDisplay-BlackItalic.ttf"
    alt_size: int = 62
    alt_upper: bool = True

    def drawtext(self, text: str, start: float, end: float, *,
                 y_frac: Optional[float] = None, alt: bool = False) -> str:
        """One drawtext filter for a single cue."""
        shown = text.upper() if (alt and self.alt_upper) else text
        esc = (shown.replace("\\", "\\\\").replace(":", "\\:")
                    .replace("'", "’").replace("%", "\\%"))
        yf = self.y_frac if y_frac is None else y_frac
        parts = [
            f"drawtext=fontfile={self.alt_font if alt else self.font}",
            f"text='{esc}'",
            f"fontsize={self.alt_size if alt else self.size}",
            f"fontcolor={self.color}",
            f"x=(w-text_w)/2",
            f"y=h*{yf}",
            f"shadowcolor={self.shadow_color}",
            f"shadowx={self.shadow_x}",
            f"shadowy={self.shadow_y}",
            f"enable='between(t,{start:.3f},{end:.3f})'",
        ]
        if self.box and not alt:
            parts += ["box=1", f"boxcolor={self.box_color}",
                      f"boxborderw={self.box_pad}"]
        elif alt:
            # The serif cue runs bare, so it needs its own edge over footage —
            # the same border-and-shadow the display tier uses, at caption
            # weight. A pill behind a serif italic fights the letterform.
            parts += ["borderw=2", "bordercolor=black@0.40",
                      "shadowcolor=black@0.55", "shadowx=0", "shadowy=3"]
        return ":".join(parts)


CAPTIONS = CaptionStyle()


# -------------------------------------------------------------- thumbnail
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

# ------------------------------------------------------- display captions
@dataclass(frozen=True)
class DisplayCaption:
    """Big editorial type for the beats that have to land.

    The second of two caption tiers, taken from a reference short that
    performs. Its ordinary narration runs as one small word in a dark pill,
    but its hook and its call to action are set LARGE in a high-contrast
    serif italic, no pill, stacked line over line, with the single word that
    carries the ask in the accent colour.

    The split is doing real work. A pill is legible and forgettable — right
    for the twenty seconds a viewer spends being informed. Display type is
    the opposite trade: it costs frame space and reading time, and buys
    emphasis. Using one style throughout means either the whole video shouts
    or none of it does, and the call to action is exactly the moment that
    cannot be a subtitle.

    Playfair Display, pinned at weight 900. The variable font renders at its
    DEFAULT instance under freetype, which is Regular — so the first build
    came out thin at every size, and no amount of scaling fixed it because
    the problem was weight, not scale. The instance is pinned at build time
    with fontTools rather than shipped as a second file.

    SIL Open Font License, so it carries no attribution obligation into a
    monetised video.
    """

    font: str = f"{FONTS}/PlayfairDisplay-BlackItalic.ttf"
    # Share of frame HEIGHT. Larger than the first pass: display type that is
    # merely bigger than the captions still reads as a caption. The reference
    # sets its CTA at roughly a tenth of the frame height.
    size_frac: float = 0.072
    accent_size_frac: float = 0.098
    color: str = "white"

    # Legibility over MOVING footage, where there is no fixed background to
    # measure against. A shadow alone was not enough — white type over a
    # bright sky washed out completely in a shipped frame. A thin dark border
    # gives every letterform an edge without putting a visible box on screen,
    # which is how a broadcast lower-third survives arbitrary video.
    border_w: int = 3
    border_color: str = "black@0.42"
    shadow_color: str = "black@0.58"
    shadow_y: int = 5

    # Type never runs to the frame edge. The reference always leaves a
    # margin, and a line that touches both edges reads as overflow whatever
    # it says.
    max_width_frac: float = 0.86

    words_per_line: int = 2
    max_lines: int = 3
    block_y_frac: float = 0.56

    def _fit_width(self, text: str, want: int, max_w: float) -> int:
        """The largest size at or under `want` that fits `max_w`."""
        try:
            from PIL import ImageFont
            size = want
            while size > 24:
                f = ImageFont.truetype(self.font, size)
                if f.getbbox(text)[2] - f.getbbox(text)[0] <= max_w:
                    return size
                size -= 4
            return size
        except Exception:                          # noqa: BLE001 — cosmetic
            # Without PIL, fall back to an advance-ratio estimate. Worse, but
            # it degrades to slightly-small rather than overflowing.
            est = max_w / max(1, len(text)) / 0.52
            return int(min(want, est))

    def stack(self, cues: list, frame_w: int, frame_h: int,
              accent: str = "#FF6B4A") -> list[str]:
        """drawtext filters for one run of cues, as an accumulating stack.

        Each line appears when its first word is spoken and STAYS until the
        block ends, so the viewer reads a growing sentence rather than a word
        replacing a word. That accumulation is what makes the treatment read
        as authored rather than auto-captioned.
        """
        if not cues:
            return []
        from .color import vivid

        # The story's accent, forced into a band that reads on anything.
        # Taking the palette accent as-is put near-white type over a bright
        # sky in a shipped frame — the contrast rule this project already
        # owns, simply never applied to display text.
        acc = vivid(accent)

        lines: list[tuple[float, float, str]] = []
        for i in range(0, len(cues), self.words_per_line):
            grp = cues[i:i + self.words_per_line]
            lines.append((grp[0][0], grp[-1][1],
                          " ".join(c[2] for c in grp)))

        out: list[str] = []
        for b in range(0, len(lines), self.max_lines):
            block = lines[b:b + self.max_lines]
            block_end = block[-1][1]
            # Lay the block out from its REAL line heights, so a stack whose
            # last line is half again as tall still sits centred.
            # MEASURE, then set. drawtext cannot report how wide a string will
            # be, so an unfitted size overflows on a long line: the first build
            # put "Anthropic wants" edge to edge with no margin at all. PIL
            # measures the same TrueType file freetype will render, so the
            # number is real rather than an advance-width estimate.
            max_w = frame_w * self.max_width_frac
            sizes = []
            for j, (_st, _en, text) in enumerate(block):
                last = (j == len(block) - 1) and len(block) > 1
                want = int(frame_h * (self.accent_size_frac if last
                                      else self.size_frac))
                sizes.append(self._fit_width(text, want, max_w))
            leads = [int(sz * 1.12) for sz in sizes]
            total = sum(leads)
            top = frame_h * self.block_y_frac - total / 2

            y = top
            for j, (st, _en, text) in enumerate(block):
                last = (j == len(block) - 1) and len(block) > 1
                col = acc if last else self.color
                esc = (text.replace("\\", "\\\\").replace(":", "\\:")
                           .replace("'", "\u2019").replace("%", "\\%"))
                out.append(":".join([
                    f"drawtext=fontfile={self.font}",
                    f"text='{esc}'",
                    f"fontsize={sizes[j]}",
                    f"fontcolor={col}",
                    "x=(w-text_w)/2",
                    f"y={y:.0f}",
                    f"borderw={self.border_w}",
                    f"bordercolor={self.border_color}",
                    f"shadowcolor={self.shadow_color}",
                    "shadowx=0",
                    f"shadowy={self.shadow_y}",
                    f"enable='between(t,{st:.3f},{block_end:.3f})'",
                ]))
                y += leads[j]
        return out


DISPLAY = DisplayCaption()
