"""
Meme pipeline: safe-fetch, normalize, credit overlay.

v0 scope — everything in one file intentionally. Split later when a
second source/path emerges that needs abstraction.

Three public entry points:

    safe_fetch(url, out_path, max_bytes, allowed_mime)
        Downloads a URL to a local file with SSRF protections. Rejects
        any URL whose hostname resolves to a private/loopback/link-local
        address. Enforces size and mime-type limits. Raises
        MemePipelineError on any rejection or failure.

    normalize_media(input_path, out_path, media_type)
        For videos: re-encodes to H.264 + AAC at 1080x1920 (9:16),
        trimmed to 30s, cropped/padded as needed.
        For images: re-encodes to a 1080x1920 JPEG with optional
        letterboxing on white. No overlay applied here — that's
        the next step.

    apply_credit_overlay(input_path, out_path, author_handle, source_name, media_type)
        Burns "via {author_handle} · {source_name}" into the top-left
        of the canvas, using the bundled Inter-Black font. For video,
        uses ffmpeg drawtext. For image, uses PIL.

All three are blocking — no asyncio. Callers wrap in
`asyncio.to_thread` when needed. Each raises MemePipelineError on
failure; none silently returns a partial result.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class MemePipelineError(RuntimeError):
    pass


# -------------------------------------------------------------------------
# safe_fetch
# -------------------------------------------------------------------------

_DEFAULT_ALLOWED_MIME = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "video/mp4",
    "video/quicktime",
    "video/webm",
}


def _is_private_address(host: str) -> bool:
    """Resolve host and reject RFC1918 / loopback / link-local / multicast."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise MemePipelineError(f"dns resolution failed for {host}: {exc}")

    for family, _type, _proto, _canon, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True
    return False


def safe_fetch(
    url: str,
    out_path: Path,
    max_bytes: int = 60 * 1024 * 1024,  # 60 MB
    allowed_mime: Optional[set[str]] = None,
    timeout_seconds: float = 30.0,
) -> str:
    """Download ``url`` to ``out_path``, return the resolved content-type.

    Raises MemePipelineError on any policy violation or network failure.
    """
    try:
        import httpx
    except ImportError as exc:
        raise MemePipelineError(f"httpx missing: {exc}")

    allowed = allowed_mime or _DEFAULT_ALLOWED_MIME

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise MemePipelineError(f"unsupported scheme: {parsed.scheme}")
    host = parsed.hostname or ""
    if not host:
        raise MemePipelineError(f"no host in url: {url}")
    if _is_private_address(host):
        raise MemePipelineError(f"host {host} resolves to a private address")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "CommonCreedBot/0.1 (meme curator)"},
        ) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise MemePipelineError(
                        f"http {resp.status_code} fetching {url}"
                    )
                content_type = (
                    resp.headers.get("content-type", "").split(";")[0].strip().lower()
                )
                if content_type not in allowed:
                    raise MemePipelineError(
                        f"content-type {content_type!r} not in allowlist"
                    )
                content_length = resp.headers.get("content-length")
                if content_length is not None:
                    try:
                        declared = int(content_length)
                    except ValueError:
                        declared = 0
                    if declared > max_bytes:
                        raise MemePipelineError(
                            f"content-length {declared} exceeds max {max_bytes}"
                        )
                downloaded = 0
                with open(out_path, "wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        downloaded += len(chunk)
                        if downloaded > max_bytes:
                            fh.close()
                            out_path.unlink(missing_ok=True)
                            raise MemePipelineError(
                                f"download exceeded max {max_bytes} bytes"
                            )
                        fh.write(chunk)
    except MemePipelineError:
        raise
    except Exception as exc:
        raise MemePipelineError(f"network error fetching {url}: {exc}")

    logger.info(
        "safe_fetch: %s -> %s (%d bytes, %s)",
        url,
        out_path,
        out_path.stat().st_size,
        content_type,
    )
    return content_type


# -------------------------------------------------------------------------
# normalize_media
# -------------------------------------------------------------------------

_CANVAS_W = 1080
_CANVAS_H = 1920
_MAX_DURATION_SEC = 30
_FONT_PATH = "/app/assets/fonts/Inter-Black.ttf"


def _run_ffmpeg(args: list[str], timeout: int = 180) -> None:
    """Run ffmpeg with a hard timeout, surfacing stderr on failure."""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            timeout=timeout,
            check=False,
            start_new_session=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise MemePipelineError(f"ffmpeg timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise MemePipelineError(
            f"ffmpeg rc={proc.returncode}: {proc.stderr.decode('utf-8', 'replace')[-800:]}"
        )


def mux_video_audio(video_path: Path, audio_path: Path, out_path: Path) -> None:
    """Merge a silent video stream with a separate audio stream (Reddit DASH).

    Uses ffmpeg -c copy so no re-encode — fast and lossless. If the audio is
    shorter/longer than the video, ffmpeg just trims to the shorter duration.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "128k",
            "-shortest",
            "-movflags", "+faststart",
            str(out_path),
        ]
    )


_IG_POST_W = 1080
_IG_POST_H = 1350  # 4:5 — Instagram's max portrait ratio for feed posts
_CORNER_RADIUS = 40  # rounded corners for aesthetic padding
_BORDER_PX = 32      # minimum white border on all sides


def _normalize_image_for_ig(input_path: Path, out_path: Path) -> None:
    """Fit an image to Instagram's 4:5 feed ratio with white padding, border, and rounded corners.

    The meme is scaled to fit inside a 1080×1350 canvas with a guaranteed
    white border on all sides, plus rounded corners for a polished look.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise MemePipelineError(f"Pillow missing: {exc}")

    img = Image.open(input_path).convert("RGBA")
    orig_w, orig_h = img.size

    # Step 1: Scale to fit inside the canvas minus the border on each side
    max_w = _IG_POST_W - _BORDER_PX * 2
    max_h = _IG_POST_H - _BORDER_PX * 2
    scale = min(max_w / orig_w, max_h / orig_h)
    new_w = int(orig_w * scale)
    new_h = int(orig_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Step 2: Apply rounded corners to the meme image
    if _CORNER_RADIUS > 0:
        corner_mask = Image.new("L", (new_w, new_h), 0)
        draw = ImageDraw.Draw(corner_mask)
        draw.rounded_rectangle(
            [(0, 0), (new_w - 1, new_h - 1)],
            radius=_CORNER_RADIUS,
            fill=255,
        )
        img.putalpha(corner_mask)

    # Step 3: Create white canvas at 4:5 and center the image
    canvas = Image.new("RGBA", (_IG_POST_W, _IG_POST_H), (255, 255, 255, 255))
    x = (_IG_POST_W - new_w) // 2
    y = (_IG_POST_H - new_h) // 2
    canvas.paste(img, (x, y), img)

    # Step 4: Save as JPEG
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, "JPEG", quality=92)


def normalize_media(input_path: Path, out_path: Path, media_type: str) -> None:
    """Re-encode to 1080x1920 9:16 mp4 (video/gif) or jpg (image)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if media_type == "image":
        _normalize_image_for_ig(input_path, out_path)
        return

    # video or gif -> mp4
    _run_ffmpeg(
        [
            "ffmpeg", "-y", "-i", str(input_path),
            "-t", str(_MAX_DURATION_SEC),
            "-vf",
            (
                f"scale={_CANVAS_W}:{_CANVAS_H}:force_original_aspect_ratio=decrease,"
                f"pad={_CANVAS_W}:{_CANVAS_H}:(ow-iw)/2:(oh-ih)/2:black"
            ),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out_path),
        ]
    )


# -------------------------------------------------------------------------
# apply_credit_overlay
# -------------------------------------------------------------------------


def _sanitize_for_drawtext(text: str) -> str:
    """Escape characters that break ffmpeg drawtext filter syntax."""
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("%", "\\%")
    )


def apply_credit_overlay(
    input_path: Path,
    out_path: Path,
    author_handle: str,
    source_name: str,
    media_type: str,
) -> None:
    """Apply the bottom-right CommonCreed watermark.

    The top-left burned-in credit was removed at the owner's request — credit
    attribution lives in the caption template (caller responsibility) and the
    visual brand mark stays clean. ``author_handle`` is still required as a
    safety gate so the caller can't accidentally publish without one.
    """
    if not author_handle:
        raise MemePipelineError("cannot overlay without an author_handle (R12 gate)")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if media_type == "image":
        _apply_watermark_image_pil(input_path, out_path)
        return

    # Video path: render the CommonCreed watermark as a transparent PNG once,
    # then ffmpeg-overlay it onto the bottom-right of every frame.
    watermark_png = out_path.parent / "_commoncreed_watermark.png"
    _render_commoncreed_watermark(watermark_png)

    _run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-i", str(watermark_png),
            "-filter_complex", "[0:v][1:v]overlay=W-w-32:H-h-32[out]",
            "-map", "[out]",
            "-map", "0:a?",  # copy audio if present
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "copy",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(out_path),
        ]
    )


# -------------------------------------------------------------------------
# CommonCreed two-tone watermark — bottom-right brand mark
# -------------------------------------------------------------------------

# Brand colours pulled to match the owner's existing CommonCreed brand:
# pastel blue + warm slate grey, blue-and-grey palette only. Soft enough
# to feel like a brand mark, dark enough to read over white meme backgrounds.
_WATERMARK_COMMON_FILL = (74, 122, 200)   # muted pastel blue
_WATERMARK_CREED_FILL = (122, 138, 158)   # warm slate grey
_WATERMARK_OUTLINE = (255, 255, 255)      # white outline for legibility on busy backgrounds
_WATERMARK_FONT_SIZE = 56


def _render_commoncreed_watermark(out_path: Path) -> None:
    """Render the two-tone CommonCreed brand mark as a transparent PNG.

    Used by apply_credit_overlay for both the image and video paths.
    Cached on disk per call site (callers pass a per-output dir path).
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise MemePipelineError(f"Pillow missing: {exc}")

    try:
        font = ImageFont.truetype(_FONT_PATH, _WATERMARK_FONT_SIZE)
    except Exception:
        font = ImageFont.load_default()

    # Measure each half so we can size the canvas tightly
    tmp_canvas = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    tmp_draw = ImageDraw.Draw(tmp_canvas)
    common_bbox = tmp_draw.textbbox((0, 0), "Common", font=font)
    creed_bbox = tmp_draw.textbbox((0, 0), "Creed", font=font)
    common_w = common_bbox[2] - common_bbox[0]
    common_h = common_bbox[3] - common_bbox[1]
    creed_w = creed_bbox[2] - creed_bbox[0]
    creed_h = creed_bbox[3] - creed_bbox[1]

    pad = 12  # outline + breathing room
    total_w = common_w + creed_w + pad * 2
    total_h = max(common_h, creed_h) + pad * 2

    canvas = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # "Common" half — deep blue with white outline
    draw.text(
        (pad - common_bbox[0], pad - common_bbox[1]),
        "Common",
        font=font,
        fill=_WATERMARK_COMMON_FILL,
        stroke_width=3,
        stroke_fill=_WATERMARK_OUTLINE,
    )
    # "Creed" half — red, butted up against "Common" with no space
    draw.text(
        (pad + common_w - creed_bbox[0], pad - creed_bbox[1]),
        "Creed",
        font=font,
        fill=_WATERMARK_CREED_FILL,
        stroke_width=3,
        stroke_fill=_WATERMARK_OUTLINE,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "PNG")


def _apply_watermark_image_pil(input_path: Path, out_path: Path) -> None:
    """PIL-based bottom-right CommonCreed watermark for static images."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise MemePipelineError(f"Pillow missing: {exc}")

    try:
        img = Image.open(input_path).convert("RGBA")
    except Exception as exc:
        raise MemePipelineError(f"cannot open image {input_path}: {exc}")

    watermark_png = out_path.parent / "_commoncreed_watermark.png"
    _render_commoncreed_watermark(watermark_png)
    try:
        wm = Image.open(watermark_png).convert("RGBA")
    except Exception as exc:
        raise MemePipelineError(f"cannot open watermark png: {exc}")

    wm_pad = 32
    wm_x = img.width - wm.width - wm_pad
    wm_y = img.height - wm.height - wm_pad
    img.paste(wm, (wm_x, wm_y), wm)  # alpha channel as mask
    img.convert("RGB").save(out_path, "JPEG", quality=92)
