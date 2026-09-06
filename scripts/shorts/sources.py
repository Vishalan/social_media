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

from .net import BROWSER_UA as _UA

logger = logging.getLogger(__name__)

SourceKind = Literal["article", "github_repo", "text"]



class SourceError(RuntimeError):
    """Raised when source material cannot be obtained."""


@dataclass
class Source:
    kind: SourceKind
    title: str
    text: str
    url: str = ""
    # Did the BODY come from fetching `url`, or from text supplied alongside it?
    #
    # This decides whether the page may be shown on screen. If the fetch could
    # not yield the article's text, a screenshot of that same page is not
    # evidence of anything either — it is a paywall wall, a bot check, or a
    # cookie banner. Bloomberg returned exactly that: a "PRESS & HOLD /
    # SUBSCRIBE NOW" interstitial, which went into a video as b-roll.
    fetched: bool = True

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



_URL_RE = re.compile(r"https?://\S+")


def _headline_of(prose: str) -> str:
    """The headline sitting at the top of pasted prose.

    A newsletter blurb leads with its headline, so when the page itself cannot
    be fetched that line is the only title available — and the title is not
    cosmetic here: it feeds the thumbnail, the kicker and the brand card.
    Falling back to "untitled" threw away something that was right there.
    """
    for raw in prose.splitlines():
        line = raw.strip()
        if len(line) < 12 or len(line) > 160:
            continue
        # Newsletters tack a reading time onto the headline.
        line = re.sub(r"\s*\(\s*\d+\s*minute read\s*\)\s*$", "", line,
                      flags=re.I).strip()
        # A headline is a fragment; a body sentence ends in a full stop.
        if line.endswith(".") and len(line.split()) > 12:
            continue
        return line
    return ""


def split_spec(spec: str) -> tuple[str, str]:
    """Separate a leading URL from any prose pasted with it.

    Real inputs arrive as a link AND a summary together — someone forwards a
    newsletter blurb with the article link above it. Treating that whole blob
    as one thing gets it wrong either way: as a URL the trailing prose corrupts
    it, as text the link becomes narration.

    Both halves are worth keeping. The URL identifies the publisher, which is
    what the source badge and palette are built from, while the prose is often
    the only body text available when the page is paywalled.
    """
    m = _URL_RE.search(spec)
    if not m:
        return "", spec.strip()
    url = m.group(0).rstrip(").,\u201d\"'")
    rest = (spec[:m.start()] + spec[m.end():]).strip()
    return url, rest


async def research(topic: str, ask) -> Source:
    """Build source material for a bare topic by searching the web.

    `ask` is the pipeline's intelligence callable. Research runs through it
    rather than a search API because the claude CLI already has web access and
    is already authenticated — adding a second search dependency would be a
    second thing to key, rate-limit and break.

    The prompt demands dates and figures explicitly. Without that the model
    returns a confident essay of general knowledge, which is indistinguishable
    from research until it goes into a video as fact.
    """
    prompt = (
        f"Research this topic on the web and report what you FIND, not what "
        f"you already know: {topic}\n\n"
        "Search for current reporting. Return 400-800 words of plain prose "
        "covering: what happened, when (give absolute dates), the specific "
        "numbers and named parties involved, and why it matters now. "
        "Attribute each significant claim to the outlet that reported it. "
        "If you cannot verify something, leave it out rather than hedging. "
        "No preamble, no bullet points, no headings — prose only."
    )
    text = (await ask(prompt) or "").strip()
    if len(text) < 300:
        raise SourceError(
            f"research on {topic!r} returned only {len(text)} chars — refusing "
            f"to build a video on it")
    logger.info("Researched %r (%d chars)", topic, len(text))
    return Source(kind="text", title=topic.strip()[:120], text=text)


def load_source(spec: str, *, kind: SourceKind | None = None,
                title: str = "") -> Source:
    """Load source material from a URL, a repo reference, or raw text.

    Args:
        spec: a URL, an ``owner/repo`` reference, or the text itself.
        kind: force a kind; inferred when omitted.
        title: optional title override for raw text.
    """
    s = spec.strip()

    # A link pasted together with prose is one input describing one story.
    url, prose = split_spec(s)
    if url and prose and kind != "text":
        try:
            src = load_source(url, kind=kind, title=title)
            # Prefer the fetched body, but keep the prose when the fetch came
            # back thin — paywalled pages return a teaser, not an error.
            if len(src.text) < max(600, len(prose)):
                logger.info("Fetched only %d chars from %s; using the supplied "
                            "text as the body and keeping the URL for "
                            "attribution", len(src.text), url)
                return Source(
                    kind=src.kind,
                    title=src.title or title or _headline_of(prose) or "untitled",
                    text=prose, url=url, fetched=False)
            return src
        except SourceError as exc:
            logger.info("Could not fetch %s (%s) — using the supplied text, "
                        "still crediting the source", url, str(exc)[:90])
            return Source(kind="article",
                          title=title or _headline_of(prose) or "untitled",
                          text=prose, url=url, fetched=False)

    if kind == "text" or (kind is None and not s.startswith("http")
                          and "/" not in s.split("\n")[0][:60]):
        return Source(kind="text", title=title or "untitled", text=s,
                      fetched=False)

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


_MD_PATTERNS = (
    (re.compile(r"<[^>]{1,200}>"), " "),               # html tags
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), " "),         # images
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),      # links -> their text
    (re.compile(r"```[\s\S]*?```"), " "),              # fenced code
    (re.compile(r"`([^`]*)`"), r"\1"),                  # inline code
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.M), ""),      # heading hashes
    (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),            # bold
    (re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)"), r"\1"),  # italic
    (re.compile(r"^\s{0,3}[-*+]\s+", re.M), ""),       # bullets
    (re.compile(r"^\s{0,3}>\s?", re.M), ""),           # block quotes
    (re.compile(r"^\s*\|.*\|\s*$", re.M), " "),         # table rows
    (re.compile(r"^\s*[-=]{3,}\s*$", re.M), " "),       # rules
    (re.compile(r"https?://\S+"), " "),                # bare urls
)


def strip_markup(text: str) -> str:
    """Plain prose from markdown or HTML.

    The script generator copes with markup because a model reads through it.
    Anything drawn ON SCREEN does not: the pull-quote bed renders source
    sentences verbatim, so a GitHub README put `**[skills.sh](https://...)**`
    and a raw `<details>` tag into a finished video, at a tiny size because the
    fitter was shrinking to accommodate a URL nobody could read anyway.

    Links keep their TEXT and lose their target, which is the only part that
    was ever meant to be read aloud or seen.
    """
    out = text or ""
    for pattern, repl in _MD_PATTERNS:
        out = pattern.sub(repl, out)
    # Collapse the whitespace the substitutions leave behind, but keep the
    # paragraph breaks that sentence splitting depends on.
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _article_body(text: str) -> str:
    """Cut the page's tail off before anything is ranked."""
    low = (text or "").lower()
    cut = len(text or "")
    for marker in _TAIL_MARKERS:
        i = low.find(marker)
        if 0 <= i < cut:
            cut = i
    return (text or "")[:cut]


def pull_sentences(text: str, count: int, *, min_words: int = 6,
                   max_words: int = 14) -> list:
    """Pick sentences worth putting on screen, with a phrase to emphasise.

    The presenter-span bed used to render whole PARAGRAPHS of the source at body
    size — four of them at once, clipped top and bottom. Everything competed
    with everything, so there was no focal point and the viewer had nowhere to
    look. One sentence at display size, with one phrase accented, is a graphic;
    a paragraph column is a screenshot of a webpage.

    Ranking prefers sentences that carry something concrete — a figure, a
    quoted term, a named thing — because those are the ones that reward being
    read in the two seconds a bed gets.

    The word ceiling used to be 26, which was survivable when a bed held the
    screen for six seconds and is not now that shots are capped near two. A
    26-word sentence rendered as eight lines of body copy that nobody can read
    at that length — and because the type auto-fits, more words silently buys
    smaller type, so the failure is a wall of small text rather than an
    overflow anything would catch. Fourteen words is roughly what a viewer can
    take from a glance while also listening to a different sentence.

    Returns [{"sentence", "emphasis"}, ...], at most ``count``.
    """
    # Markup never reaches the screen. These sentences are drawn
    # verbatim in the pull-quote bed, and a README is markdown.
    text = strip_markup(text)
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
