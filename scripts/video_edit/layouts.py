"""Frame layouts that keep the presenter on screen alongside the content.

Earlier assemblies cut FULL-FRAME between the avatar and each graphic, so the
presenter disappeared for seconds at a time. These layouts keep them present:
content occupies the frame, the avatar sits in a fixed window.

Two forms:

``pip_circle``
    Avatar in a circular window, content full-frame behind. Research note worth
    recording: no published sizing, positioning or usage convention exists for
    round PIP in short-form. It is documented almost entirely as a livestream /
    OBS and TikTok *reaction-cam* device, and carries an informal "responding to
    someone else's content" connotation. A rounded rectangle avoids that
    association. The circle is used here because it was explicitly requested;
    the finding is logged, not silently overridden.

``half_stacked``
    Content on top, presenter below. Vertical stack, never side-by-side: a 9:16
    frame split left/right gives two 540x1920 panels, which is unusable. The
    presenter takes the LOWER half because platform UI clips the bottom 12-20%
    of frame, and losing part of a talking head there costs less than losing
    part of a stat.
"""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

LayoutName = Literal["pip_circle", "half_stacked", "full"]


class LayoutError(RuntimeError):
    """Raised when a layout cannot be composited."""


@dataclass(frozen=True)
class LayoutSpec:
    """Geometry for one layout at a given frame size."""

    name: LayoutName
    width: int = 1080
    height: int = 1920

    # --- pip_circle -----------------------------------------------------
    # Diameter as a fraction of frame width. 0.34 keeps the face readable on a
    # phone without covering the content it is meant to accompany.
    pip_diameter_frac: float = 0.34
    pip_margin_frac: float = 0.05
    # Bottom-left: the bottom-RIGHT corner is where TikTok stacks its action
    # rail and Reels its audio disc, so a PIP there is partly occluded.
    pip_corner: str = "bottom-left"
    # Where the FACE sits vertically in the source frame, as a fraction of
    # its height. A plain centre-crop of a 9:16 talking-head lands on the
    # torso and hands — the head is in the upper third. 0.24 matches the
    # gesture library's framing (face centre ~195px of an 854px frame).
    pip_face_y_frac: float = 0.24

    # --- half_stacked ---------------------------------------------------
    # Content gets the top 52%: slightly more than half, because the bottom
    # 12-20% of frame is eaten by platform UI and the presenter absorbs that
    # loss better than a graphic does.
    content_frac: float = 0.52

    @property
    def pip_diameter(self) -> int:
        return int(self.width * self.pip_diameter_frac)

    @property
    def pip_xy(self) -> tuple[int, int]:
        d = self.pip_diameter
        m = int(self.width * self.pip_margin_frac)
        # Lifted clear of the caption band (y ~= 0.74H) and the bottom UI strip.
        bottom_y = int(self.height * 0.60)
        if self.pip_corner == "bottom-right":
            return self.width - d - m, bottom_y
        if self.pip_corner == "top-right":
            return self.width - d - m, int(self.height * 0.10)
        if self.pip_corner == "top-left":
            return m, int(self.height * 0.10)
        return m, bottom_y

    @property
    def content_height(self) -> int:
        # Even height: h264 with yuv420p requires even dimensions.
        return int(self.height * self.content_frac) // 2 * 2

    @property
    def presenter_height(self) -> int:
        return self.height - self.content_height


def _circle_mask(path: Path, diameter: int, *, ring_px: int = 4) -> str:
    """Write a white-on-transparent circle used as an alpha mask.

    Anti-aliased by drawing at 4x and downsampling; a hard-edged mask produces
    visible stair-stepping on the circle at this diameter.
    """
    from PIL import Image, ImageDraw

    # LUMA-encoded, not alpha-encoded: ffmpeg's `alphamerge` takes the SECOND
    # input's LUMA as the alpha channel. A white-with-alpha PNG has luma 255
    # everywhere, so the mask was fully opaque and the PIP rendered as a SQUARE
    # with a ring drawn on top. Black outside the circle, white inside.
    ss = 4
    big = Image.new("L", (diameter * ss, diameter * ss), 0)
    ImageDraw.Draw(big).ellipse([0, 0, diameter * ss - 1, diameter * ss - 1], fill=255)
    small = big.resize((diameter, diameter), Image.LANCZOS)
    small.convert("RGB").save(path)
    return str(path)


def _circle_ring(path: Path, diameter: int, *, width_px: int = 4,
                 rgba_color: tuple = (255, 255, 255, 215)) -> str:
    """Pre-render the rim as a PNG.

    Drawn here rather than with ffmpeg's ``geq``: geq evaluates a per-pixel
    expression per frame and made a 3-second composite exceed five minutes.
    A static PNG overlay costs nothing.
    """
    from PIL import Image, ImageDraw

    ss = 4
    big = Image.new("RGBA", (diameter * ss, diameter * ss), (0, 0, 0, 0))
    ImageDraw.Draw(big).ellipse(
        [width_px * ss // 2, width_px * ss // 2,
         diameter * ss - 1 - width_px * ss // 2, diameter * ss - 1 - width_px * ss // 2],
        outline=rgba_color, width=width_px * ss,
    )
    big.resize((diameter, diameter), Image.LANCZOS).save(path)
    return str(path)


def pip_circle_filter(
    spec: LayoutSpec,
    *,
    content_label: str = "0:v",
    avatar_label: str = "1:v",
    mask_label: str = "2:v",
    ring_label: str = "3:v",
    out_label: str = "vout",
    ring: bool = True,
) -> str:
    """FFmpeg filter_complex compositing the avatar as a circular PIP.

    The avatar is centre-cropped to a square before scaling, so the face is not
    squashed — the source is 9:16 and a straight scale to a square would
    distort it badly.
    """
    d = spec.pip_diameter
    x, y = spec.pip_xy
    parts = [
        f"[{content_label}]scale={spec.width}:{spec.height}:"
        f"force_original_aspect_ratio=increase,crop={spec.width}:{spec.height},"
        f"setsar=1[bg]",
        # Square centre-crop of the presenter, then scale to the PIP diameter.
        # Square crop positioned on the face, clamped inside the frame.
        f"[{avatar_label}]crop='min(iw,ih)':'min(iw,ih)':"
        f"'(iw-min(iw,ih))/2':"
        f"'clip(ih*{spec.pip_face_y_frac}-min(iw,ih)/2,0,ih-min(iw,ih))',"
        f"scale={d}:{d},setsar=1[pipsq]",
        f"[pipsq][{mask_label}]alphamerge[pipc]",
    ]
    if ring:
        # Rim supplied as a pre-rendered PNG input (see _circle_ring) — it reads
        # as intentional framing and stops the circle dissolving into a dark
        # background, at zero per-frame cost.
        parts.append(f"[bg][pipc]overlay={x}:{y}[withpip]")
        parts.append(f"[withpip][{ring_label}]overlay={x}:{y}[{out_label}]")
    else:
        parts.append(f"[bg][pipc]overlay={x}:{y}[{out_label}]")
    return ";".join(parts)


def half_stacked_filter(
    spec: LayoutSpec,
    *,
    content_label: str = "0:v",
    avatar_label: str = "1:v",
    out_label: str = "vout",
) -> str:
    """FFmpeg filter_complex stacking content over presenter."""
    ch, ph = spec.content_height, spec.presenter_height
    return ";".join([
        f"[{content_label}]scale={spec.width}:{ch}:force_original_aspect_ratio=increase,"
        f"crop={spec.width}:{ch},setsar=1[top]",
        f"[{avatar_label}]scale={spec.width}:{ph}:force_original_aspect_ratio=increase,"
        f"crop={spec.width}:{ph},setsar=1[bot]",
        f"[top][bot]vstack=inputs=2[{out_label}]",
    ])


def composite(
    *,
    content: str,
    avatar: str,
    output: str,
    layout: LayoutName = "pip_circle",
    spec: Optional[LayoutSpec] = None,
    work_dir: str = "/tmp",
    crf: int = 17,
) -> str:
    """Composite one content clip with the presenter into a laid-out frame."""
    spec = spec or LayoutSpec(name=layout)
    inputs = ["-i", content, "-i", avatar]

    if layout == "pip_circle":
        d = spec.pip_diameter
        mask = _circle_mask(Path(work_dir) / f"_circmask_{d}.png", d)
        ringpng = _circle_ring(Path(work_dir) / f"_circring_{d}.png", d)
        inputs += ["-i", mask, "-i", ringpng]
        fc = pip_circle_filter(spec)
    elif layout == "half_stacked":
        fc = half_stacked_filter(spec)
    else:
        raise LayoutError(f"composite() does not handle layout {layout!r}")

    cmd = ["ffmpeg", "-v", "error", "-y", *inputs,
           "-filter_complex", fc, "-map", "[vout]",
           "-c:v", "libx264", "-crf", str(crf), "-pix_fmt", "yuv420p", "-an",
           output]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise LayoutError(f"ffmpeg failed for {layout}: {r.stderr[-800:]}")
    return output
