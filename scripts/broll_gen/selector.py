"""
AI-driven b-roll type selector.

Uses Claude (haiku) to analyze topic title, URL, and script content
and return the highest-engagement b-roll type for that specific topic.
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

_VALID_TYPES = frozenset(
    ["browser_visit", "image_montage", "code_walkthrough", "stats_card",
     "headline_burst", "ai_video", "stock_video",
     "phone_highlight", "tweet_reveal", "split_screen", "cinematic_chart"]
)

_SYSTEM_PROMPT = """\
You select the most engaging subordinate footage type for an AI & Technology short-form video.
Types and when to use them:
- browser_visit: topic has a real article URL worth visiting (not YouTube/Twitter/social)
- code_walkthrough: topic involves API, model, framework, SDK, "how to use X", or a code release
- stats_card: script has 2+ NUMERIC stats/benchmarks (e.g. "15x faster", "60% cheaper", "82 tokens/s")
- headline_burst: topic is a major announcement, dramatic claim, or "breaking news" — great for viral impact
- image_montage: general tech news, product reveal, company story; good fallback when Pexels key is available
- stock_video: cinematic real-world footage for emotional or context-setting beats; use for topics involving data centers, smartphones, keyboards, server rooms, or any scene where cinematic real-world footage reinforces the mood
- ai_video: only for abstract/speculative topics with zero concrete visuals
- phone_highlight: Vertical phone mockup of the article being narrated, with the spoken phrase highlighted in real time.
- tweet_reveal: CommonCreed-branded tweet card with animated like counter. Select when source article quotes a named person.
- split_screen: Vertical 50/50 split-screen comparison with center wipe. Select for A-vs-B topics.
- cinematic_chart: Animated bar chart / number ticker / line chart rendered by the Remotion sidecar. Gated by CINEMATIC_CHART_ENABLED env flag and numeric-density signal.

Priority rule: stats_card beats headline_burst only when there are clear numeric comparisons.
headline_burst beats image_montage for high-impact announcements.
stock_video beats image_montage for topics with strong cinematic real-world visual potential.

Primary: pick the highest-engagement type for this specific topic.
Fallback: pick a different type if primary fails (never pick the same type twice).

Split-screen detection (optional — emit only when the topic is fundamentally \
an A-vs-B comparison between two named entities):
If, and only if, the topic is fundamentally a comparison between two named entities, \
also populate ``split_screen_pair`` with one generator per side.
Detection signals: " vs ", "X versus Y", two named models/products in the title, \
"before vs after", "A beats B", or side-by-side benchmark comparisons.
Generator types for each side are restricted to {browser_visit, image_montage, stats_card}.
If the topic is not a comparison, OMIT the ``split_screen_pair`` key entirely from your JSON output (do NOT emit ``null``).

Tweet-quote detection (optional — emit only when the source article quotes a \
named person directly):
If, and only if, the article contains a direct quote attributed to a named \
person, also populate ``tweet_quote`` with \
``{author, handle, body, like_count_estimate, verified}``:
  - ``author``: the full display name of the person being quoted.
  - ``handle``: best-guess @handle derived from the author's name; ``null`` \
if you are not confident.
  - ``body``: the quote itself, trimmed to at most ~240 characters.
  - ``like_count_estimate``: a tasteful round number in the 100–10000 range \
that reads as realistic engagement for that person.
  - ``verified``: ``true`` if the author is a widely-known public figure, \
else ``false``.
If no direct quote attributed to a named person is present, OMIT the \
``tweet_quote`` key entirely from your JSON output (do NOT emit ``null``).\
"""

# Sub-schema for ``tweet_quote`` — emitted only when the article contains a
# direct quote attributed to a named person (Unit B1). Mirrors the
# ``split_screen_pair`` additive-only pattern; when no quote is present the
# field is ``null``.
_TWEET_QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "author": {
            "type": "string",
            "description": "Full display name of the quoted person.",
        },
        "handle": {
            "type": ["string", "null"],
            "description": (
                "Best-guess @handle (without the leading '@') derived from "
                "the author's name, or null if unknown."
            ),
        },
        "body": {
            "type": "string",
            "description": "The quoted text (≤ ~240 chars).",
        },
        "like_count_estimate": {
            "type": "integer",
            # Anthropic's constrained decoding rejects integer minimum/maximum.
            # The 100..10000 range is enforced in the system-prompt instructions
            # + clamped at use-site, not in the JSON schema.
            "description": (
                "Tasteful round number for the animated like counter "
                "(aim for 100..10000)."
            ),
        },
        "verified": {"type": "boolean"},
    },
    "required": ["author", "body", "like_count_estimate", "verified"],
    "additionalProperties": False,
}


# Side-generator enum for ``split_screen_pair`` — restricted per Unit B2
# spec to the generators that support ``width_override``.
_SPLIT_SIDE_GEN_ENUM = ["browser_visit", "image_montage", "stats_card"]

# Sub-schema for one side of a split_screen_pair. Each side names a generator
# and carries free-form ``params`` (Haiku fills these with topic/script
# overrides so each side can narrate its own entity).
_SPLIT_SIDE_SCHEMA = {
    "type": "object",
    "properties": {
        "generator_type": {
            "type": "string",
            "enum": _SPLIT_SIDE_GEN_ENUM,
        },
        # Anthropic's constrained-decoding rejects additionalProperties: true,
        # so we declare the two known optional sub-objects explicitly and set
        # additionalProperties: false. Haiku can still emit topic/script with
        # their own free-form contents — we just can't accept *arbitrary*
        # sibling keys here.
        "params": {
            "type": "object",
            "description": (
                "Optional per-side overrides: topic (dict with title/url) "
                "and script (dict with script text)."
            ),
            "properties": {
                "topic": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "script": {
                    "type": "object",
                    "properties": {
                        "script": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
    },
    "required": ["generator_type"],
    "additionalProperties": False,
}

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "primary": {
            "type": "string",
            "enum": [
                "browser_visit",
                "image_montage",
                "code_walkthrough",
                "stats_card",
                "headline_burst",
                "stock_video",
                "ai_video",
                "phone_highlight",
                "tweet_reveal",
                "split_screen",
                "cinematic_chart",
            ],
        },
        "fallback": {
            "type": "string",
            "enum": [
                "browser_visit",
                "image_montage",
                "code_walkthrough",
                "stats_card",
                "headline_burst",
                "stock_video",
                "ai_video",
                "phone_highlight",
                "tweet_reveal",
                "split_screen",
                "cinematic_chart",
            ],
        },
        # Unit B2 — optional: populated only when the topic is an A-vs-B
        # comparison between two named entities. Callers lift this onto
        # VideoJob.split_screen_pair so the split_screen generator is gated
        # by the presence of this field.
        # Anthropic's constrained-decoding schema rejects ``oneOf`` — we
        # express "null or object" by keeping the key out of ``required``
        # and instructing Haiku to omit it when absent.
        "split_screen_pair": {
            "type": "object",
            "properties": {
                "left": _SPLIT_SIDE_SCHEMA,
                "right": _SPLIT_SIDE_SCHEMA,
            },
            "required": ["left", "right"],
            "additionalProperties": False,
        },
        # Unit B1 — optional: populated only when the source article contains
        # a direct quote attributed to a named person. Callers lift this onto
        # VideoJob.tweet_quote so the tweet_reveal generator is gated by the
        # presence of this field. Same omit-when-absent pattern as
        # split_screen_pair (no ``oneOf``).
        "tweet_quote": _TWEET_QUOTE_SCHEMA,
    },
    "required": ["primary", "fallback"],
    "additionalProperties": False,
}

_SAFE_DEFAULT = ["image_montage", "ai_video"]


class BrollSelector:
    """Select the highest-engagement b-roll type for a given topic using Claude Haiku."""

    def __init__(self, anthropic_client: AsyncAnthropic) -> None:
        self._client = anthropic_client
        # Unit B2: most-recent Haiku-emitted ``split_screen_pair`` (or None).
        # Populated as a side-effect of ``select()`` so callers can lift it
        # onto ``VideoJob.split_screen_pair`` without changing the public
        # return type of ``select()``.
        self.last_split_screen_pair: dict | None = None
        # Unit B1: most-recent Haiku-emitted ``tweet_quote`` (or None). Same
        # side-effect pattern as ``last_split_screen_pair`` — callers lift it
        # onto ``VideoJob.tweet_quote`` without changing ``select()``'s
        # return type.
        self.last_tweet_quote: dict | None = None

    @staticmethod
    def _compute_forced_primary_candidates(
        topic_url: str,
        extracted_article: dict | None,
    ) -> list[str] | None:
        """Return the forced primary-candidate list for an article URL, or None.

        When a real article URL is available, bias selection toward
        article-rooted b-roll. With an extracted article body (≥2 body
        paragraphs) we can also use ``phone_highlight``; otherwise we fall back
        to ``browser_visit`` only. Tweet / split / chart paths are gated
        separately by ``tweet_quote`` / ``split_screen_pair`` / numeric-density
        signals handled downstream (Wave-2 units).
        """
        topic_url_is_article = bool(topic_url) and not any(
            d in topic_url for d in ("youtube.com", "twitter.com", "x.com", "reddit.com")
        )
        if not topic_url_is_article:
            return None
        if extracted_article and len(extracted_article.get("body_paragraphs", [])) >= 2:
            return ["phone_highlight", "browser_visit"]
        return ["browser_visit"]

    # ── Unit C2 — cinematic_chart numeric-density gating ──────────────────
    #
    # Distinct region from ``_compute_forced_primary_candidates`` (owned by
    # Unit 0.5 + A1 short-circuit) and from B1's upcoming tweet_quote
    # detection / B2's already-merged split_screen_pair detection. Each
    # region is a standalone helper so parallel Wave-2 workers don't
    # collide inside a single function body.
    @staticmethod
    def _compute_chart_forced_candidates(
        chart_spec: dict | None,
    ) -> list[str] | None:
        """Return the forced primary-candidate list when a chart_spec is available.

        When ``job.chart_spec`` is populated AND the ``CINEMATIC_CHART_ENABLED``
        env flag is truthy, the selector prefers ``cinematic_chart`` as primary
        with ``stats_card`` as a graceful numeric fallback. Either condition
        missing → returns ``None`` so the selector falls through to the other
        gating regions (article URL, tweet quote, split screen pair).
        """
        if not chart_spec:
            return None
        if os.environ.get("CINEMATIC_CHART_ENABLED", "false").lower() != "true":
            return None
        return ["cinematic_chart", "stats_card"]

    async def select(
        self,
        topic_title: str,
        topic_url: str,
        script_text: str,
        extracted_article: dict | None = None,
        chart_spec: dict | None = None,
    ) -> list[str]:
        """Analyze the topic and script to choose primary and fallback b-roll types.

        Args:
            topic_title: The title/headline of the video topic.
            topic_url: The source URL for the topic article.
            script_text: The generated voiceover script.
            extracted_article: Optional ``ArticleExtract.to_dict()`` payload
                (see ``scripts/topic_intel/article_extractor.py``). When
                present with ≥2 ``body_paragraphs``, enables the
                ``phone_highlight`` candidate for article URLs.
            chart_spec: Optional ``{template, props, target_duration_s}`` dict
                (see ``broll_gen/cinematic_chart.py::extract_chart_spec``).
                When present AND ``CINEMATIC_CHART_ENABLED=true`` in the env,
                biases primary toward ``cinematic_chart`` with ``stats_card``
                fallback (Unit C2 gating region — distinct from the article /
                tweet / split_screen gating regions above).

        Returns:
            A 2-element list ``[primary_type, fallback_type]`` where each element
            is one of the registered b-roll type names in ``_VALID_TYPES``.
            Falls back to ``["image_montage", "ai_video"]`` on any Claude error.
        """
        forced_primary_candidates = self._compute_forced_primary_candidates(
            topic_url, extracted_article,
        )
        if forced_primary_candidates is not None:
            logger.info(
                "BrollSelector: article URL detected — forced_primary_candidates=%s",
                forced_primary_candidates,
            )

        # Unit C2: numeric-density gate — takes precedence over the article
        # short-circuit when a chart_spec is present and the env flag is on.
        # Placed additively so B1 (tweet_quote) can own its own gating region
        # below without touching this block.
        chart_forced = self._compute_chart_forced_candidates(chart_spec)
        if chart_forced is not None:
            logger.info(
                "BrollSelector: chart_spec + %s=true — forced_primary_candidates=%s",
                "CINEMATIC_CHART_ENABLED", chart_forced,
            )
            forced_primary_candidates = chart_forced

        user_prompt = (
            f"Topic: {topic_title}\n"
            f"URL: {topic_url}\n"
            f"Script excerpt (first 300 chars): {script_text[:300]}"
        )
        if forced_primary_candidates is not None:
            user_prompt += (
                f"\nConstraint: 'primary' MUST be one of "
                f"{forced_primary_candidates} (choose whichever fits best). "
                f"'fallback' must be a different type."
            )

        try:
            response = await self._client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=64,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": _RESPONSE_SCHEMA,
                    }
                },
            )
            raw = response.content[0].text
            data = json.loads(raw)
            # Lift Haiku's optional ``split_screen_pair`` onto the selector
            # instance so downstream orchestration (commoncreed_pipeline) can
            # copy it onto VideoJob without changing the return contract.
            self.last_split_screen_pair = data.get("split_screen_pair") or None
            # Same pattern for Unit B1's ``tweet_quote``.
            self.last_tweet_quote = data.get("tweet_quote") or None
            return [data["primary"], data["fallback"]]
        except Exception as exc:
            logger.warning(
                "BrollSelector: Claude call failed (%s). Using safe default %s.",
                exc,
                _SAFE_DEFAULT,
            )
            self.last_split_screen_pair = None
            self.last_tweet_quote = None
            return list(_SAFE_DEFAULT)
