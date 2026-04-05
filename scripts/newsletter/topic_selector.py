"""
Claude-powered topic selector for the newsletter pipeline.

Given a list of articles extracted from the TLDR AI newsletter, Claude picks
the single best article for a viral @commoncreed AI tech short.

Selection criteria:
- Surprising / counter-intuitive angle
- Concrete numbers, benchmarks, comparisons
- Widely-relevant (affects many developers or consumers)
- Has enough substance for a 45-60 second script
- Avoids: pure speculation, vague "AI doing X", roundups without a hook
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a viral content strategist for @commoncreed, an AI & Technology news channel
on TikTok, Instagram Reels, and YouTube Shorts targeting developers and tech-savvy millennials.

Given a list of articles from the TLDR AI newsletter, select the single best article
to turn into a 45-60 second short-form video.

Selection criteria (in order):
1. Surprising / counter-intuitive — something that makes people say "wait, really?"
2. Concrete numbers or comparisons — benchmarks, costs, speeds, scale
3. Widely relevant — affects developers, consumers, or the AI industry broadly
4. Strong hook potential — can be teased in the first 3 seconds
5. Enough depth for 45s of content (not just a one-liner)

Avoid:
- Pure opinion pieces with no facts
- Sponsor / ad items
- Topics that are too niche or academic
- Roundup articles without a specific angle

Return the index (0-based) of the chosen article, a one-sentence reason,
and a suggested video hook (the first sentence a viewer hears).
"""

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "index": {
            "type": "integer",
            "description": "0-based index into the articles list",
        },
        "reason": {
            "type": "string",
            "description": "One sentence explaining why this article was chosen",
        },
        "hook": {
            "type": "string",
            "description": "Suggested opening hook sentence for the video (≤15 words, punchy)",
        },
    },
    "required": ["index", "reason", "hook"],
    "additionalProperties": False,
}


async def select_topic(
    articles: list[dict],
    anthropic_client: "AsyncAnthropic",
) -> dict:
    """
    Pick the best article from a newsletter list for a viral AI short.

    Args:
        articles: List of article dicts with keys: title, url, summary, section.
        anthropic_client: Async Anthropic client.

    Returns:
        The selected article dict, enriched with ``hook`` and ``selection_reason``.

    Raises:
        ValueError: If articles list is empty.
        RuntimeError: If Claude returns an out-of-range index.
    """
    if not articles:
        raise ValueError("articles list is empty")

    # Format articles for Claude
    numbered = "\n\n".join(
        f"[{i}] {a['title']}\n"
        f"Section: {a.get('section', 'Unknown')}\n"
        f"Summary: {a.get('summary', '(no summary)')[:200]}"
        for i, a in enumerate(articles)
    )

    response = await anthropic_client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=256,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Choose the best article for a viral AI tech short:\n\n{numbered}"
                ),
            }
        ],
        output_config={
            "format": {
                "type": "json_schema",
                "schema": _RESPONSE_SCHEMA,
            }
        },
    )

    data = json.loads(response.content[0].text)
    idx = data["index"]

    if not (0 <= idx < len(articles)):
        logger.warning(
            "Claude returned out-of-range index %d (max %d), defaulting to 0",
            idx, len(articles) - 1,
        )
        idx = 0

    selected = dict(articles[idx])
    selected["hook"] = data["hook"]
    selected["selection_reason"] = data["reason"]

    logger.info(
        "Topic selected: %r — %s", selected["title"], data["reason"]
    )
    return selected
