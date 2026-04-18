"""Tests for scripts.topic_intel.article_extractor.

All tests mock trafilatura — no real network I/O.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import types
from pathlib import Path

import pytest

# Support dual-import: run from repo root (scripts.topic_intel...) or from scripts/.
try:
    from scripts.topic_intel import article_extractor as ae
except ImportError:  # pragma: no cover — fallback when cwd is scripts/
    from topic_intel import article_extractor as ae  # type: ignore[no-redef]


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_article.html"
URL = "https://example.com/gpt-x-announcement"


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _install_fake_trafilatura(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fetch_return: object = "<html>stub</html>",
    extract_return: object,
    fetch_calls: list[str] | None = None,
) -> None:
    """Install a fake `trafilatura` module so the extractor can import it.

    If `fetch_calls` is provided, every call to `fetch_url` appends its URL.
    """
    fake = types.ModuleType("trafilatura")

    def _fake_fetch_url(url: str) -> object:
        if fetch_calls is not None:
            fetch_calls.append(url)
        return fetch_return

    def _fake_extract(downloaded: object, *, output_format: str = "json") -> object:
        assert output_format == "json", "contract: extractor must ask for JSON"
        if callable(extract_return):
            return extract_return(downloaded)
        return extract_return

    fake.fetch_url = _fake_fetch_url  # type: ignore[attr-defined]
    fake.extract = _fake_extract  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "trafilatura", fake)


def _fixture_payload(text: str, *, title: str = "GPT-X Announcement") -> str:
    return json.dumps(
        {
            "title": title,
            "text": text,
            "author": "Jane Reporter",
            "date": "2026-04-15",
        }
    )


# ─── Tests ────────────────────────────────────────────────────────────────────


def test_extract_happy_path_mocked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reasonable JSON input → lead paragraph populated, ≥2 body paragraphs."""
    # The fixture HTML exists and is loadable (proves the fixture is real);
    # we feed a JSON payload representing what trafilatura would return.
    assert FIXTURE_PATH.exists(), "fixture HTML must exist on disk"
    html_bytes = FIXTURE_PATH.read_text(encoding="utf-8")
    assert "GPT-X" in html_bytes

    long_p1 = (
        "OpenAI on Monday unveiled GPT-X, its newest large language model, "
        "claiming significant gains in multi-step reasoning and tool use."
    )
    long_p2 = (
        "Early benchmarks published by the company show GPT-X solving "
        "olympiad-level mathematics problems in a single forward pass."
    )
    long_p3 = (
        "The release comes amid growing competition from rival labs, several "
        "of whom have shipped comparable models in the past month."
    )
    body = "\n\n".join([long_p1, long_p2, long_p3])
    _install_fake_trafilatura(
        monkeypatch,
        fetch_return=html_bytes,
        extract_return=_fixture_payload(body),
    )

    out = ae.extract_article_text(URL, cache_dir=tmp_path)
    assert out is not None
    assert isinstance(out, ae.ArticleExtract)
    assert len(out.lead_paragraph) > 40
    assert out.lead_paragraph == long_p1
    assert len(out.body_paragraphs) >= 2
    assert out.body_paragraphs[0] == long_p1
    assert out.title == "GPT-X Announcement"
    assert out.source_url == URL


def test_extract_paywall_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Body < 80 chars after filtering → None (paywall signal)."""
    # A single short paragraph that survives paragraph-length filtering would
    # still be < 80 chars total. Use something >= 40 chars so it isn't dropped
    # at the per-paragraph step, then verify the 80-char body gate still rejects.
    short = "Subscribe for full access to this article."  # 42 chars
    assert len(short) >= ae._MIN_PARAGRAPH_CHARS
    assert len(short) < ae._MIN_BODY_CHARS
    _install_fake_trafilatura(
        monkeypatch,
        extract_return=_fixture_payload(short),
    )

    out = ae.extract_article_text(URL, cache_dir=tmp_path)
    assert out is None


def test_short_paragraphs_filtered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Paragraphs shorter than 40 chars are excluded from body_paragraphs."""
    short = "Share"  # 5 chars
    long_a = (
        "OpenAI on Monday unveiled GPT-X, its newest large language model, "
        "claiming significant gains in multi-step reasoning."
    )
    long_b = (
        "Early benchmarks show GPT-X solving olympiad-level mathematics "
        "problems that previously required agentic scaffolding."
    )
    body = "\n\n".join([short, long_a, "Tweet", long_b, "x"])
    _install_fake_trafilatura(
        monkeypatch,
        extract_return=_fixture_payload(body),
    )

    out = ae.extract_article_text(URL, cache_dir=tmp_path)
    assert out is not None
    assert short not in out.body_paragraphs
    assert "Tweet" not in out.body_paragraphs
    assert "x" not in out.body_paragraphs
    assert long_a in out.body_paragraphs
    assert long_b in out.body_paragraphs
    assert all(len(p) >= 40 for p in out.body_paragraphs)


def test_sponsored_content_stripped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Paragraphs matching the sponsored/ad/continue-reading regex are stripped."""
    sponsored = (
        "This paragraph contains sponsored content and should not appear in the output."
    )
    ad = "Advertisement — try our new premium plan for free this month."
    cont = "Continue reading below to see the rest of this long-form article."
    real_body = (
        "OpenAI on Monday unveiled GPT-X, its newest large language model. "
        "The announcement marks the first major release since last year."
    )
    real_body_b = (
        "Early benchmarks show strong gains on reasoning tasks, though "
        "third-party verification is still pending."
    )
    body = "\n\n".join([sponsored, real_body, ad, real_body_b, cont])
    _install_fake_trafilatura(
        monkeypatch,
        extract_return=_fixture_payload(body),
    )

    out = ae.extract_article_text(URL, cache_dir=tmp_path)
    assert out is not None
    for para in out.body_paragraphs:
        assert "sponsored content" not in para.lower()
        assert "advertisement" not in para.lower()
        assert "continue reading" not in para.lower()
    assert real_body in out.body_paragraphs
    assert real_body_b in out.body_paragraphs


def test_disk_cache_hit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Second call with same URL reads from cache; fetch_url is not called twice."""
    long_a = (
        "OpenAI on Monday unveiled GPT-X, its newest large language model, "
        "claiming significant gains on reasoning benchmarks."
    )
    long_b = (
        "The model is available through the API at a reduced price, "
        "targeted at high-volume developers."
    )
    body = "\n\n".join([long_a, long_b])
    fetch_calls: list[str] = []
    _install_fake_trafilatura(
        monkeypatch,
        extract_return=_fixture_payload(body),
        fetch_calls=fetch_calls,
    )

    first = ae.extract_article_text(URL, cache_dir=tmp_path)
    assert first is not None
    assert len(fetch_calls) == 1

    # Cache file should now exist at the hashed path.
    expected_file = tmp_path / f"{ae._url_hash(URL)}.json"
    assert expected_file.exists(), "first call should have written the cache"

    second = ae.extract_article_text(URL, cache_dir=tmp_path)
    assert second is not None
    assert second.to_dict() == first.to_dict()
    # fetch_url was NOT called a second time — pure cache hit.
    assert len(fetch_calls) == 1


def test_dataclass_to_dict_roundtrip() -> None:
    """ArticleExtract.to_dict → JSON-serializable, contains all fields."""
    art = ae.ArticleExtract(
        title="Hello World",
        lead_paragraph="A paragraph of reasonable length for testing serialization.",
        body_paragraphs=[
            "A paragraph of reasonable length for testing serialization.",
            "Another paragraph — also long enough to be plausible body copy.",
        ],
        publish_date="2026-04-18",
        byline="Jane Reporter",
        source_url="https://example.com/hello",
    )
    d = art.to_dict()
    assert isinstance(d, dict)

    # JSON-serializable.
    encoded = json.dumps(d)
    assert "Hello World" in encoded

    # All dataclass fields present.
    field_names = {f.name for f in dataclasses.fields(ae.ArticleExtract)}
    assert field_names.issubset(d.keys())

    # Round-trip back through from_dict.
    restored = ae.ArticleExtract.from_dict(json.loads(encoded))
    assert restored == art
