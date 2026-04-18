"""
B-roll type: browser_visit (mixed timeline)

Visits the article URL with a headless Playwright browser, captures key sections
as screenshots with their visible text, then asks Claude to plan a mixed b-roll
timeline where every segment is synced to what the voiceover is saying:

  browser        — viewport screenshot of the relevant article section (Ken Burns)
  stats_card     — animated number counter (when script mentions a specific metric)
  headline_burst — punchy text on cinematic gradient (surprising claims / hooks)

Each segment is rendered as a short clip and joined with crossfade transitions.
No looping — all content is unique and directly tied to the script.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .base import BrollBase, BrollError
from video_edit.video_editor import FFMPEG

if TYPE_CHECKING:
    from pipeline import VideoJob

logger = logging.getLogger(__name__)

# Viewport dimensions — half-screen slot in VideoEditor (OUTPUT_HEIGHT // 2)
_VIEWPORT_W = 1080
_VIEWPORT_H = 1920  # 9:16 portrait — matches final video output

# Non-article URL fragments (rejected immediately)
_NON_ARTICLE_FRAGMENTS = (
    "youtube.com/watch", "youtu.be",
    "twitter.com/", "x.com/",
    "github.com",
)

# Minimum word count for paywall detection
_MIN_WORD_COUNT = 200

# Seconds allocated per b-roll segment
_SEC_PER_SEGMENT = 3.5

# Maximum segments (avoids insane render times)
_MAX_SEGMENTS = 10

# Cross-fade duration between segments
_XFADE_DURATION = 0.35   # seconds

# Approximate speaking rate used for script timestamp estimation
_WORDS_PER_SEC = 2.5

# JavaScript injected before screenshots: hides non-article chrome
_HIDE_CLUTTER_JS = """
() => {
    const hide = [
        'footer', 'nav', 'header',
        '[class*="related"]', '[class*="recommended"]', '[class*="more-stories"]',
        '[class*="also-read"]', '[class*="you-may"]', '[class*="read-more"]',
        '[class*="newsletter"]', '[class*="subscribe"]', '[class*="signup"]',
        '[class*="cookie"]', '[class*="gdpr"]', '[class*="consent"]', '[class*="banner"]',
        '[class*=" ad-"]', '[class*="advertisement"]', '[id*="ad-"]', '[class*="promo"]',
        '[class*="sidebar"]', '[class*="widget"]', '[class*="aside"]',
        '[class*="social-share"]', '[class*="share-bar"]', '[class*="share-button"]',
        '[class*="comments"]', '[id*="comments"]',
        '[class*="popup"]', '[class*="modal"]', '[class*="overlay"]',
        '[class*="sticky"]', '[class*="fixed-"]',
        '[role="complementary"]', '[role="banner"]', '[role="navigation"]',
    ];
    const style = document.createElement('style');
    style.textContent = hide.map(s => `${s} { display: none !important; }`).join(' ');
    document.head.appendChild(style);
}
"""

# Finds interesting scroll positions scoped to the article body
_FIND_POSITIONS_JS = """
() => {
    const body_h = Math.max(
        document.body.scrollHeight,
        document.documentElement.scrollHeight,
        1
    );

    const articleSelectors = [
        'article', '[role="main"]', 'main',
        '.post-content', '.article-content', '.article-body',
        '.entry-content', '.story-body', '.article__body',
        '.post-body', '.content-body', '.article-text',
        '#article-body', '#story-content', '#post-content', '#article',
    ];

    let articleEl = null;
    for (const sel of articleSelectors) {
        const el = document.querySelector(sel);
        if (el) {
            const words = (el.innerText || '').trim().split(/\\s+/).length;
            if (words > 80) { articleEl = el; break; }
        }
    }

    let articleTopPx = 0;
    let articleBottomPx = body_h * 0.78;
    if (articleEl) {
        const rect = articleEl.getBoundingClientRect();
        articleTopPx    = Math.max(0, window.scrollY + rect.top);
        articleBottomPx = Math.min(body_h * 0.90, window.scrollY + rect.bottom);
    }

    const positions = [articleTopPx / body_h];

    const selectors = [
        'h2', 'h3', 'h4',
        'blockquote', 'figure',
        '[class*="highlight"]', '[class*="pullquote"]', '[class*="quote"]',
        '[class*="stat"]',
    ];

    const root = articleEl || document;
    for (const sel of selectors) {
        for (const el of root.querySelectorAll(sel)) {
            try {
                const rect = el.getBoundingClientRect();
                const absY = window.scrollY + rect.top;
                if (absY > articleTopPx + 80 && absY < articleBottomPx - 120) {
                    positions.push(absY / body_h);
                }
            } catch(e) {}
        }
    }

    positions.sort((a, b) => a - b);
    const deduped = [positions[0]];
    for (let i = 1; i < positions.length; i++) {
        if (positions[i] - deduped[deduped.length - 1] >= 0.06) {
            deduped.push(positions[i]);
        }
    }
    let article_left_px, article_right_px, article_width_px;
    if (articleEl) {
        const articleRect = articleEl.getBoundingClientRect();
        // Detect actual content column width from the widest text child,
        // not the container (which often has width:100% with inner padding).
        let maxChildW = 0;
        let minChildL = articleRect.right;
        for (const ch of articleEl.querySelectorAll('p, h1, h2, h3, h4, li, blockquote, pre, figure, img')) {
            const cr = ch.getBoundingClientRect();
            if (cr.width > 100 && cr.height > 10) {
                if (cr.width > maxChildW) maxChildW = cr.width;
                if (cr.left < minChildL) minChildL = cr.left;
            }
        }
        article_width_px = maxChildW > 100 ? maxChildW : articleRect.width;
        article_left_px  = maxChildW > 100 ? minChildL : articleRect.left;
        article_right_px = article_left_px + article_width_px;
    } else {
        article_left_px  = 0;
        article_right_px = window.innerWidth;
        article_width_px = window.innerWidth;
    }
    return {
        positions: deduped,
        body_h,
        article_bottom_pct: articleBottomPx / body_h,
        article_left_px,
        article_right_px,
        article_width_px,
    };
}
"""

# Extracts the text visible in the current viewport
_GET_VISIBLE_TEXT_JS = """
() => {
    const texts = [];
    const seen = new Set();
    const vh = window.innerHeight;
    for (const el of document.querySelectorAll('p, h1, h2, h3, h4, blockquote, li')) {
        const rect = el.getBoundingClientRect();
        if (rect.top >= -40 && rect.bottom <= vh + 40 && rect.width > 80) {
            const text = (el.innerText || '').trim().replace(/\\s+/g, ' ');
            const key = text.substring(0, 40);
            if (text.length > 20 && !seen.has(key)) {
                seen.add(key);
                texts.push(text.substring(0, 150));
            }
        }
    }
    return texts.slice(0, 5).join(' | ');
}
"""

# JavaScript to find article images and code blocks worth screenshotting
_EXTRACT_MEDIA_JS = """
() => {
    const media = [];

    // Find meaningful images (not icons/avatars)
    const imgSelectors = 'article img, main img, [role="main"] img, .post-content img, .article-content img, .entry-content img, .content img, figure img';
    for (const img of document.querySelectorAll(imgSelectors)) {
        const rect = img.getBoundingClientRect();
        const nat_w = img.naturalWidth || rect.width;
        const nat_h = img.naturalHeight || rect.height;
        if (nat_w >= 300 && nat_h >= 150 && rect.width >= 200) {
            media.push({
                type: 'image',
                bbox: {x: rect.x, y: rect.y + window.scrollY, w: rect.width, h: rect.height},
                src: img.src || '',
                alt: (img.alt || '').substring(0, 100),
            });
        }
    }

    // Find code blocks
    for (const el of document.querySelectorAll('pre, .highlight, .code-block')) {
        const rect = el.getBoundingClientRect();
        if (rect.width >= 200 && rect.height >= 80) {
            media.push({
                type: 'code',
                bbox: {x: rect.x, y: rect.y + window.scrollY, w: rect.width, h: rect.height},
            });
        }
    }

    // Deduplicate by vertical position
    const seen = new Set();
    return media.filter(m => {
        const key = Math.round(m.bbox.y / 50) + '_' + m.type;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
    }).slice(0, 8);
}
"""

# System prompt for the timeline planner
_TIMELINE_SYSTEM_PROMPT = """\
You are a social media video editor planning b-roll for a 60-second viral AI tech short.

You will receive:
1. The voiceover script divided into timed segments
2. Article sections with text visible at each scroll position

For each script segment choose the b-roll type:

  browser        — Full-screen website screenshot with cinematic Ken Burns animation.
                   Pick the scroll_pct whose article text is most relevant to what the
                   voiceover is saying at that moment.

Rules:
- Every segment must be browser type.
- Vary the scroll_pct across segments — show DIFFERENT parts of the article, not the same section.
- Match scroll_pct to the section whose visible text is most relevant to the voiceover at that moment.

EDITING RHYTHM RULES (2026 short-form standard):
- Cut every 2–4 seconds. Long static segments fail retention.
- Place a cut, image, or text card on every concrete proper-noun or numeric token in the script.
- Insert a "burst sequence" — 5–10 quick cuts within 3 seconds — approximately every 15 seconds as a retention reset.
- Use multiple short segments instead of fewer long ones.
- Target ~{target_duration_s} / 2.5 segments per video (so a 60 s video = ~24 segments).
"""

_TIMELINE_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["browser"],
                    },
                    # browser
                    "scroll_pct": {
                        "type": "number",
                        "description": "Scroll position 0.0-1.0 for browser type",
                    },
                    # stats_card
                    "numeric": {
                        "type": "number",
                        "description": "The bare number to animate",
                    },
                    "unit": {
                        "type": "string",
                        "description": "Text after the number, ≤12 chars (e.g. 'x faster', '%')",
                    },
                    "label": {
                        "type": "string",
                        "description": "Short description, ≤30 chars",
                    },
                    # headline_burst
                    "lines": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "1-2 punchy lines ≤6 words each",
                    },
                    # emphasis
                    "text": {
                        "type": "string",
                        "description": "Short transition phrase for emphasis type, 2-4 words (e.g. 'THE FIX', 'WHY IT MATTERS')",
                    },
                },
                "required": ["type"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["segments"],
    "additionalProperties": False,
}


class BrowserVisitGenerator(BrollBase):
    """
    Mixed-timeline article b-roll.

    Visits the article, captures key sections with screenshots + text snippets,
    then uses Claude to plan a timeline where each segment is synced to the
    voiceover — showing browser screenshots, animated stat counters, or punchy
    headline cards exactly when the script mentions the corresponding content.

    Raises:
        BrollError: For non-article URLs, paywalls, or FFmpeg failure.
    """

    def __init__(
        self,
        anthropic_client=None,
        width_override: int | None = None,
    ) -> None:
        """
        Args:
            anthropic_client: Optional AsyncAnthropic client used by the
                mixed-timeline planner.
            width_override: If provided, overrides the Playwright viewport
                width (and all downstream canvas width math) from the default
                ``_VIEWPORT_W``. Used by ``SplitScreenGenerator`` to render
                540 × 1920 half-width clips for hstack composition.
        """
        self._client = anthropic_client
        self._viewport_w = int(width_override) if width_override else _VIEWPORT_W

    async def generate(
        self,
        job: "VideoJob",
        target_duration_s: float,
        output_path: str,
    ) -> str:
        url: str = job.topic.get("url", "")
        self._check_non_article(url)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Fewer, longer segments = more distinct visuals and less freeze risk.
        # Aim for ~6-8s per segment rather than ~3s.
        n_segments = min(
            _MAX_SEGMENTS,
            max(4, int(target_duration_s / 7) + 1),
        )

        # Capture screenshots + visible text at each article section
        sections = await self._capture_sections(url, n_segments)
        if len(sections) < 2:
            raise BrollError(f"captured only {len(sections)} section(s) — need ≥ 2")

        # Plan the mixed timeline with Claude (falls back to uniform browser if no client)
        script_text = ""
        if hasattr(job, "script") and job.script:
            script_text = job.script.get("script", job.script.get("body", ""))

        if self._client and script_text:
            try:
                plan = await self._plan_timeline(
                    script_text, target_duration_s, sections, n_segments
                )
            except Exception as exc:
                logger.warning("Timeline planning failed (%s) — falling back to uniform browser", exc)
                plan = [{"type": "browser", "scroll_pct": s["scroll_pct"]} for s in sections[:n_segments]]
        else:
            plan = [{"type": "browser", "scroll_pct": s["scroll_pct"]} for s in sections[:n_segments]]

        logger.info(
            "BrowserVisitGenerator: %d segments planned (%s)",
            len(plan),
            ", ".join(s["type"] for s in plan),
        )

        # Each clip must be slightly longer to account for xfade overlap.
        # After xfading n clips, total = n * per_clip - (n-1) * XFADE = target
        # ⇒ per_clip = (target + (n-1) * XFADE) / n
        n = len(plan)
        per_segment_s = (target_duration_s + (n - 1) * _XFADE_DURATION) / n
        self._last_per_segment_s = per_segment_s

        tmp_dir = Path(tempfile.mkdtemp(prefix="bv_mixed_"))
        try:
            clip_paths = await self._render_all_segments(plan, sections, per_segment_s, tmp_dir, job)
            await self._encode_mixed_timeline(clip_paths, target_duration_s, output_path)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        logger.info(
            "BrowserVisitGenerator: %s saved (%d segments, %.1fs)",
            output_path, len(plan), target_duration_s,
        )
        return output_path

    # ─── Private helpers ──────────────────────────────────────────────────

    def _check_non_article(self, url: str) -> None:
        for frag in _NON_ARTICLE_FRAGMENTS:
            if frag in url:
                raise BrollError(f"non-article URL: {url!r} contains {frag!r}")

    async def _capture_sections(self, url: str, n_sections: int) -> list[dict]:
        """
        Visit the URL and capture {scroll_pct, screenshot_path, text} at
        interesting article positions.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise BrollError("playwright not installed")

        tmp_dir = Path(tempfile.mkdtemp(prefix="browser_"))
        sections: list[dict] = []

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(
                        viewport={"width": self._viewport_w, "height": _VIEWPORT_H}
                    )
                    await page.goto(url, wait_until="domcontentloaded", timeout=18000)

                    # Wait for JS rendering before checking content
                    try:
                        await page.wait_for_load_state("networkidle", timeout=8000)
                    except Exception:
                        # networkidle may never fire on ad-heavy pages; give JS 3s to render
                        await page.wait_for_timeout(3000)

                    # Paywall / empty-page check (after JS has rendered)
                    try:
                        body_text = await page.inner_text("body")
                        if len(body_text.split()) < _MIN_WORD_COUNT:
                            raise BrollError(
                                f"paywall or insufficient content: "
                                f"{len(body_text.split())} words < {_MIN_WORD_COUNT}"
                            )
                    except BrollError:
                        raise
                    except Exception:
                        pass

                    # Zoom content to fill viewport BEFORE hiding clutter (clutter
                    # hiding changes layout widths). Measure the widest content element
                    # so nothing gets cut off after zooming.
                    zoom_factor = 1.0
                    try:
                        max_content_w = await page.evaluate("""() => {
                            const article = document.querySelector('article') ||
                                            document.querySelector('[role="main"]') ||
                                            document.querySelector('main') ||
                                            document.body;
                            let maxW = 0;
                            for (const el of article.querySelectorAll('p, h1, h2, h3, h4, pre, blockquote, figure, img, table, figcaption')) {
                                const r = el.getBoundingClientRect();
                                if (r.width > 100 && r.height > 10 && r.width > maxW)
                                    maxW = r.width;
                            }
                            return Math.round(maxW || article.getBoundingClientRect().width);
                        }""")
                        if max_content_w > 100 and max_content_w < self._viewport_w * 0.90:
                            zoom_factor = (self._viewport_w * 0.95) / max_content_w
                            zoom_factor = min(zoom_factor, 1.4)  # nothing gets cut off
                            await page.evaluate(
                                f"document.documentElement.style.zoom = '{zoom_factor:.2f}'"
                            )
                            await asyncio.sleep(0.5)
                            # Recalculate positions after zoom
                            result = await page.evaluate(_FIND_POSITIONS_JS)
                            all_positions = result["positions"]
                            body_h = result["body_h"]
                            article_bottom_pct = result.get("article_bottom_pct", 0.78)
                            logger.info(
                                "BrowserVisit: zoomed page %.1fx (widest content was %dpx)",
                                zoom_factor, max_content_w,
                            )
                    except Exception as exc:
                        logger.debug("CSS zoom detection failed (non-fatal): %s", exc)
                        zoom_factor = 1.0

                    # Hide footer, nav, related articles, ads, cookie banners
                    try:
                        await page.evaluate(_HIDE_CLUTTER_JS)
                    except Exception:
                        pass

                    # Find scroll positions (after zoom + clutter hide)
                    result = await page.evaluate(_FIND_POSITIONS_JS)
                    all_positions = result["positions"]
                    body_h = result["body_h"]
                    article_bottom_pct = result.get("article_bottom_pct", 0.78)

                    selected = _select_positions(all_positions, n_sections, article_bottom_pct)

                    logger.debug(
                        "BrowserVisit: %d DOM positions → %d selected (article bottom %.0f%%) for %s",
                        len(all_positions), len(selected), article_bottom_pct * 100, url,
                    )

                    for i, pct in enumerate(selected):
                        scroll_y = int(body_h * pct)
                        await page.evaluate(f"window.scrollTo(0, {scroll_y})")
                        await asyncio.sleep(0.25)

                        png_path = tmp_dir / f"section_{i:03d}.png"
                        await page.screenshot(path=str(png_path))

                        # Extract visible text for Claude planning
                        try:
                            text = await page.evaluate(_GET_VISIBLE_TEXT_JS)
                        except Exception:
                            text = ""

                        sections.append({
                            "scroll_pct": pct,
                            "screenshot_path": png_path,
                            "text": text[:400],
                        })

                    # Extract article images and code blocks as dedicated b-roll
                    try:
                        media_items = await page.evaluate(_EXTRACT_MEDIA_JS)
                        for m_idx, item in enumerate(media_items or []):
                            bbox = item.get("bbox", {})
                            bx = int(bbox.get("x", 0))
                            by = int(bbox.get("y", 0))
                            bw = int(bbox.get("w", 0))
                            bh = int(bbox.get("h", 0))
                            if bw < 200 or bh < 100:
                                continue

                            # Scroll to the element and take a focused screenshot
                            await page.evaluate(f"window.scrollTo(0, {max(0, by - 100)})")
                            await asyncio.sleep(0.2)

                            media_path = tmp_dir / f"media_{m_idx:03d}.png"
                            # Screenshot the element's region at full width for 9:16
                            clip_y = min(100, _VIEWPORT_H - bh) if bh < _VIEWPORT_H else 0
                            await page.screenshot(
                                path=str(media_path),
                                clip={
                                    "x": max(0, bx - 20),
                                    "y": clip_y,
                                    "width": min(bw + 40, self._viewport_w),
                                    "height": min(bh + 200, _VIEWPORT_H),
                                },
                            )

                            scroll_pct = by / max(body_h, 1)
                            sections.append({
                                "scroll_pct": scroll_pct,
                                "screenshot_path": media_path,
                                "text": item.get("alt", item.get("type", "")),
                                "media_type": item.get("type", "image"),
                            })
                            logger.debug(
                                "BrowserVisit: extracted %s at y=%d (%dx%d)",
                                item.get("type"), by, bw, bh,
                            )
                    except Exception as exc:
                        logger.debug("Media extraction failed (non-fatal): %s", exc)

                finally:
                    await browser.close()

        except BrollError:
            raise
        except Exception as exc:
            raise BrollError(f"playwright error: {exc}") from exc

        return sections

    async def _plan_timeline(
        self,
        script_text: str,
        target_duration_s: float,
        sections: list[dict],
        n_segments: int,
    ) -> list[dict]:
        """Call Claude Haiku to plan the mixed b-roll timeline.

        Applies a 2026 editing-rhythm segment-count budget:
          - ``MAX_SEGMENTS_PER_VIDEO = max(8, int(target_duration_s / 1.5))``
            (e.g. 60 s → 40).
          - If Haiku returns more than ``MAX * 1.5`` segments, retry ONCE with a
            compaction prompt asking it to consolidate adjacent same-type segments.
          - If still over after retry, truncate from the end (the renderer will
            stop at ``target_duration_s`` anyway — existing behavior).
        """
        from anthropic import AsyncAnthropic  # noqa: F401 — import kept for callers

        # 2026 rhythm budget: target ~(target_duration_s / 2.5) segments, hard cap 1.5x that.
        max_segments_per_video = max(8, int(target_duration_s / 1.5))
        hard_cap = int(max_segments_per_video * 1.5)

        # Build timed script segments
        words = script_text.split()
        t_per_word = target_duration_s / max(len(words), 1)
        words_per_seg = max(1, len(words) // n_segments)

        script_segments: list[str] = []
        for i in range(n_segments):
            w0 = i * words_per_seg
            w1 = min((i + 1) * words_per_seg, len(words))
            t0 = w0 * t_per_word
            t1 = w1 * t_per_word
            chunk = " ".join(words[w0:w1])
            script_segments.append(f"[{t0:.1f}-{t1:.1f}s] {chunk}")

        # Build article sections summary
        sections_text = "\n".join(
            f"Section {i} (scroll {s['scroll_pct']:.0%}): {s['text'][:200]}"
            for i, s in enumerate(sections)
        )

        base_user_msg = (
            f"Script (estimated timestamps):\n"
            + "\n".join(script_segments)
            + f"\n\nArticle sections:\n{sections_text}"
            + f"\n\nPlan exactly {n_segments} b-roll segments to cover {target_duration_s:.1f} seconds."
        )

        async def _call_haiku(user_msg: str) -> list[dict]:
            response = await self._client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=1024,
                system=_TIMELINE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
                output_config={
                    "format": {"type": "json_schema", "schema": _TIMELINE_SCHEMA}
                },
            )
            data = json.loads(response.content[0].text)
            return list(data["segments"])

        # First call
        segments = await _call_haiku(base_user_msg)

        # Segment-count budget enforcement (counts raw len of Haiku's segments list
        # before validation/padding — that's the knob we can influence via retry).
        if len(segments) > hard_cap:
            logger.info(
                "Timeline planner: %d segments exceeds hard cap %d (max=%d); retrying with compaction prompt",
                len(segments), hard_cap, max_segments_per_video,
            )
            compaction_msg = (
                base_user_msg
                + "\n\n"
                + (
                    f"The previous plan exceeded the segment budget of "
                    f"{max_segments_per_video} segments. Consolidate adjacent "
                    f"same-type segments and return at most {max_segments_per_video}."
                )
            )
            segments = await _call_haiku(compaction_msg)

            if len(segments) > hard_cap:
                logger.warning(
                    "Timeline planner: compaction retry still returned %d segments (cap=%d) — truncating",
                    len(segments), hard_cap,
                )
                segments = segments[:hard_cap]

        # Validate and fix up segments
        valid: list[dict] = []
        for seg in segments:
            t = seg.get("type", "browser")
            if t == "browser":
                pct = seg.get("scroll_pct")
                if pct is None:
                    pct = sections[len(valid) % len(sections)]["scroll_pct"]
                entry: dict = {"type": "browser", "scroll_pct": float(pct)}
                if seg.get("overlay_text"):
                    entry["overlay_text"] = str(seg["overlay_text"])[:50]
                valid.append(entry)
            elif t == "stats_card":
                if seg.get("numeric") is not None:
                    valid.append({
                        "type": "stats_card",
                        "numeric": float(seg["numeric"]),
                        "unit": str(seg.get("unit", ""))[:12],
                        "label": str(seg.get("label", ""))[:30],
                    })
                else:
                    # Fall back to browser if stat data is missing
                    valid.append({"type": "browser", "scroll_pct": sections[len(valid) % len(sections)]["scroll_pct"]})
            elif t == "headline_burst":
                lines = seg.get("lines") or []
                if lines:
                    valid.append({"type": "headline_burst", "lines": [str(l)[:40] for l in lines[:2]]})
                else:
                    valid.append({"type": "browser", "scroll_pct": sections[len(valid) % len(sections)]["scroll_pct"]})
            elif t == "stock_video":
                valid.append({"type": "stock_video"})
            elif t == "emphasis":
                text = seg.get("text", "")
                if text:
                    valid.append({"type": "emphasis", "text": str(text)[:40]})
                else:
                    valid.append({"type": "browser", "scroll_pct": sections[len(valid) % len(sections)]["scroll_pct"]})
            else:
                valid.append({"type": "browser", "scroll_pct": sections[len(valid) % len(sections)]["scroll_pct"]})

        # If Haiku returned fewer segments than the caller-requested ``n_segments``
        # AND we're still under the rhythm budget, pad out. Otherwise honor
        # Haiku's higher count (capped by hard_cap, already applied above) so
        # that the 2026 rhythm rules can produce more cuts than ``n_segments``.
        if len(valid) < n_segments and len(valid) < max_segments_per_video:
            while len(valid) < n_segments and len(valid) < max_segments_per_video:
                idx = len(valid) % len(sections)
                valid.append({"type": "browser", "scroll_pct": sections[idx]["scroll_pct"]})

        return valid[:hard_cap]

    def _closest_section(self, sections: list[dict], scroll_pct: float) -> dict:
        """Return the captured section whose scroll_pct is closest to the target."""
        return min(sections, key=lambda s: abs(s["scroll_pct"] - scroll_pct))

    async def _render_all_segments(
        self,
        plan: list[dict],
        sections: list[dict],
        per_segment_s: float,
        tmp_dir: Path,
        job: "VideoJob | None" = None,
    ) -> list[Path]:
        """Render each planned segment to a short MP4 clip."""
        clips: list[Path] = []
        for idx, seg in enumerate(plan):
            clip_path = tmp_dir / f"clip_{idx:03d}.mp4"
            seg_tmp = tmp_dir / f"seg_{idx:03d}"
            seg_tmp.mkdir(exist_ok=True)

            t = seg["type"]
            if t == "browser":
                section = self._closest_section(sections, seg["scroll_pct"])
                await self._render_browser_clip(
                    section["screenshot_path"], per_segment_s, clip_path, idx,
                )
            elif t == "stats_card":
                from broll_gen.stats_card import render_single_stat_clip
                stat = {
                    "numeric": seg["numeric"],
                    "unit": seg["unit"],
                    "label": seg["label"],
                }
                await render_single_stat_clip(stat, per_segment_s, str(clip_path), seg_tmp)
            elif t == "headline_burst":
                from broll_gen.headline_burst import render_lines_clip
                await render_lines_clip(seg["lines"], per_segment_s, str(clip_path), seg_tmp)
            elif t == "emphasis":
                from broll_gen.emphasis_card import render_emphasis_clip
                await render_emphasis_clip(
                    seg.get("text", "..."),
                    per_segment_s,
                    str(clip_path),
                    seg_tmp,
                )
            elif t == "stock_video":
                import os
                from broll_gen.stock_video import StockVideoGenerator
                from broll_gen.headline_burst import render_lines_clip as _render_lines_clip
                pexels_key = os.environ.get("PEXELS_API_KEY", "")
                try:
                    stock_gen = StockVideoGenerator(pexels_api_key=pexels_key)
                    await stock_gen.generate(
                        job=job,
                        target_duration_s=per_segment_s,
                        output_path=str(clip_path),
                    )
                except Exception as exc:
                    logger.warning(
                        "stock_video segment %d failed (%s) — falling back to render_lines_clip",
                        idx, exc,
                    )
                    fallback_lines = seg.get("lines", [seg.get("text", "...")])
                    await _render_lines_clip(fallback_lines, per_segment_s, str(clip_path), seg_tmp)

            clips.append(clip_path)
        return clips

    async def _render_browser_clip(
        self,
        screenshot_path: Path,
        duration_s: float,
        output_path: Path,
        clip_idx: int,
    ) -> None:
        """Render a single browser screenshot as a Ken Burns zoompan clip."""
        fps = 30
        n_frames = max(1, int(fps * duration_s))

        # Ken Burns animations — very subtle to avoid clipping zoomed content.
        # When CSS zoom was applied, content is already near the edges so we
        # use near-zero zoom rates to prevent any text from being cut off.
        animations = [
            # 0: Barely perceptible zoom in, centered
            {"zoom": "zoom+0.0001",
             "x": "iw/2-(iw/zoom/2)", "y": "ih/2-(ih/zoom/2)"},
            # 1: Barely perceptible zoom out, centered
            {"zoom": "if(eq(on,1),1.015,zoom-0.0001)",
             "x": "iw/2-(iw/zoom/2)", "y": "ih/2-(ih/zoom/2)"},
            # 2: Very gentle downward drift, no zoom
            {"zoom": "1.005",
             "x": "iw/2-(iw/zoom/2)",
             "y": f"min(ih/2-(ih/zoom/2),on*{0.05*_VIEWPORT_H/max(n_frames,1):.4f})"},
            # 3: Static hold (no motion — gives variety by contrast)
            {"zoom": "1.0",
             "x": "0", "y": "0"},
        ]
        anim = animations[clip_idx % len(animations)]
        zoom_expr = anim["zoom"]
        pan_x = anim["x"]
        pan_y = anim["y"]

        vw = self._viewport_w
        filt = (
            f"scale={vw}:{_VIEWPORT_H}:force_original_aspect_ratio=increase,"
            f"crop={vw}:{_VIEWPORT_H},"
            f"zoompan=z='{zoom_expr}':x='{pan_x}':y='{pan_y}'"
            f":d={n_frames}:s={vw}x{_VIEWPORT_H}:fps={fps},"
            f"setpts=PTS-STARTPTS"
        )

        cmd = [
            FFMPEG, "-y",
            "-loop", "1", "-t", str(duration_s + 1.0), "-i", str(screenshot_path),
            "-vf", filt,
            "-t", str(duration_s),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(fps),
            str(output_path),
        ]
        try:
            await asyncio.to_thread(subprocess.run, cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise BrollError(
                f"ffmpeg browser clip failed: {e.stderr.decode(errors='replace')[:400]}"
            ) from e

    async def _encode_mixed_timeline(
        self,
        clip_paths: list[Path],
        target_duration_s: float,
        output_path: str,
    ) -> None:
        """Join all segment clips with xfade transitions."""
        n = len(clip_paths)
        if n == 0:
            raise BrollError("no clips to assemble")

        if n == 1:
            import shutil as _sh
            _sh.copy2(clip_paths[0], output_path)
            return

        # Build input list
        inputs: list[str] = []
        for p in clip_paths:
            inputs += ["-i", str(p)]

        # Each clip duration (already includes xfade compensation from generate())
        clip_dur = self._last_per_segment_s if hasattr(self, "_last_per_segment_s") else target_duration_s / n

        # Build xfade chain — offset is where each transition starts in the output timeline
        filter_parts: list[str] = []
        prev = "0:v"
        cumulative = clip_dur  # end of first clip
        for t_idx in range(1, n):
            offset = cumulative - _XFADE_DURATION
            out_label = f"xf{t_idx}" if t_idx < n - 1 else "vout"
            filter_parts.append(
                f"[{prev}][{t_idx}:v]"
                f"xfade=transition=fade:duration={_XFADE_DURATION:.2f}"
                f":offset={max(0.1, offset):.3f}"
                f"[{out_label}]"
            )
            prev = out_label
            cumulative = offset + clip_dur  # each new clip adds its full duration from the xfade point

        cmd = (
            [FFMPEG, "-y"]
            + inputs
            + [
                "-filter_complex", "; ".join(filter_parts),
                "-map", "[vout]",
                "-t", str(target_duration_s),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
                output_path,
            ]
        )

        try:
            await asyncio.to_thread(subprocess.run, cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise BrollError(
                f"ffmpeg xfade failed: {e.stderr.decode(errors='replace')[:600]}"
            ) from e


def _select_positions(
    positions: list[float], n: int, article_bottom_pct: float = 0.78
) -> list[float]:
    """
    Select exactly n positions from the found DOM positions, capped at the
    article bottom to avoid footer / related-articles content.
    """
    cap = article_bottom_pct
    positions = [p for p in positions if p <= cap]

    if not positions:
        return [i / max(n - 1, 1) * cap for i in range(n)]

    if len(positions) <= n:
        result = list(positions)
        max_pos = min(positions[-1], cap)
        step = max_pos / max(n - len(positions), 1)
        extra_pos = 0.0
        while len(result) < n:
            extra_pos += step
            candidate = round(min(extra_pos, cap), 3)
            if not any(abs(candidate - p) < 0.04 for p in result):
                result.append(candidate)
            if extra_pos >= cap:
                break
        return sorted(result)[:n]

    step = (len(positions) - 1) / (n - 1)
    return [positions[min(round(i * step), len(positions) - 1)] for i in range(n)]
