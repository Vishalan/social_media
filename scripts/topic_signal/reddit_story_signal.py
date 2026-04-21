"""Reddit topic-signal source for story-channel niches (Vesper, future).

Fetches top posts from a configured list of subreddits via Reddit's
public JSON API (no auth). Returns :class:`TopicSignal` objects that
carry title + engagement metadata only — never ``selftext``/``body``.

Contract (enforced by Unit 6 tests):
  * The post body JSON field is never read, stored, or returned.
  * Titles are canonicalized at ingest (Security Posture S5): strip
    control characters (``\\x00-\\x1F`` + ``\\x7F``), strip ANSI CSI
    sequences, NFKC-normalize Unicode, strip the Unicode-tag range
    ``U+E0000..U+E007F``, strip zero-width joiners, truncate to 300 chars.
  * Dedup flows through :class:`AnalyticsTracker` with the caller's
    ``channel_id`` and configurable window (Vesper passes 180 days).

Rank heuristic:
    ``score * log(num_comments + 1) * subreddit_weight``
Subreddits unknown to ``subreddit_weights`` default to 1.0.

Rate-limit courtesy: 2-second delay between subreddit fetches. Per
``nas-pipeline-bringup-gotchas`` / ``commoncreed-pipeline-expansion``:
403 errors from Reddit retry once with exponential backoff before
returning what we have.
"""

from __future__ import annotations

import logging
import math
import re
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from ._types import TopicSignal

logger = logging.getLogger(__name__)


# ─── Title canonicalization (Security Posture S5) ──────────────────────────

MAX_TITLE_LEN = 300

# Control chars: C0 (\x00-\x1F) + DEL (\x7F). Kept separate from the
# Unicode-tag range so the regex stays readable.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1F\x7F]+")

# ANSI CSI escape sequences (\x1b[...m style — already partially caught
# by control chars but the trailing parameter byte isn't; catch the
# whole thing explicitly).
_ANSI_CSI_RE = re.compile(r"\x1b\[[\x30-\x3F]*[\x20-\x2F]*[\x40-\x7E]")

# Zero-width joiners / formatters we strip even when inside a title.
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060-\u206f\ufeff]")

# Unicode tag range U+E0000..U+E007F — used in prompt-injection attacks
# that smuggle hidden instructions into visually-empty text.
def _strip_unicode_tags(text: str) -> str:
    return "".join(
        ch for ch in text
        if not (0xE0000 <= ord(ch) <= 0xE007F)
    )


def canonicalize_title(raw: str) -> str:
    """Canonicalize a raw Reddit title before it touches storage/logs/LLM.

    Pipeline (in order):
      1. NFKC Unicode normalization (compatibility decomposition + compose).
      2. Strip Unicode-tag range U+E0000..U+E007F.
      3. Strip zero-width joiners/formatters.
      4. Strip ANSI CSI escapes.
      5. Strip C0 control chars + DEL.
      6. Collapse whitespace to single spaces.
      7. Truncate to :data:`MAX_TITLE_LEN` chars.
    """
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", raw)
    text = _strip_unicode_tags(text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _ANSI_CSI_RE.sub("", text)
    text = _CONTROL_CHARS_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:MAX_TITLE_LEN]


# ─── Rank heuristic ─────────────────────────────────────────────────────────


def _rank_score(
    score: int,
    num_comments: int,
    subreddit: str,
    subreddit_weights: Dict[str, float],
) -> float:
    """Combined ranking — per plan Unit 6 Approach."""
    weight = subreddit_weights.get(subreddit, 1.0)
    return score * math.log(num_comments + 1) * weight


# ─── Source ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RedditStorySignalConfig:
    subreddits: Sequence[str]
    min_score: int = 500
    time_filter: str = "day"  # day/week/month/year/all
    limit: int = 10           # per-subreddit fetch size
    user_agent: str = "VesperBot/0.1 (topic signal crawler)"
    subreddit_weights: Optional[Dict[str, float]] = None
    # Seconds to wait between subreddit fetches — rate-limit courtesy.
    fetch_delay_s: float = 2.0
    request_timeout_s: float = 15.0


class RedditStorySignalSource:
    """Fetch + dedup + rank top-post signals across multiple subreddits.

    The source is stateless apart from its configuration; dedup state
    lives in the caller-supplied :class:`AnalyticsTracker`.
    """

    def __init__(self, config: RedditStorySignalConfig) -> None:
        self.config = config

    def fetch_topic_candidates(
        self,
        tracker: Any,                  # AnalyticsTracker — imported lazily
        *,
        channel_id: str,
        window_days: int = 180,
        top_n: int = 5,
        sleep_fn=time.sleep,           # injectable for tests
        http_client_factory=None,      # injectable for tests
    ) -> List[TopicSignal]:
        """Return up to ``top_n`` deduped, ranked :class:`TopicSignal` objects.

        Args:
            tracker: :class:`AnalyticsTracker` for dedup (calls
                ``is_duplicate_topic`` + ``record_news_item`` scoped to
                ``channel_id`` / ``window_days``).
            channel_id: Scope key for dedup. Vesper passes ``"vesper"``.
            window_days: Dedup lookback (Vesper: 180 days).
            top_n: Max candidates to return after dedup + rank.
            sleep_fn: Injectable sleeper for tests.
            http_client_factory: Injectable httpx-client factory for tests.
        """
        candidates: List[TopicSignal] = []
        for idx, sub in enumerate(self.config.subreddits):
            if idx > 0:
                sleep_fn(self.config.fetch_delay_s)
            candidates.extend(
                self._fetch_one_subreddit(sub, http_client_factory=http_client_factory)
            )

        if not candidates:
            logger.warning(
                "RedditStorySignalSource: zero candidates across %d subreddits",
                len(self.config.subreddits),
            )
            return []

        # Dedup against analytics history BEFORE ranking — saves a few
        # tracker calls on signals we'd never return anyway.
        deduped = [
            c for c in candidates
            if not tracker.is_duplicate_topic(
                c.source_url, c.title,
                channel_id=channel_id,
                window_days=window_days,
            )
        ]

        weights = self.config.subreddit_weights or {}
        deduped.sort(
            key=lambda c: _rank_score(
                c.score, c.num_comments, c.subreddit, weights,
            ),
            reverse=True,
        )

        top = deduped[:top_n]

        # Record the picks so the next run dedups against them.
        for sig in top:
            tracker.record_news_item(
                sig.source_url, sig.title, channel_id=channel_id,
            )

        logger.info(
            "RedditStorySignalSource: %d raw / %d deduped / %d returned "
            "(channel=%s, window=%dd)",
            len(candidates), len(deduped), len(top), channel_id, window_days,
        )
        return top

    # ─── HTTP ──────────────────────────────────────────────────────────────

    def _fetch_one_subreddit(
        self,
        subreddit: str,
        *,
        http_client_factory=None,
    ) -> List[TopicSignal]:
        """Fetch one subreddit's top page. Returns [] on error."""
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            logger.error("httpx not installed: %s", exc)
            return []

        url = (
            f"https://www.reddit.com/r/{subreddit}/top.json"
            f"?t={self.config.time_filter}&limit={self.config.limit}"
        )
        headers = {"User-Agent": self.config.user_agent}

        if http_client_factory is None:
            http_client_factory = lambda: httpx.Client(  # noqa: E731
                timeout=self.config.request_timeout_s,
                follow_redirects=True,
            )

        data: Optional[Dict[str, Any]] = None
        attempts = 0
        while attempts < 2:
            attempts += 1
            try:
                with http_client_factory() as client:
                    r = client.get(url, headers=headers)
                    if r.status_code == 200:
                        data = r.json()
                        break
                    if r.status_code in (403, 429) and attempts < 2:
                        wait_s = 2 ** attempts
                        logger.warning(
                            "Reddit %s returned %d; retry in %ds",
                            subreddit, r.status_code, wait_s,
                        )
                        time.sleep(wait_s)
                        continue
                    logger.warning(
                        "Reddit %s returned non-200: %d", subreddit, r.status_code
                    )
                    return []
            except Exception as exc:
                logger.warning(
                    "Reddit %s fetch failed (attempt %d): %s",
                    subreddit, attempts, exc,
                )
                return []

        if not data:
            return []

        children = (data.get("data") or {}).get("children") or []
        results: List[TopicSignal] = []
        for child in children:
            post = (child or {}).get("data") or {}
            sig = self._to_signal(post, subreddit)
            if sig is not None:
                results.append(sig)
        return results

    # ─── Post → TopicSignal ────────────────────────────────────────────────

    def _to_signal(self, post: Dict[str, Any], subreddit: str) -> Optional[TopicSignal]:
        """Convert a raw Reddit post JSON to a :class:`TopicSignal`.

        **Does NOT read** ``post["selftext"]`` / ``post["body"]`` — that
        would violate the signal-only contract. A test enforces this at
        the attribute-access level.
        """
        if post.get("over_18"):
            return None
        if post.get("stickied"):
            return None

        score = int(post.get("score") or 0)
        if score < self.config.min_score:
            return None

        raw_title = (post.get("title") or "").strip()
        title = canonicalize_title(raw_title)
        if not title:
            return None

        permalink = post.get("permalink") or ""
        if not permalink:
            return None
        source_url = "https://reddit.com" + permalink

        return TopicSignal(
            source="reddit",
            source_url=source_url,
            subreddit=subreddit,
            title=title,
            score=score,
            num_comments=int(post.get("num_comments") or 0),
            fetched_at=datetime.utcnow(),
        )


__all__ = [
    "MAX_TITLE_LEN",
    "RedditStorySignalConfig",
    "RedditStorySignalSource",
    "canonicalize_title",
]
