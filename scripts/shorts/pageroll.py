"""Page-roll b-roll: footage made from the source page itself.

Generic stock footage hurts a story — strangers in a coworking space, dropped
into a piece about a repository, tell the viewer nothing. The source page is
both more relevant and more interesting to look at.

Two things make this work rather than merely function:

REGION DETECTION, not blind cropping. A first version scaled the page to panel
width and cropped the centre. Measured against a real GitHub capture, that
discarded 606px of content from the left, because the page is laid out edge to
edge rather than as a centred column. This version finds actual content blocks
— contiguous bands of non-background pixels — and fits each one to the panel,
so a region is shown whole instead of sliced.

SCRIPT ALIGNMENT, not arbitrary order. Regions are returned with their bounds
so a caller can match them to the narration beat they illustrate. Showing the
commit list while the narration explains the file format is as disconnected as
stock footage.

Requires Chrome on the rendering host. Falls back cleanly: on failure the
caller gets an empty list and the pipeline proceeds without page-roll.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

RollKind = Literal["scroll", "hold"]


class PageRollError(RuntimeError):
    """Raised when a page cannot be captured or rendered."""


@dataclass
class Region:
    """A coherent block of page content."""
    top: int
    bottom: int
    left: int
    right: int
    density: float          # fraction of pixels differing from background
    index: int = 0

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def width(self) -> int:
        return self.right - self.left


@dataclass
class RollClip:
    path: str
    kind: RollKind
    duration: float
    source_url: str
    region: str = ""
    region_index: int = 0


def _chrome_binary() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    raise PageRollError("no Chrome/Chromium on PATH")


def capture_page(url: str, out_png: str, *, width: int = 1280,
                 max_height: int = 12000, timeout_s: int = 180,
                 dark: bool = True, attempts: int = 2,
                 reuse: bool = True) -> str:
    """Full-page screenshot at DPR 2.

    Retries once: headless Chrome occasionally hangs on a slow third-party
    asset and a second run usually lands. An existing capture is reused rather
    than re-fetched, which also keeps re-runs of later stages cheap.
    """
    if reuse and os.path.exists(out_png) and os.path.getsize(out_png) > 0:
        logger.info("Reusing existing capture %s", out_png)
        return out_png
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _capture_once(url, out_png, width=width,
                                 max_height=max_height, timeout_s=timeout_s,
                                 dark=dark)
        except (PageRollError, subprocess.TimeoutExpired) as exc:
            last = exc
            logger.warning("capture attempt %d/%d failed: %s",
                           attempt, attempts, str(exc)[:160])
    raise PageRollError(f"capture failed after {attempts} attempts: {last}")


def _capture_once(url: str, out_png: str, *, width: int,
                  max_height: int, timeout_s: int, dark: bool) -> str:
    chrome = _chrome_binary()
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    # --user-data-dir and --disable-dev-shm-usage are not optional headless:
    # without them Chrome hangs indefinitely rather than erroring.
    profile = Path(out_png).parent / "_chrome_profile"
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
        "--disable-dev-shm-usage", "--no-first-run", "--no-default-browser-check",
        f"--user-data-dir={profile}",
        "--hide-scrollbars", "--force-device-scale-factor=2",
        f"--window-size={width},{min(max_height, 3000)}",
        "--screenshot=" + out_png,
        "--virtual-time-budget=8000",
    ]
    if dark:
        cmd += ["--force-dark-mode", "--enable-features=WebContentsForceDark"]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    if not os.path.exists(out_png) or os.path.getsize(out_png) == 0:
        raise PageRollError(f"no screenshot for {url}: {r.stderr[-300:]}")
    logger.info("Captured %s (%d KB)", url, os.path.getsize(out_png) // 1024)
    return out_png


_READER_JS = """
() => {
  const textLen = (el) => {
    let n = 0;
    for (const p of el.querySelectorAll('p, li, h2, h3, pre, code')) {
      n += (p.innerText || '').trim().length;
    }
    return n;
  };

  // ANCHOR ON THE HEADLINE, then walk up to the block that contains the story.
  //
  // Picking the container with the most paragraph text instead captured the
  // WRONG ARTICLE: a TechCrunch page embeds a full podcast transcript, which is
  // longer than the piece itself, so "most text wins" produced a clean capture
  // of an unrelated Zuckerberg interview. The headline is the one element
  // guaranteed to belong to the story the URL is about.
  // Take the SMALLEST ancestor that holds the body, not the largest. Climbing
  // to the maximum re-absorbed the podcast transcript as a sibling: 13,743
  // chars against the article's 8,004, and a 19,000px capture. The first
  // ancestor to clear the threshold is the article container; everything above
  // it is the page.
  const ENOUGH = 2500;
  const h1 = document.querySelector('article h1, main h1, h1');
  let best = null, bestLen = 0;
  if (h1) {
    let node = h1.parentElement, depth = 0;
    while (node && depth < 8 && node !== document.body) {
      const n = textLen(node);
      if (n > bestLen) { bestLen = n; best = node; }
      if (n >= ENOUGH) break;
      node = node.parentElement; depth++;
    }
  }
  // Only if there is no usable headline do we fall back to the selector sweep.
  if (!best || bestLen < 600) {
    for (const el of document.querySelectorAll(
        'article, [itemprop="articleBody"], [class*="article-content"], '
        + '[class*="article-body"], [class*="entry-content"], '
        + '[class*="post-content"], [class*="story-body"], main, [role="main"]')) {
      const n = textLen(el);
      if (n > bestLen) { bestLen = n; best = el; }
    }
  }
  if (!best || bestLen < 400) return null;

  // Strip page furniture LAST, and only from inside the chosen root. Removing
  // it first deleted the article on pages whose body class happens to match a
  // junk pattern, leaving whatever survived to be selected instead.
  const junk = [
    'iframe', 'ins', 'aside', 'nav', 'footer', 'form', 'video',
    '[class*="ad-"]', '[class*="-ad"]', '[class*="ads"]', '[id*="ad-"]',
    '[id*="google_ads"]', '[class*="advert"]', '[aria-label*="advert" i]',
    '[class*="sponsor"]', '[class*="promo"]', '[class*="newsletter"]',
    '[class*="subscribe"]', '[class*="related"]', '[class*="popular"]',
    '[class*="recommend"]', '[class*="social"]', '[class*="share"]',
    '[class*="comment"]', '[class*="paywall"]', '[class*="cookie"]',
    '[data-testid*="ad"]',
  ];
  for (const sel of junk) {
    for (const el of best.querySelectorAll(sel)) el.remove();
  }
  // Widen the column: a 700px measure inside a 1280px viewport leaves the
  // capture half empty, and the panel then shows mostly margin.
  best.style.margin = '0 auto';
  best.style.maxWidth = 'none';
  best.style.width = '100%';
  best.style.padding = '28px 34px';
  best.setAttribute('data-reader-root', '1');
  const r = best.getBoundingClientRect();
  return {
    h: Math.round(r.height),
    chars: textLen(best),
    headline: (h1 ? (h1.innerText || '') : '').trim().slice(0, 90),
  };
}
"""


def capture_article(url: str, out_png: str, *, width: int = 1280,
                    timeout_ms: int = 45000, reuse: bool = True) -> str:
    """Capture ONLY the article body, with page furniture removed.

    The plain full-page capture is the whole document, and on a news site most
    of the document is not the story. Measured on the TechCrunch capture used
    for the X ranking-algorithm short, the panel spent several seconds on an
    Oracle advert, a "Most Popular" rail and a podcast promo carrying a stock
    headshot of someone with no connection to the piece — the same irrelevant
    footage that keyword stock search was dropped for. It recurred because the
    drift revisits the same tall image.

    Returns a tall PNG of the story text alone, which is both relevant and the
    only version whose body text is readable once zoomed into a panel.
    """
    if reuse and os.path.exists(out_png) and os.path.getsize(out_png) > 0:
        logger.info("Reusing existing article capture %s", out_png)
        return out_png

    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    profile = Path(out_png).parent / "_reader_profile"
    profile.mkdir(parents=True, exist_ok=True)
    script = f'''
import json, sys
from playwright.sync_api import sync_playwright

url, out, width, profile = sys.argv[1:5]
width = int(width)
with sync_playwright() as p:
    b = p.chromium.launch_persistent_context(
        profile,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars",
              "--force-dark-mode", "--enable-features=WebContentsForceDark"],
        viewport={{"width": width, "height": 1400}}, device_scale_factor=2,
        color_scheme="dark")
    pg = b.pages[0] if b.pages else b.new_page()
    # domcontentloaded, not networkidle: ads and analytics keep a news site's
    # network busy forever, so networkidle times out on a page that rendered
    # in two seconds.
    pg.goto(url, wait_until="domcontentloaded", timeout={timeout_ms})
    pg.wait_for_timeout(2500)
    pg.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    pg.wait_for_timeout(1500)
    pg.evaluate("() => window.scrollTo(0, 0)")
    pg.wait_for_timeout(500)
    info = pg.evaluate({_READER_JS!r})
    if not info:
        print("NOROOT"); b.close(); sys.exit(3)
    el = pg.query_selector("[data-reader-root]")
    if el is None:
        print("NOROOT"); b.close(); sys.exit(3)
    el.screenshot(path=out)
    print("OK", json.dumps(info))
    b.close()
'''
    r = subprocess.run(["python3", "-c", script, url, out_png, str(width),
                        str(profile)],
                       capture_output=True, text=True,
                       timeout=timeout_ms / 1000 + 120)
    if "NOROOT" in (r.stdout or ""):
        raise PageRollError(f"no article body found on {url}")
    if not os.path.exists(out_png) or os.path.getsize(out_png) == 0:
        raise PageRollError(
            f"article capture failed for {url}: "
            f"{(r.stderr or r.stdout or '')[-300:]}")
    logger.info("Article capture %s (%d KB) %s", url,
                os.path.getsize(out_png) // 1024,
                (r.stdout or "").strip()[:80])
    return out_png


_READER_CSS = """
:root { color-scheme: dark; }
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  width: 1080px; background: %(bg)s; color: %(fg)s;
  font-family: Inter, -apple-system, "Segoe UI", Roboto, sans-serif;
  padding: 54px 62px 80px;
}
.kicker {
  font-size: 24px; font-weight: 700; letter-spacing: .16em;
  text-transform: uppercase; color: %(accent)s; margin-bottom: 20px;
}
h1 {
  font-size: 62px; line-height: 1.12; font-weight: 800;
  letter-spacing: -.015em; margin-bottom: 26px;
}
.rule { width: 168px; height: 9px; border-radius: 5px;
        background: %(accent)s; margin-bottom: 42px; }
p {
  font-size: 37px; line-height: 1.58; margin-bottom: 34px;
  color: %(fg)s;
}
p.lead { font-size: 41px; font-weight: 600; }
em { color: %(accent)s; font-style: normal; font-weight: 700; }
"""


_BOILER_PATTERNS = [
    # "Image Credits: TechCrunch Social", "Image Credits: GitHub screenshot" —
    # a caption for an image that is not in the reader column at all.
    re.compile(r"Image Credits?:\s*(?:\S+\s*){0,4}", re.I),
    # "9:00 AM PDT · August 13, 2026" and the byline that precedes it.
    re.compile(r"\b\d{1,2}:\d{2}\s*[AP]M\s+[A-Z]{2,4}\s*[·|-]\s*"
               r"\w+\s+\d{1,2},\s*\d{4}", re.I),
    re.compile(r"\b\d{1,2}\s+(?:minute|hour|day)s?\s+ago\b", re.I),
    # Trailing site attribution on a scraped <title>.
    re.compile(r"\s*\|\s*(?:TechCrunch|The Verge|Reuters|Bloomberg|CNBC|"
               r"Wired|Ars Technica|Engadget)\b", re.I),
    re.compile(r"\b(?:Advertisement|Sponsored|Related Posts?|Most Popular|"
               r"Sign up for|Subscribe to|Read more:)\b.*?(?=\.|$)", re.I),
]


# Promotional copy that publishers inline INTO the article body.
#
# The reader page is built from the scraped text, so an ad inside that text
# renders as if it were the story: a build put "Flash Sale - Get $100 off your
# Disrupt 2026 ticket ... REGISTER NOW." on screen in the owner's video. These
# are matched per-sentence rather than per-line because the ad arrives mid
# paragraph, and they are deliberately specific — a broad "money words" filter
# would eat real reporting about pricing, funding or revenue.
_PROMO_RE = re.compile(
    r"(flash sale|register now|save \$\d|\$\d+\s*off\b|get \$\d+\s*off"
    r"|early bird|use code\b|promo code|limited time offer"
    r"|subscribe (?:now|today)|sign up (?:now|today)|newsletter"
    r"|book your (?:seat|ticket)|buy (?:your )?tickets?\b"
    r"|disrupt \d{4} ticket)",
    re.I,
)


def _drop_promos(text: str) -> tuple:
    """Remove sentences that are advertising, not reporting.

    Returns (cleaned_text, dropped_count).
    """
    kept, dropped = [], 0
    for para in text.split("\n"):
        sentences = re.split(r"(?<=[.!?])\s+", para)
        good = [x for x in sentences if not _PROMO_RE.search(x)]
        dropped += len(sentences) - len(good)
        kept.append(" ".join(good))
    return "\n".join(kept), dropped


def _strip_boilerplate(text: str, title: str) -> str:
    """Remove scraper leftovers so the lead paragraph reads as prose.

    The extracted text carries the page's furniture inline: the headline
    repeated, the site name, the byline, the timestamp and image captions. All of
    it landed in the FIRST paragraph, which the reader page sets largest and
    boldest — so the most prominent text in the panel read
    "... | TechCrunch Image Credits: TechCrunch Social X open sources its
    ranking algorithm ... 9:00 AM PDT · August 13, 2026 X is significantly
    expanding ...".
    """
    text, promos = _drop_promos(text)
    if promos:
        logger.info("Reader page: dropped %d promotional sentence(s)", promos)
    for pat in _BOILER_PATTERNS:
        text = pat.sub(" ", text)
    # Drop the LEAD-IN metadata structurally rather than by matching the title.
    #
    # Matching the title does not work: the title here is the one the script
    # generated ("X Just Open Sourced The Algorithm That 'Shadowbans' You")
    # while the scrape carries the publisher's ("X open sources its ranking
    # algorithm, letting users see if they've been 'shadowbanned'"), twice, in
    # both straight and curly quotes, followed by a byline. Exact matching
    # removed none of it and prefix matching sliced one copy in half.
    #
    # What the lead-in reliably IS: a run of short lines that are not prose. A
    # real body paragraph is long and ends in a sentence terminator. So skip
    # forward to the first line that looks like prose and start there.
    lines = [ln.strip() for ln in text.splitlines()]
    start = 0
    # Scan 24 lines, not 8. A real scrape's lead-in is longer than it looks:
    # headline, a timer widget rendered as "-:-:-:-", a stray "Close"
    # button label, blank lines, the duplicated headline and the byline all
    # arrive before the first sentence of prose.
    for idx, ln in enumerate(lines[:24]):
        if len(ln) >= 160 and ln.rstrip().endswith((".", "”", '"', "!", "?")):
            start = idx
            break
    if start:
        dropped = " / ".join(x for x in lines[:start] if x)[:110]
        logger.info("Reader page: dropped %d lead-in line(s): %s",
                    start, dropped)
        text = "\n".join(lines[start:])
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def build_reader_png(*, title: str, text: str, out_png: str,
                     kicker: str = "SOURCE", palette: Optional[list] = None,
                     max_paragraphs: int = 14, timeout_s: int = 120) -> str:
    """Render the source text as a clean, readable column and screenshot it.

    Why not screenshot the publisher's page for this: the panel behind a
    presenter-led span is a BED, and a live news page is a poor one. The real
    capture put an Oracle advert, a "Most Popular" rail and a podcast promo
    carrying an unrelated stock headshot into the video, and removing them in
    the DOM proved unreliable — on the TechCrunch page an embedded podcast
    transcript sits inside the same wrapper as the article, directly above the
    headline, so no amount of ancestor-walking separates them. Two attempts
    produced a clean capture of the WRONG article.

    The evidence types (highlight, annotate, macro) still use the real page:
    there the whole point is that the claim is visible on the publisher's own
    site, and each crops tightly onto a located phrase, so page furniture never
    enters the frame. This function serves the other job — something relevant,
    on-brand and legible for the eye to rest on — using the same text the script
    was written from, so it cannot drift off-topic.

    Rendered at 1080 CSS px so body type lands at ~37px, which stays readable
    once the panel scales it; the previous full-page captures were 2560px wide
    and their body text arrived at roughly 8px.
    """
    pal = palette or []
    bg = pal[0] if pal else "#0B0D11"
    fg = "#F4F6F8"
    accent = next((c for c in reversed(pal) if c.lower() not in
                   ("#000000", "#ffffff", bg.lower())), "#22D3EE")

    text = _strip_boilerplate(text, title)
    paras = [p.strip() for p in re.split(r"\n\s*\n|\r\n\r\n", text) if p.strip()]
    if len(paras) < 3:
        paras = [s.strip() for s in re.split(r"(?<=[.!?])\s{1,2}(?=[A-Z])", text)
                 if s.strip()]
    # Group short fragments so the column reads as prose rather than a list.
    merged: list[str] = []
    for p in paras:
        if merged and len(merged[-1]) < 180:
            merged[-1] = f"{merged[-1]} {p}"
        else:
            merged.append(p)
    merged = merged[:max_paragraphs]
    if not merged:
        raise PageRollError("no source text to render a reader page from")

    body = "".join(
        f'<p class="{"lead" if i == 0 else ""}">{html.escape(p)}</p>'
        for i, p in enumerate(merged))
    doc = (f"<!doctype html><meta charset=utf-8>"
           f"<style>{_READER_CSS % {'bg': bg, 'fg': fg, 'accent': accent}}</style>"
           f'<div class="kicker">{html.escape(kicker[:40])}</div>'
           f"<h1>{html.escape(title)}</h1><div class=rule></div>{body}")

    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    html_path = str(Path(out_png).with_suffix(".html"))
    Path(html_path).write_text(doc, encoding="utf-8")

    # Playwright's full_page, not Chrome's --screenshot: new headless captures
    # the WINDOW, so a fixed --window-size either clips the column or pads it
    # with empty background, and empty background in the panel is the blank-frame
    # defect this whole path exists to avoid. full_page sizes to the content.
    # Also record where each paragraph sits, so a caller can frame ON a
    # paragraph and highlight it rather than drifting past the column at a
    # position that means nothing. Written beside the PNG as a sidecar.
    shot = f'''
import json, sys
from playwright.sync_api import sync_playwright
src, out, rects_out = sys.argv[1:4]
DPR = 2
with sync_playwright() as p:
    b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
    pg = b.new_page(viewport={{"width": 1080, "height": 1400}},
                    device_scale_factor=DPR)
    pg.goto("file://" + src, wait_until="load")
    pg.wait_for_timeout(400)
    pg.screenshot(path=out, full_page=True)
    rects = pg.evaluate("""() => Array.from(document.querySelectorAll('p'))
        .map(function (el) {{
          var r = el.getBoundingClientRect();
          return {{y: Math.round(r.top + window.scrollY),
                  h: Math.round(r.height),
                  chars: (el.innerText || '').trim().length}};
        }})""")
    for r in rects:
        r["y"] *= DPR
        r["h"] *= DPR
    open(rects_out, "w").write(json.dumps(rects))
    b.close()
print("OK")
'''
    rects_path = str(Path(out_png).with_suffix(".json"))
    r = subprocess.run(["python3", "-c", shot, html_path, out_png, rects_path],
                       capture_output=True, text=True, timeout=timeout_s)
    if not os.path.exists(out_png) or os.path.getsize(out_png) == 0:
        raise PageRollError(
            f"reader render failed: {(r.stderr or r.stdout or '')[-300:]}")
    logger.info("Reader page: %d paragraphs, %s (%d KB)", len(merged),
                out_png, os.path.getsize(out_png) // 1024)
    return out_png


def reader_paragraphs(reader_png: str, *, min_chars: int = 90,
                      target_width: int = 0) -> list[dict]:
    """Paragraph rectangles for a reader page, tall enough to be worth framing.

    Returns [{"y", "h", "chars"}, ...]. Empty when the sidecar is missing, which
    lets the caller fall back to plain drifting.

    ``target_width`` rescales the rectangles into the coordinate space the
    caller will actually crop in. This is not optional bookkeeping: the sidecar
    records device pixels (the page is captured at DPR 2, so 2160 wide) while the
    panel filter scales the image to 1080 wide first, which halves every y. Used
    unscaled, every paragraph's offset came out 2x too large, clamped against the
    bottom of the image, and EVERY panel framed the last paragraph of the article
    — the same coordinate-space mismatch that put annotation boxes on empty space
    twice before.
    """
    sidecar = Path(reader_png).with_suffix(".json")
    if not sidecar.exists():
        return []
    try:
        rects = json.loads(sidecar.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    out = [r for r in rects if r.get("chars", 0) >= min_chars]

    if target_width and out:
        try:
            from PIL import Image
            with Image.open(reader_png) as im:
                src_w = im.width
        except Exception:                          # noqa: BLE001 — optional
            src_w = 0
        if src_w and src_w != target_width:
            k = target_width / src_w
            out = [{**r, "y": int(r["y"] * k), "h": max(1, int(r["h"] * k))}
                   for r in out]
            logger.info("Reader rects scaled by %.3f (%dpx capture -> %dpx "
                        "panel)", k, src_w, target_width)
    return out


def detect_regions(png: str, *, panel_aspect: float = 998 / 1080,
                   max_regions: int = 14, overlap: float = 0.5) -> list[Region]:
    """Slice the page into panel-shaped windows and rank them by content.

    A first version looked for whitespace gaps between blocks. That works on
    article pages and fails completely on an application UI: a GitHub file
    listing has no blank rows, so the whole 6000px page came back as one
    region and the clip was a squeezed full-page smear.

    Windows are sized so that scaling the page's full width to the panel width
    fills the panel height exactly — the region is a natural screenful, shown
    at the page's own proportions, with nothing cropped off the sides.
    """
    from PIL import Image
    import numpy as np

    im = Image.open(png).convert("RGB")
    a = np.asarray(im)
    h, w = a.shape[:2]
    bg = np.median(a.reshape(-1, 3), axis=0)
    dev = np.abs(a.astype(np.int16) - bg.astype(np.int16)).sum(axis=2)
    active = dev > 34
    rowact = active.mean(axis=1)

    win = max(200, int(w * panel_aspect))          # page px per screenful
    # A 6000px page holds only ~2.5 screenfuls, so windows overlap heavily —
    # otherwise there are not enough distinct regions to cover a 60s video.
    step = max(1, int(win * (1.0 - overlap)))

    windows: list[Region] = []
    for top in range(0, max(1, h - win), step):
        bottom = min(h, top + win)
        density = float(rowact[top:bottom].mean())
        # Ignore near-empty windows: page footers and long blank tails.
        if density < 0.012:
            continue
        windows.append(Region(top=top, bottom=bottom, left=0, right=w,
                              density=density))

    if not windows:
        windows = [Region(top=0, bottom=min(h, win), left=0, right=w,
                          density=float(rowact[:win].mean()))]

    # Keep the densest, then restore document order so the clips read as a
    # progression down the page rather than a jumble.
    windows.sort(key=lambda r: -r.density)
    windows = windows[:max_regions]
    windows.sort(key=lambda r: r.top)
    for i, r in enumerate(windows):
        r.index = i
    logger.info("Detected %d content windows (%dpx each) in %s",
                len(windows), win, Path(png).name)
    return windows


def render_region(png: str, region: Region, out_mp4: str, *,
                  duration: float, width: int, height: int,
                  fps: int) -> RollKind:
    """Fit one region to the panel and move gently within it.

    The region is scaled so its FULL WIDTH fits the panel — nothing is cropped
    horizontally, which is what previously sliced content off both edges. If
    the scaled region is taller than the panel the crop window travels down it;
    otherwise it is centred, padded, and given a slow push.
    """
    frames = max(2, int(duration * fps))
    scale = width / max(1, region.width)
    scaled_h = int(region.height * scale)

    pre = (f"crop={region.width}:{region.height}:{region.left}:{region.top},"
           f"scale={width}:-2:flags=lanczos")

    if scaled_h > height + 20:
        travel = scaled_h - height
        # At most one panel-height of travel per clip: faster and the eye
        # cannot read anything on the way past.
        y1 = min(travel, height)
        vf = (f"{pre},crop={width}:{height}:0:'0+({y1})*n/{frames - 1}',"
              f"format=yuv420p")
        kind: RollKind = "scroll"
    else:
        pad_y = max(0, (height - scaled_h) // 2)
        vf = (f"{pre},pad={width}:{height}:0:{pad_y}:color=0x0D1117,"
              f"zoompan=z='1.0+0.06*on/{frames}':x='iw/2-(iw/zoom/2)':"
              f"y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps={fps},"
              f"format=yuv420p")
        kind = "hold"

    cmd = ["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", str(fps),
           "-t", f"{duration:.3f}", "-i", png, "-vf", vf, "-r", str(fps),
           "-frames:v", str(frames),
           "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out_mp4]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise PageRollError(f"region render failed: {r.stderr[-500:]}")
    return kind


def build_rolls(url: str, out_dir: str, *, count: int = 4,
                duration: float = 3.0, width: int = 1080, height: int = 1920,
                fps: int = 25, half_height: Optional[int] = None,
                pick: Optional[list[int]] = None) -> list[RollClip]:
    """Capture the page and render one clip per selected content region.

    ``pick`` chooses region indices, letting a caller align regions to script
    beats. Without it, regions are spread evenly down the page.
    """
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    png = os.path.join(out_dir, "page.png")
    try:
        capture_page(url, png)
    except (PageRollError, subprocess.TimeoutExpired) as exc:
        logger.warning("page-roll capture failed for %s: %s", url, exc)
        return []

    try:
        regions = detect_regions(png, panel_aspect=(half_height or height) / width)
    except Exception as exc:                      # noqa: BLE001 — optional stage
        logger.warning("region detection failed: %s", exc)
        return []
    if not regions:
        logger.warning("no content regions found in %s", url)
        return []

    json.dump([{"index": r.index, "top": r.top, "bottom": r.bottom,
                "left": r.left, "right": r.right, "height": r.height,
                "width": r.width, "density": round(r.density, 4)}
               for r in regions],
              open(os.path.join(out_dir, "regions.json"), "w"), indent=2)

    if pick:
        chosen = [regions[i] for i in pick if 0 <= i < len(regions)][:count]
    else:
        step = max(1, len(regions) // max(1, count))
        chosen = regions[::step][:count]

    h = half_height or height
    clips: list[RollClip] = []
    for i, reg in enumerate(chosen):
        out = os.path.join(out_dir, f"roll_{i}.mp4")
        try:
            kind = render_region(png, reg, out, duration=duration, width=width,
                                 height=h, fps=fps)
        except PageRollError as exc:
            logger.warning("region %d failed: %s", reg.index, exc)
            continue
        clips.append(RollClip(path=out, kind=kind, duration=duration,
                              source_url=url, region_index=reg.index,
                              region=f"y{reg.top}-{reg.bottom}"))
        logger.info("page-roll %d: %s region %d (%dx%d at y=%d)",
                    i, kind, reg.index, reg.width, reg.height, reg.top)
    return clips
