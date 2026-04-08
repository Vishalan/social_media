"""Tests for GitHubTrendingTopicSource."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from sidecar.topic_sources.github_trending_source import GitHubTrendingTopicSource


def _row(owner: str, repo: str, desc: str, stars_today: int) -> str:
    desc_html = (
        f'<p class="col-9 color-fg-muted my-1 pr-4">{desc}</p>' if desc else ""
    )
    star_html = (
        f'<span class="d-inline-block float-sm-right"><svg></svg> {stars_today} stars today</span>'
        if stars_today is not None
        else ""
    )
    return f"""
    <article class="Box-row">
      <h2 class="h3 lh-condensed"><a href="/{owner}/{repo}">{owner}/{repo}</a></h2>
      {desc_html}
      {star_html}
    </article>
    """


def _page(*rows: str) -> str:
    return f"<html><body>{''.join(rows)}</body></html>"


FIXTURE_HTML = _page(
    _row("acme", "rocket", "A blazing fast rocket framework", 250),
    _row("foo", "bar", "Tiny utility lib", 42),
    _row("low", "signal", "Some repo", 3),       # below min stars
    _row("nodesc", "repo", "", 500),               # missing description
)


def _mock_response(status: int = 200, text: str = FIXTURE_HTML):
    request = httpx.Request("GET", "https://github.com/trending")
    return httpx.Response(status_code=status, text=text, request=request)


def _patch_get(response):
    return patch("httpx.Client.get", return_value=response)


def test_is_configured_always_true():
    src = GitHubTrendingTopicSource()
    assert src.is_configured(None) is True
    assert src.is_configured(SimpleNamespace()) is True


def test_normal_html_returns_expected_items():
    src = GitHubTrendingTopicSource()
    with _patch_get(_mock_response()):
        items, label = src.fetch_items(SimpleNamespace())
    assert label.startswith("github_trending@")
    assert len(items) == 2
    titles = [i["title"] for i in items]
    assert any("acme/rocket" in t for t in titles)
    assert any("foo/bar" in t for t in titles)
    for item in items:
        assert item["source"] == "github_trending"
        assert item["url"].startswith("https://github.com/")
        assert "stars today" in item["summary"]


def test_min_stars_filter_drops_low_signal():
    src = GitHubTrendingTopicSource()
    settings = SimpleNamespace(GITHUB_TRENDING_MIN_STARS_TODAY=100)
    with _patch_get(_mock_response()):
        items, _ = src.fetch_items(settings)
    assert len(items) == 1
    assert "acme/rocket" in items[0]["title"]


def test_max_items_caps_output():
    rows = [_row(f"owner{i}", f"repo{i}", f"desc {i}", 50) for i in range(10)]
    html = _page(*rows)
    src = GitHubTrendingTopicSource()
    settings = SimpleNamespace(GITHUB_TRENDING_MAX_ITEMS=3)
    with _patch_get(_mock_response(text=html)):
        items, _ = src.fetch_items(settings)
    assert len(items) == 3


def test_empty_trending_page_returns_empty_list():
    src = GitHubTrendingTopicSource()
    with _patch_get(_mock_response(text="<html><body></body></html>")):
        items, label = src.fetch_items(SimpleNamespace())
    assert items == []
    assert label.startswith("github_trending@")


def test_http_5xx_returns_empty_and_logs(caplog):
    src = GitHubTrendingTopicSource()
    with _patch_get(_mock_response(status=503, text="oops")):
        with caplog.at_level("WARNING"):
            items, label = src.fetch_items(SimpleNamespace())
    assert items == []
    assert label.startswith("github_trending@")
    assert any("503" in r.message for r in caplog.records)


def test_malformed_html_returns_empty():
    src = GitHubTrendingTopicSource()
    with _patch_get(_mock_response(text="<<<not really html>>>")):
        items, _ = src.fetch_items(SimpleNamespace())
    assert items == []


def test_network_exception_returns_empty():
    src = GitHubTrendingTopicSource()
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("boom")):
        items, label = src.fetch_items(SimpleNamespace())
    assert items == []
    assert label.startswith("github_trending@")


def test_source_field_stamped_on_every_item():
    src = GitHubTrendingTopicSource()
    with _patch_get(_mock_response()):
        items, _ = src.fetch_items(SimpleNamespace())
    assert items and all(i["source"] == "github_trending" for i in items)
