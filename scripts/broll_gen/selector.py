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
     "headline_burst", "ai_video", "stock_video"]
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

    async def select(
        self,
        topic_title: str,
        topic_url: str,
        script_text: str,
    ) -> list[str]:
        """Analyze the topic and script to choose primary and fallback b-roll types.

        Args:
            topic_title: The title/headline of the video topic.
            topic_url: The source URL for the topic article.
            script_text: The generated voiceover script.

        Returns:
            A 2-element list ``[primary_type, fallback_type]`` where each element
            is one of: ``browser_visit``, ``image_montage``, ``code_walkthrough``,
            ``stats_card``, ``ai_video``.
            Falls back to ``["image_montage", "ai_video"]`` on any Claude error.
        """
        # Always prefer browser_visit when a real article URL is available —
        # website screenshots are the highest-engagement b-roll type.
        if topic_url and not any(
            d in topic_url for d in ("youtube.com", "twitter.com", "x.com", "reddit.com")
        ):
            logger.info("BrollSelector: forcing browser_visit (real article URL available)")
            return ["browser_visit", "headline_burst"]

        user_prompt = (
            f"Topic: {topic_title}\n"
            f"URL: {topic_url}\n"
            f"Script excerpt (first 300 chars): {script_text[:300]}"
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
