"""Load source material for a short.

Three kinds, all reduced to the same shape: a facts blob the intelligence layer
can write from, plus a label describing what sort of story it is.

Article URLs are fetched with a browser User-Agent. Many publishers — OpenAI's
own blog among them — sit behind Cloudflare and return 403 to default library
agents. When a fetch is blocked the error says so explicitly rather than
returning an empty body that would silently become a content-free script.
"""
from __future__ import annotations

import html
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

logger = logging.getLogger(__name__)

SourceKind = Literal["article", "github_repo", "text"]

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class SourceError(RuntimeError):
    """Raised when source material cannot be obtained."""


@dataclass
class Source:
    kind: SourceKind
    title: str
    text: str
    url: str = ""

    def summary(self) -> str:
        return self.text


class _Text(HTMLParser):
    """Minimal article-text extractor: drops script/style, keeps block text."""

    _SKIP = {"script", "style", "nav", "footer", "header", "aside", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth:
            return
        s = html.unescape(data).strip()
        if len(s) > 2:
            self.parts.append(s)


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 429):
            raise SourceError(
                f"{url} returned HTTP {exc.code} — the publisher is blocking "
                f"automated fetches. Supply the text directly (kind='text') or "
                f"capture it through a browser."
            ) from exc
        raise SourceError(f"{url} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SourceError(f"cannot reach {url}: {exc}") from exc


def load_source(spec: str, *, kind: SourceKind | None = None,
                title: str = "") -> Source:
    """Load source material from a URL, a repo reference, or raw text.

    Args:
        spec: a URL, an ``owner/repo`` reference, or the text itself.
        kind: force a kind; inferred when omitted.
        title: optional title override for raw text.
    """
    s = spec.strip()

    if kind == "text" or (kind is None and not s.startswith("http")
                          and "/" not in s.split("\n")[0][:60]):
        return Source(kind="text", title=title or "untitled", text=s)

    if kind == "github_repo" or "github.com/" in s or (
            kind is None and re.fullmatch(r"[\w.-]+/[\w.-]+", s)):
        from topic_intel.github_repo import fetch_repo, GitHubRepoError
        try:
            facts = fetch_repo(s)
        except GitHubRepoError as exc:
            raise SourceError(str(exc)) from exc
        return Source(kind="github_repo", title=facts.full_name,
                      text=facts.summary(), url=s)

    raw_html = _fetch(s)
    p = _Text()
    p.feed(raw_html)
    body = "\n".join(p.parts)
    m = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.S | re.I)
    # Unescape: a raw title renders as "they&#039;ve been &#039;shadowbanned&#039;"
    # wherever it is drawn on screen.
    doc_title = title or (html.unescape(m.group(1)).strip() if m else s)
    # Publishers append their own name; it is noise in a 140-char mockup title.
    doc_title = re.sub(r"\s*[|\-–—]\s*[A-Z][\w .]{2,24}$", "", doc_title).strip()
    if len(body) < 400:
        raise SourceError(
            f"extracted only {len(body)} chars of text from {s} — the page is "
            f"probably JavaScript-rendered. Supply the text directly."
        )
    logger.info("Loaded article %r (%d chars)", doc_title, len(body))
    return Source(kind="article", title=doc_title, text=body[:20000], url=s)


# ------------------------------------------------------------- pull quotes
_NUM_RE = __import__("re").compile(r"\d")
_STOP_START = ("the company", "it also", "this also", "that was", "in earlier",
               "the platform", "image credits", "close", "subscribe")

# Everything from the first of these onward is the page's tail, not the story:
# author bio, contact details, event promotion, corrections, tag lists. Ranking
# over the raw scrape surfaced exactly these — a reporter's start date, a Signal
# handle and a conference sell — because they are dense with the numbers and
# capitalised names the scoring rewards.
_TAIL_MARKERS = (
    "view bio", "consumer news editor", "senior reporter", "you can contact",
    "correction:", "topics\n", "related articles", "most popular",
    "newsletters", "scale faster", "sign up for", "follow us on",
)

# A sentence containing any of these is furniture wherever it appears.
_JUNK_IN = (
    "@", "signal.", "encrypted", "view bio", "correction:", "techcrunch since",
    "reporter for", "editor at", "subscribe", "newsletter", "all rights reserved",
)


def _article_body(text: str) -> str:
    """Cut the page's tail off before anything is ranked."""
    low = (text or "").lower()
    cut = len(text or "")
    for marker in _TAIL_MARKERS:
        i = low.find(marker)
        if 0 <= i < cut:
            cut = i
    return (text or "")[:cut]


def pull_sentences(text: str, count: int, *, min_words: int = 9,
                   max_words: int = 26) -> list:
    """Pick sentences worth putting on screen, with a phrase to emphasise.

    The presenter-span bed used to render whole PARAGRAPHS of the source at body
    size — four of them at once, clipped top and bottom. Everything competed
    with everything, so there was no focal point and the viewer had nowhere to
    look. One sentence at display size, with one phrase accented, is a graphic;
    a paragraph column is a screenshot of a webpage.

    Ranking prefers sentences that carry something concrete — a figure, a
    quoted term, a named thing — because those are the ones that reward being
    read in the two seconds a bed gets.

    Returns [{"sentence", "emphasis"}, ...], at most ``count``.
    """
    import re

    body = _article_body(text)
    raw = [" ".join(s.split()) for s in re.split(r"(?<=[.!?])\s+", body)]
    total = max(1, len(raw))
    seen, scored = set(), []
    for pos, s in enumerate(raw):
        words = s.split()
        if not (min_words <= len(words) <= max_words):
            continue
        low = s.lower()
        if any(low.startswith(x) for x in _STOP_START):
            continue
        if any(j in low for j in _JUNK_IN):
            continue
        key = low[:48]
        if key in seen:
            continue
        seen.add(key)
        score = 0
        if _NUM_RE.search(s):
            score += 3
        if '"' in s or "“" in s or "'" in s:
            score += 2
        # A capitalised word mid-sentence is usually a product or a person.
        score += min(3, sum(1 for w in words[1:] if w[:1].isupper()))
        # Mid-length sentences read best on a panel.
        score += 2 if 12 <= len(words) <= 20 else 0
        # Earlier is better: a news article puts its substance up top, and the
        # further down the scrape you go the more likely a sentence is tail.
        score += 3 if pos < total * 0.35 else (1 if pos < total * 0.7 else 0)
        scored.append((score, s))

    scored.sort(key=lambda x: -x[0])
    out = []
    for _, s in scored[:count]:
        out.append({"sentence": s, "emphasis": _emphasis_of(s)})
    return out


def _emphasis_of(sentence: str) -> str:
    """The phrase inside a sentence that should carry the accent.

    One target, chosen by what the eye would go to anyway: a figure if there is
    one, otherwise the clause after the first comma, otherwise the middle.
    """
    import re

    words = sentence.split()
    m = re.search(r"\S*\d\S*", sentence)
    if m:
        idx = len(sentence[:m.start()].split())
        return " ".join(words[idx:idx + 3])
    if "," in sentence:
        after = sentence.split(",", 1)[1].split()
        if len(after) >= 3:
            return " ".join(after[:3])
    mid = max(1, len(words) // 3)
    return " ".join(words[mid:mid + 3])
