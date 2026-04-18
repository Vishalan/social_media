"""
AI-driven b-roll type selector.

Uses Claude (haiku) to analyze topic title, URL, and script content
and return the highest-engagement b-roll type for that specific topic.
"""

from __future__ import annotations

import json
import logging
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
Fallback: pick a different type if primary fails (never pick the same type twice).\
"""

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
    },
    "required": ["primary", "fallback"],
    "additionalProperties": False,
}

_SAFE_DEFAULT = ["image_montage", "ai_video"]


class BrollSelector:
    """Select the highest-engagement b-roll type for a given topic using Claude Haiku."""

    def __init__(self, anthropic_client: AsyncAnthropic) -> None:
        self._client = anthropic_client

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

    async def select(
        self,
        topic_title: str,
        topic_url: str,
        script_text: str,
        extracted_article: dict | None = None,
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
            return [data["primary"], data["fallback"]]
        except Exception as exc:
            logger.warning(
                "BrollSelector: Claude call failed (%s). Using safe default %s.",
                exc,
                _SAFE_DEFAULT,
            )
            return list(_SAFE_DEFAULT)
