"""B-roll type: ``tweet_reveal`` — CommonCreed-branded tweet card (Unit B1).

Renders a vertical 1080x1920 tweet card on a navy matte with:
  * a white card (24 px rounded corners, 80% viewport width, vertically centered),
  * author block (initial-based avatar circle, bold navy name, gray @handle,
    optional sky-blue verified checkmark),
  * tweet body in 48 px Inter Regular navy,
  * like counter that animates from 0 to ``tweet_quote.like_count_estimate``
    over 1.5 s with a cubic ease-out curve,
  * a 0.4 s slide-up + fade-in intro on the card itself,
  * a static hold of the final card through ``target_duration_s``.

Render strategy
---------------
Follows the Unit A1 (``phone_highlight``) pattern:
  1. Build one Jinja-rendered HTML string per animation frame (counter value +
     slide / fade transform applied).
  2. Drive Playwright per frame → one PNG per frame.
  3. Concat the PNGs with an FFmpeg concat demuxer, adding a trailing hold
     frame to fill ``target_duration_s``, output at 30 fps.

The animation timeline uses 30 frames over 1.5 s = 20 fps of source steps;
FFmpeg up-samples to 30 fps on encode so the final clip matches the rest of
the pipeline.

Failure
-------
``job.tweet_quote`` must be populated upstream (by the topic-selection Haiku
call). Missing → ``BrollError("tweet_reveal requires job.tweet_quote")``.

All external services (Playwright, Jinja, FFmpeg) are mocked in the tests.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .base import BrollBase, BrollError

# Dual-import for branding tokens — primary (``scripts.`` prefix) works when
# the test runner or CLI is invoked from the repo root; the fallback handles
# the scripts/ CWD that ``scripts/pytest.ini`` configures.
try:
    from scripts.branding import NAVY, SKY_BLUE, WHITE  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — fallback when cwd is scripts/
    from branding import NAVY, SKY_BLUE, WHITE  # type: ignore[no-redef]

# FFmpeg path — same constant used by every other generator.
try:
    from scripts.video_edit.video_editor import FFMPEG  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — fallback when cwd is scripts/
    from video_edit.video_editor import FFMPEG  # type: ignore[no-redef]

if TYPE_CHECKING:  # pragma: no cover
    from commoncreed_pipeline import VideoJob


logger = logging.getLogger(__name__)


# ─── Constants ───────────────────────────────────────────────────────────────

_VIEWPORT_W = 1080
_VIEWPORT_H = 1920
_OUTPUT_FPS = 30  # Final encoded FPS (matches the rest of the pipeline).

# Animation timeline.
_ANIMATION_DURATION_S = 1.5
_ANIMATION_FRAMES = 30               # 30 frames across 1.5 s → 20 fps source.
_FRAME_STEP_S = _ANIMATION_DURATION_S / _ANIMATION_FRAMES  # 0.05 s / step.

# Slide-in + fade: both finish 0.4 s into the timeline.
_SLIDE_IN_DURATION_S = 0.40
_SLIDE_START_OFFSET_PX = 80  # Card starts 80 px below its settled position.

# Asset paths resolved once at import time.
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_TEMPLATE_PATH: Path = _PROJECT_ROOT / "assets" / "templates" / "tweet_card.html.j2"


# ─── Easing helpers ──────────────────────────────────────────────────────────


def _cubic_ease_out(t: float) -> float:
    """Cubic ease-out on ``t`` in ``[0, 1]`` → ``[0, 1]``.

    Classic ``1 - (1 - t)^3`` — fast start, smooth settle. Used for the like
    counter so the number "lands" rather than "creeps in".
    """
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return 1.0 - (1.0 - t) ** 3


def _frame_values(
    step: int,
    like_count_estimate: int,
) -> tuple[int, int, float]:
    """Return ``(like_count, translate_y_px, opacity)`` for ``step`` (0-indexed).

    ``step`` ranges from 0 (first frame) through ``_ANIMATION_FRAMES - 1``.
    """
    # Progress through the full 1.5 s animation (0 → 1.0 at the last step).
    max_step = _ANIMATION_FRAMES - 1
    progress = step / max_step if max_step > 0 else 1.0

    # Like counter: cubic ease-out of 0 → like_count_estimate.
    eased = _cubic_ease_out(progress)
    like_count = int(round(eased * max(0, int(like_count_estimate))))

    # Slide + fade: linear progress over the first 0.4 s of the 1.5 s timeline.
    elapsed = step * _FRAME_STEP_S
    slide_prog = min(1.0, elapsed / _SLIDE_IN_DURATION_S)
    translate_y = int(round((1.0 - slide_prog) * _SLIDE_START_OFFSET_PX))
    opacity = slide_prog  # 0 → 1 linear (settles at 0.4 s).

    return like_count, translate_y, opacity


# ─── Avatar initial ──────────────────────────────────────────────────────────


def _avatar_initial(author: str) -> str:
    """Pick a single uppercase letter for the avatar circle.

    First alphanumeric letter of the author string; falls back to ``"?"`` for
    empty or non-alphanumeric strings.
    """
    for ch in author:
        if ch.isalpha():
            return ch.upper()
    for ch in author:
        if ch.isalnum():
            return ch.upper()
    return "?"


# ─── Template rendering ──────────────────────────────────────────────────────


def _render_template(
    *,
    author: str,
    handle: str | None,
    body: str,
    verified: bool,
    like_count: int,
    card_translate_y: int,
    card_opacity: float,
    avatar_initial: str,
) -> str:
    """Render ``tweet_card.html.j2`` to a string.

    Jinja2 is imported lazily so the module remains importable when the
    package is missing. Tests monkey-patch this function at the module level.
    """
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
    except ImportError as exc:  # pragma: no cover — sidecar ships jinja2
        raise BrollError(f"jinja2 not installed: {exc}") from exc

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_PATH.parent)),
        autoescape=select_autoescape(["html", "xml", "j2"]),
    )
    template = env.get_template(_TEMPLATE_PATH.name)
    return template.render(
        author=author,
        handle=handle,
        body=body,
        verified=verified,
        like_count=like_count,
        card_translate_y=card_translate_y,
        card_opacity=card_opacity,
        avatar_initial=avatar_initial,
        brand_sky_blue=SKY_BLUE,
        brand_navy=NAVY,
        brand_white=WHITE,
    )


# ─── Playwright screenshots ──────────────────────────────────────────────────


async def _screenshot_html(html: str, output_path: Path) -> None:
    """Render ``html`` with Playwright and save a 1080x1920 PNG screenshot.

    Mirrors the lifecycle used in ``phone_highlight.py`` — ``async with
    async_playwright()`` per call, no browser pool. Tests patch this function
    at the module level so no real browser is launched.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover — mocked in tests
        raise BrollError(f"playwright not installed: {exc}") from exc

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H},
                device_scale_factor=1,
            )
            page = await context.new_page()
            await page.set_content(html, wait_until="domcontentloaded")
            await page.screenshot(
                path=str(output_path),
                full_page=False,
                clip={
                    "x": 0,
                    "y": 0,
                    "width": _VIEWPORT_W,
                    "height": _VIEWPORT_H,
                },
            )
        finally:
            await browser.close()


# ─── FFmpeg assembly ─────────────────────────────────────────────────────────


async def _assemble_video(
    png_paths: list[Path],
    target_duration_s: float,
    output_path: str,
) -> None:
    """Concat the animation PNGs + trailing hold frame, encode to MP4.

    Each of the first ``_ANIMATION_FRAMES`` PNGs is held for ``_FRAME_STEP_S``
    (50 ms) so the 30-frame animation plays over exactly 1.5 s. The last PNG
    is then repeated for ``max(0, target_duration_s - 1.5)`` additional
    seconds, so the generator returns a clip that is exactly
    ``target_duration_s`` long.
    """
    if not png_paths:
        raise BrollError("tweet_reveal: no PNG frames to assemble")

    tmp_dir = png_paths[0].parent
    concat_list = tmp_dir / "concat.txt"

    # Animation steps at 50 ms each.
    anim_total = len(png_paths) * _FRAME_STEP_S
    hold_s = max(0.0, float(target_duration_s) - anim_total)

    with concat_list.open("w", encoding="utf-8") as fh:
        for p in png_paths:
            fh.write(f"file '{p.as_posix()}'\nduration {_FRAME_STEP_S:.3f}\n")
        # Hold frame — render the final PNG for the remaining duration. Even
        # when hold_s is 0 we must emit a final `file` line so the concat
        # demuxer flushes the last frame (its quirky grammar).
        fh.write(f"file '{png_paths[-1].as_posix()}'\nduration {max(hold_s, 0.001):.3f}\n")
        fh.write(f"file '{png_paths[-1].as_posix()}'\n")

    cmd: list[str] = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-vf",
        f"scale={_VIEWPORT_W}:{_VIEWPORT_H}:force_original_aspect_ratio=cover,"
        f"crop={_VIEWPORT_W}:{_VIEWPORT_H},setsar=1,fps={_OUTPUT_FPS}",
        "-t", f"{float(target_duration_s):.2f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", str(_OUTPUT_FPS),
        output_path,
    ]

    try:
        await asyncio.to_thread(
            subprocess.run, cmd, check=True, capture_output=True
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace")[:500] if exc.stderr else ""
        raise BrollError(f"ffmpeg tweet_reveal failed: {stderr}") from exc


# ─── Quote validation ────────────────────────────────────────────────────────


def _validate_tweet_quote(tq: Any) -> dict:
    """Normalize ``tq`` → dict with the fields the template consumes.

    Raises ``BrollError`` when ``tq`` is missing required keys. Optional
    fields are filled with sensible defaults.
    """
    if tq is None:
        raise BrollError("tweet_reveal requires job.tweet_quote")
    if not isinstance(tq, dict):
        raise BrollError(
            "tweet_reveal requires job.tweet_quote to be a dict; "
            f"got {type(tq).__name__}"
        )
    author = str(tq.get("author") or "").strip()
    body = str(tq.get("body") or "").strip()
    if not author:
        raise BrollError("tweet_reveal: tweet_quote.author must be non-empty")
    if not body:
        raise BrollError("tweet_reveal: tweet_quote.body must be non-empty")

    handle_raw = tq.get("handle")
    if handle_raw is None:
        handle: str | None = None
    else:
        handle = re.sub(r"^@", "", str(handle_raw)).strip() or None

    try:
        like_count_estimate = int(tq.get("like_count_estimate") or 0)
    except (TypeError, ValueError):
        like_count_estimate = 0
    like_count_estimate = max(0, like_count_estimate)

    verified = bool(tq.get("verified", False))

    return {
        "author": author,
        "handle": handle,
        "body": body,
        "verified": verified,
        "like_count_estimate": like_count_estimate,
    }


# ─── Public generator ────────────────────────────────────────────────────────


class TweetRevealGenerator(BrollBase):
    """CommonCreed-branded tweet-card b-roll (Unit B1).

    Requires the upstream pipeline to have populated ``job.tweet_quote`` with
    ``{author, handle, body, like_count_estimate, verified}`` — the topic-
    selection Haiku step fills this when an article contains a direct quote
    attributed to a named person.

    This generator takes no external clients: Playwright is launched fresh per
    call, Jinja renders from an on-disk template, FFmpeg is invoked once at
    the end. The factory wires it with no kwargs — ``make_broll_generator
    ("tweet_reveal")``.
    """

    def __init__(self) -> None:
        # No constructor arguments — all rendering dependencies are module
        # globals (Playwright, Jinja, FFmpeg). This matches the split_screen
        # composer pattern.
        pass

    async def generate(
        self,
        job: "VideoJob",
        target_duration_s: float,
        output_path: str,
    ) -> str:
        tq = _validate_tweet_quote(getattr(job, "tweet_quote", None))

        avatar = _avatar_initial(tq["author"])

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix="tweet_reveal_"))
        png_paths: list[Path] = []
        try:
            for step in range(_ANIMATION_FRAMES):
                like_count, translate_y, opacity = _frame_values(
                    step, tq["like_count_estimate"]
                )
                html = _render_template(
                    author=tq["author"],
                    handle=tq["handle"],
                    body=tq["body"],
                    verified=tq["verified"],
                    like_count=like_count,
                    card_translate_y=translate_y,
                    card_opacity=opacity,
                    avatar_initial=avatar,
                )
                png_path = tmp_dir / f"tweet_{step:04d}.png"
                await _screenshot_html(html, png_path)
                png_paths.append(png_path)

            await _assemble_video(png_paths, float(target_duration_s), output_path)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        logger.info(
            "TweetRevealGenerator: wrote %s (author=%r, likes→%d, %.1fs)",
            output_path,
            tq["author"],
            tq["like_count_estimate"],
            float(target_duration_s),
        )
        return output_path
