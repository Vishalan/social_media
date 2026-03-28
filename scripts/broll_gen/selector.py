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
    ["browser_visit", "image_montage", "code_walkthrough", "stats_card", "ai_video"]
)

_SYSTEM_PROMPT = """\
You select the most engaging subordinate footage type for an AI & Technology short-form video.
Types and when to use them:
- browser_visit: when topic has a real article URL worth visiting (not YouTube/Twitter)
- code_walkthrough: when topic involves API, model, framework, SDK, "how to use X", code release
- stats_card: when the script contains measurable comparisons: numbers, benchmarks, speeds, costs
- image_montage: for general tech news, product releases, company announcements
- ai_video: only for abstract/speculative topics with no concrete visuals

Primary: pick the highest-engagement type.
Fallback: pick a different type to try if primary fails.\
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
