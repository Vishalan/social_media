"""Tests for :class:`RedditStorySignalSource` (Unit 6).

Mock the httpx client so tests never hit the live Reddit API. Enforces
the signal-only contract (no body ingestion) at the attribute-access
level, plus PII/control-char canonicalization and cross-channel dedup.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from datetime import datetime

# Ensure scripts/ on path.
_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from analytics.tracker import AnalyticsTracker
from topic_signal import TopicSignal
from topic_signal.reddit_story_signal import (
    MAX_TITLE_LEN,
    RedditStorySignalConfig,
    RedditStorySignalSource,
    canonicalize_title,
)


# ─── Canonicalization tests ─────────────────────────────────────────────────


class CanonicalizeTitleTests(unittest.TestCase):
    def test_passes_plain_title_through(self):
        self.assertEqual(
            canonicalize_title("Something happened last night"),
            "Something happened last night",
        )

    def test_strips_control_chars(self):
        self.assertEqual(
            canonicalize_title("Bad\x00title\x07with\x1bevils"),
            "Bad title with evils",
        )

    def test_strips_zero_width_joiners(self):
        # Zero-width space + ZWJ + ZWNJ hidden in the middle.
        raw = "Hidden\u200b\u200c\u200djoiner"
        self.assertEqual(canonicalize_title(raw), "Hiddenjoiner")

    def test_strips_unicode_tag_range(self):
        # U+E0041 (LATIN TAG A). If this slips through, prompt-injection
        # attackers can smuggle invisible instructions via Reddit titles.
        raw = "Visible\U000E0041\U000E0042\U000E0043title"
        out = canonicalize_title(raw)
        self.assertEqual(out, "Visibletitle")
        # Assert no Unicode-tag code point survived.
        for ch in out:
            self.assertFalse(
                0xE0000 <= ord(ch) <= 0xE007F,
                f"Unicode-tag char {ord(ch):#x} leaked through",
            )

    def test_strips_ansi_csi_sequences(self):
        raw = "Red\x1b[31mdanger\x1b[0mword"
        self.assertEqual(canonicalize_title(raw), "Reddangerword")

    def test_truncates_to_max_len(self):
        raw = "x" * (MAX_TITLE_LEN + 500)
        self.assertEqual(len(canonicalize_title(raw)), MAX_TITLE_LEN)

    def test_empty_string_returns_empty(self):
        self.assertEqual(canonicalize_title(""), "")

    def test_collapses_whitespace(self):
        self.assertEqual(
            canonicalize_title("A   B\t\tC\nD  E"),
            "A B C D E",
        )


# ─── TopicSignal contract ───────────────────────────────────────────────────


class TopicSignalContractTests(unittest.TestCase):
    """The TopicSignal dataclass must never carry body/selftext/content."""

    def test_topic_signal_has_no_body_field(self):
        sig = TopicSignal(
            source="reddit",
            source_url="https://reddit.com/r/nosleep/comments/x/title",
            subreddit="nosleep",
            title="A title",
            score=1234,
            num_comments=56,
            fetched_at=datetime.utcnow(),
        )
        forbidden = {"body", "selftext", "content", "author", "author_handle"}
        attrs = set(vars(sig).keys())
        self.assertFalse(
            forbidden.intersection(attrs),
            f"TopicSignal carries forbidden fields: {forbidden.intersection(attrs)}",
        )


# ─── RedditStorySignalSource — end-to-end with mocked httpx ─────────────────


def _make_mock_client_factory(payload: dict):
    """Return a factory that hands back a context-manager httpx-like
    client whose GET returns ``payload`` as JSON."""
    def factory():
        client = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = payload
        client.get.return_value = response

        # Context-manager protocol
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=client)
        cm.__exit__ = MagicMock(return_value=False)
        return cm
    return factory


def _reddit_payload(posts: list[dict]) -> dict:
    """Wrap a list of post dicts into Reddit's JSON envelope shape."""
    return {
        "data": {
            "children": [{"data": p} for p in posts],
        }
    }


def _make_post(**overrides) -> dict:
    """Canonical Reddit-post JSON with sensible defaults; overrides win."""
    base = {
        "title": "Default title",
        "score": 2000,
        "num_comments": 100,
        "permalink": "/r/nosleep/comments/x1/default/",
        "created_utc": 1714608000,
        "over_18": False,
        "stickied": False,
        # selftext INTENTIONALLY present so we can assert the source
        # doesn't read it through into TopicSignal.
        "selftext": "THIS IS THE BODY — MUST NOT LEAK",
        "author": "someuser",
    }
    base.update(overrides)
    return base


class FetchTopicCandidatesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vesper-signal-")
        self.db_path = os.path.join(self.tmp, "analytics.db")
        self.tracker = AnalyticsTracker(db_path=self.db_path)

    def tearDown(self) -> None:
        self.tracker.close()
        for p in Path(self.tmp).iterdir():
            p.unlink()
        Path(self.tmp).rmdir()

    def test_happy_path_returns_ranked_topic_signals(self):
        payload = _reddit_payload([
            _make_post(title="low engagement", score=600, num_comments=10,
                      permalink="/r/nosleep/comments/a/low/"),
            _make_post(title="high engagement", score=8000, num_comments=800,
                      permalink="/r/nosleep/comments/b/high/"),
            _make_post(title="mid engagement", score=2500, num_comments=200,
                      permalink="/r/nosleep/comments/c/mid/"),
        ])
        cfg = RedditStorySignalConfig(
            subreddits=["nosleep"], min_score=500, limit=10, fetch_delay_s=0,
        )
        src = RedditStorySignalSource(cfg)
        out = src.fetch_topic_candidates(
            self.tracker,
            channel_id="vesper",
            window_days=180,
            top_n=3,
            sleep_fn=lambda _s: None,
            http_client_factory=_make_mock_client_factory(payload),
        )
        self.assertEqual(len(out), 3)
        # Ranked descending by score * log(comments+1).
        titles = [s.title for s in out]
        self.assertEqual(titles[0], "high engagement")

    def test_never_stores_body_selftext_or_content(self):
        """TopicSignal returned from the source must NOT carry body."""
        payload = _reddit_payload([_make_post()])
        cfg = RedditStorySignalConfig(
            subreddits=["nosleep"], min_score=500, fetch_delay_s=0,
        )
        src = RedditStorySignalSource(cfg)
        out = src.fetch_topic_candidates(
            self.tracker,
            channel_id="vesper",
            window_days=180,
            top_n=1,
            sleep_fn=lambda _s: None,
            http_client_factory=_make_mock_client_factory(payload),
        )
        self.assertEqual(len(out), 1)
        attrs = vars(out[0])
        forbidden = {"body", "selftext", "content", "author", "author_handle"}
        self.assertFalse(forbidden.intersection(attrs.keys()))
        # None of the title/etc fields should contain the body text either.
        for v in attrs.values():
            if isinstance(v, str):
                self.assertNotIn("MUST NOT LEAK", v)

    def test_dedup_removes_previously_seen_urls(self):
        payload = _reddit_payload([
            _make_post(title="A", permalink="/r/nosleep/comments/aaa/a/",
                      score=3000, num_comments=300),
            _make_post(title="B", permalink="/r/nosleep/comments/bbb/b/",
                      score=4000, num_comments=400),
        ])
        # Pre-seed the tracker with one of the two URLs.
        self.tracker.record_news_item(
            "https://reddit.com/r/nosleep/comments/aaa/a/", "A",
            channel_id="vesper",
        )
        cfg = RedditStorySignalConfig(
            subreddits=["nosleep"], min_score=500, fetch_delay_s=0,
        )
        src = RedditStorySignalSource(cfg)
        out = src.fetch_topic_candidates(
            self.tracker,
            channel_id="vesper",
            window_days=180,
            top_n=5,
            sleep_fn=lambda _s: None,
            http_client_factory=_make_mock_client_factory(payload),
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "B")

    def test_dedup_is_channel_scoped(self):
        """A URL deduped for commoncreed is still fresh for vesper."""
        url = "https://reddit.com/r/nosleep/comments/zzz/z/"
        self.tracker.record_news_item(
            url, "Shared topic", channel_id="commoncreed",
        )
        payload = _reddit_payload([
            _make_post(title="Shared topic",
                      permalink="/r/nosleep/comments/zzz/z/",
                      score=3000, num_comments=300),
        ])
        cfg = RedditStorySignalConfig(
            subreddits=["nosleep"], min_score=500, fetch_delay_s=0,
        )
        src = RedditStorySignalSource(cfg)
        out = src.fetch_topic_candidates(
            self.tracker,
            channel_id="vesper",
            window_days=180,
            top_n=5,
            sleep_fn=lambda _s: None,
            http_client_factory=_make_mock_client_factory(payload),
        )
        # Vesper sees it as fresh.
        self.assertEqual(len(out), 1)

    def test_filters_nsfw_and_stickied(self):
        payload = _reddit_payload([
            _make_post(title="nsfw post", over_18=True,
                      permalink="/r/nosleep/comments/nsfw/x/"),
            _make_post(title="stickied post", stickied=True,
                      permalink="/r/nosleep/comments/sticky/x/"),
            _make_post(title="clean post",
                      permalink="/r/nosleep/comments/clean/x/"),
        ])
        cfg = RedditStorySignalConfig(
            subreddits=["nosleep"], min_score=500, fetch_delay_s=0,
        )
        src = RedditStorySignalSource(cfg)
        out = src.fetch_topic_candidates(
            self.tracker,
            channel_id="vesper",
            window_days=180,
            top_n=5,
            sleep_fn=lambda _s: None,
            http_client_factory=_make_mock_client_factory(payload),
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "clean post")

    def test_min_score_threshold(self):
        payload = _reddit_payload([
            _make_post(title="below threshold", score=100,
                      permalink="/r/nosleep/comments/low/x/"),
            _make_post(title="above threshold", score=1000,
                      permalink="/r/nosleep/comments/high/x/"),
        ])
        cfg = RedditStorySignalConfig(
            subreddits=["nosleep"], min_score=500, fetch_delay_s=0,
        )
        src = RedditStorySignalSource(cfg)
        out = src.fetch_topic_candidates(
            self.tracker,
            channel_id="vesper",
            window_days=180,
            top_n=5,
            sleep_fn=lambda _s: None,
            http_client_factory=_make_mock_client_factory(payload),
        )
        titles = [s.title for s in out]
        self.assertIn("above threshold", titles)
        self.assertNotIn("below threshold", titles)

    def test_injection_bearing_title_sanitized(self):
        """A title with hidden Unicode-tag chars must be cleaned before
        it reaches analytics / logs / the LLM."""
        payload = _reddit_payload([
            _make_post(
                title="Visible\U000E0041\U000E0049\U000E0047stuff",
                permalink="/r/nosleep/comments/inj/x/",
                score=1000,
            ),
        ])
        cfg = RedditStorySignalConfig(
            subreddits=["nosleep"], min_score=500, fetch_delay_s=0,
        )
        src = RedditStorySignalSource(cfg)
        out = src.fetch_topic_candidates(
            self.tracker,
            channel_id="vesper",
            window_days=180,
            top_n=5,
            sleep_fn=lambda _s: None,
            http_client_factory=_make_mock_client_factory(payload),
        )
        self.assertEqual(len(out), 1)
        for ch in out[0].title:
            self.assertFalse(
                0xE0000 <= ord(ch) <= 0xE007F,
                f"Unicode-tag char {ord(ch):#x} reached TopicSignal",
            )

    def test_multiple_subreddits_sleep_between(self):
        sleeps: list[float] = []
        payload = _reddit_payload([])  # no posts from either subreddit
        cfg = RedditStorySignalConfig(
            subreddits=["nosleep", "LetsNotMeet"],
            min_score=500,
            fetch_delay_s=1.5,
        )
        src = RedditStorySignalSource(cfg)
        src.fetch_topic_candidates(
            self.tracker,
            channel_id="vesper",
            window_days=180,
            top_n=5,
            sleep_fn=lambda s: sleeps.append(s),
            http_client_factory=_make_mock_client_factory(payload),
        )
        # Exactly one inter-subreddit sleep (N-1 = 1 for 2 subreddits).
        self.assertEqual(sleeps, [1.5])


class HttpErrorPathsTests(unittest.TestCase):
    """Graceful error handling for 403/500/network failures."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vesper-http-")
        self.db_path = os.path.join(self.tmp, "analytics.db")
        self.tracker = AnalyticsTracker(db_path=self.db_path)

    def tearDown(self) -> None:
        self.tracker.close()
        for p in Path(self.tmp).iterdir():
            p.unlink()
        Path(self.tmp).rmdir()

    def test_non_200_returns_empty(self):
        def _factory():
            client = MagicMock()
            response = MagicMock()
            response.status_code = 500
            client.get.return_value = response
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=client)
            cm.__exit__ = MagicMock(return_value=False)
            return cm

        cfg = RedditStorySignalConfig(
            subreddits=["nosleep"], min_score=500, fetch_delay_s=0,
        )
        src = RedditStorySignalSource(cfg)
        out = src.fetch_topic_candidates(
            self.tracker,
            channel_id="vesper",
            window_days=180,
            top_n=5,
            sleep_fn=lambda _s: None,
            http_client_factory=_factory,
        )
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
