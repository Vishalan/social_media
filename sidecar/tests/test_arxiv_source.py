"""Tests for ArxivTopicSource."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx

from sidecar.topic_sources.arxiv_source import ArxivTopicSource


def _entry(arxiv_id: str, title: str, abstract: str) -> str:
    return f"""
    <item rdf:about="https://arxiv.org/abs/{arxiv_id}">
      <title>{title}. (arXiv:{arxiv_id} [cs.AI])</title>
      <link>https://arxiv.org/abs/{arxiv_id}</link>
      <description>&lt;p&gt;{abstract}&lt;/p&gt;</description>
      <dc:rights>http://creativecommons.org/licenses/by/4.0/</dc:rights>
    </item>
    """


def _feed(*entries: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel rdf:about="http://arxiv.org/rss/cs.AI"><title>cs.AI</title></channel>
  {''.join(entries)}
</rdf:RDF>
"""


FEED_AI = _feed(
    _entry("2601.00001v1", "Transformers Eat the World", "We show <em>transformers</em> are all you need."),
    _entry("2601.00002v1", "Diffusion Goes Brrr", "A new diffusion sampler."),
    _entry("2601.00003v1", "Shared Paper About LLMs", "Cross-listed work."),
)

FEED_CL = _feed(
    _entry("2601.00099v1", "Tokenizers Considered Harmful", "An NLP rant."),
    _entry("2601.00003v1", "Shared Paper About LLMs", "Cross-listed work."),
)


def _resp(text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        text=text,
        request=httpx.Request("GET", "http://export.arxiv.org/rss/cs.AI"),
    )


def _patch_sequence(*responses):
    return patch("httpx.Client.get", side_effect=list(responses))


def test_is_configured_always_true():
    src = ArxivTopicSource()
    assert src.is_configured(None) is True
    assert src.is_configured(SimpleNamespace()) is True


def test_valid_feeds_return_items_with_source_stamp():
    src = ArxivTopicSource()
    with _patch_sequence(_resp(FEED_AI), _resp(FEED_CL)):
        items, label = src.fetch_items(SimpleNamespace())
    assert label.startswith("arxiv@")
    assert len(items) >= 4
    for item in items:
        assert item["source"] == "arxiv"
        assert item["url"].startswith("https://arxiv.org/abs/")
        assert "title" in item and item["title"]
        assert "summary" in item


def test_cross_category_dedup_keeps_one_copy():
    src = ArxivTopicSource()
    with _patch_sequence(_resp(FEED_AI), _resp(FEED_CL)):
        items, _ = src.fetch_items(SimpleNamespace())
    urls = [i["url"] for i in items]
    assert len(urls) == len(set(urls))
    shared = "https://arxiv.org/abs/2601.00003v1"
    assert urls.count(shared) == 1


def test_title_cleaning_strips_arxiv_suffix():
    src = ArxivTopicSource()
    with _patch_sequence(_resp(FEED_AI), _resp(_feed())):
        items, _ = src.fetch_items(SimpleNamespace())
    assert any(i["title"] == "Transformers Eat the World" for i in items)
    for i in items:
        assert "arXiv:" not in i["title"]


def test_abstract_html_tags_stripped():
    src = ArxivTopicSource()
    with _patch_sequence(_resp(FEED_AI), _resp(_feed())):
        items, _ = src.fetch_items(SimpleNamespace())
    target = next(i for i in items if "Transformers" in i["title"])
    assert "<em>" not in target["summary"]
    assert "transformers" in target["summary"]


def test_empty_feed_returns_empty():
    src = ArxivTopicSource()
    with _patch_sequence(_resp(_feed()), _resp(_feed())):
        items, label = src.fetch_items(SimpleNamespace())
    assert items == []
    assert label.startswith("arxiv@")


def test_one_category_5xx_other_still_works():
    src = ArxivTopicSource()
    with _patch_sequence(_resp("oops", status=503), _resp(FEED_CL)):
        items, _ = src.fetch_items(SimpleNamespace())
    assert len(items) >= 1
    assert all(i["source"] == "arxiv" for i in items)


def test_all_categories_5xx_returns_empty():
    src = ArxivTopicSource()
    with _patch_sequence(_resp("a", status=503), _resp("b", status=500)):
        items, label = src.fetch_items(SimpleNamespace())
    assert items == []
    assert label.startswith("arxiv@")


def test_malformed_xml_returns_empty():
    src = ArxivTopicSource()
    with _patch_sequence(_resp("<<<not xml>>>"), _resp("<<<also not>>>")):
        items, _ = src.fetch_items(SimpleNamespace())
    assert items == []


def test_max_items_caps_output():
    src = ArxivTopicSource()
    settings = SimpleNamespace(ARXIV_MAX_ITEMS=2)
    with _patch_sequence(_resp(FEED_AI), _resp(FEED_CL)):
        items, _ = src.fetch_items(settings)
    assert len(items) == 2


def test_network_exception_returns_empty():
    src = ArxivTopicSource()
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("boom")):
        items, label = src.fetch_items(SimpleNamespace())
    assert items == []
    assert label.startswith("arxiv@")
