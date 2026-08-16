"""Load source material for a short.

Three kinds, all reduced to the same shape: a facts blob the intelligence layer
can write from, plus a label describing what sort of story it is.

Article URLs are fetched with a browser User-Agent. Many publishers — OpenAI's
own blog among them — sit behind Cloudflare and return 403 to default library
agents. When a fetch is blocked the error says so explicitly rather than
returning an empty body that would silently become a content-free script.
"""
from __future__ import annotations

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
        s = data.strip()
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

    html = _fetch(s)
    p = _Text()
    p.feed(html)
    body = "\n".join(p.parts)
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    doc_title = title or (m.group(1).strip() if m else s)
    if len(body) < 400:
        raise SourceError(
            f"extracted only {len(body)} chars of text from {s} — the page is "
            f"probably JavaScript-rendered. Supply the text directly."
        )
    logger.info("Loaded article %r (%d chars)", doc_title, len(body))
    return Source(kind="article", title=doc_title, text=body[:20000], url=s)
