"""
LLM-based newsletter item extraction + topic scoring.

Uses Claude Sonnet to:
  1. Parse a TLDR newsletter body into a list of stories.
  2. Score the stories on virality/novelty/thought-provocation/AI relevance
     and return the top N in posting order.

Prompt discipline follows `scripts/thumbnail_gen/headline.py`: explicit JSON
rules in the prompt, a strict validator, and a single retry on drift.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"

_EXTRACT_PROMPT = """You will be given the plaintext body of a TLDR AI newsletter. \
Parse it into a JSON array of stories.

OUTPUT RULES (CRITICAL):
- Output ONLY a JSON array. No preamble, no markdown code fences, no commentary.
- Each element MUST be a JSON object with EXACTLY these keys:
  "title" (string), "url" (string), "description" (string), "category" (string).
- If a field is missing from the source, use an empty string "" — do NOT omit the key.
- If the newsletter has no stories, output exactly: []
- Do NOT include section headers, sponsor slots, or the unsubscribe footer.

Newsletter body:
\"\"\"
{body}
\"\"\"
"""

_EXTRACT_RETRY_PROMPT = """Your previous response was not valid JSON. \
Output ONLY a JSON array — no markdown, no code fences, no commentary. \
Each element must have exactly the keys: title, url, description, category.

Newsletter body:
\"\"\"
{body}
\"\"\"
"""

_SCORE_PROMPT = """You are curating AI-tech stories for a short-form video channel \
(CommonCreed — AI avatar news shorts). Score each story on four axes, 1-10 each:
  - virality: will this grab attention on TikTok/Reels/Shorts?
  - novelty: is this genuinely new, not a rehash?
  - thought_provocation: does this make viewers think/debate?
  - ai_tech_relevance: how on-brand for an AI-tech channel?

Then compute score = virality + novelty + thought_provocation + ai_tech_relevance \
(an integer 4-40) and a 1-sentence rationale (max 20 words — be terse).

Return ONLY the TOP 10 items as a JSON array, sorted by score DESCENDING. \
Do NOT score or return the rest. Each element MUST have EXACTLY these keys:
  "title" (string), "url" (string), "description" (string — max 100 chars, trim if needed),
  "score" (number), "rationale" (string, max 20 words).

No markdown, no code fences, no preamble. JSON array only.

Items to score (return only the top 10 of these):
{items_json}
"""

_SCORE_RETRY_PROMPT = """Your previous response was not valid JSON or got truncated. \
Output ONLY a JSON array with the TOP 10 items, sorted by score DESCENDING. \
Each element must have exactly: title, url, description (<=100 chars), \
score (integer), rationale (<=20 words). No markdown, no code fences.

Items to score (return only the top 10):
{items_json}
"""


def _strip_code_fence(text: str) -> str:
    """Remove ```json ... ``` (or any) fences if the model wrapped the JSON.

    Handles:
      - leading ```json\\n or ```\\n
      - trailing \\n``` (with or without surrounding whitespace)
      - plain text before/after the fence
    """
    if not text:
        return text
    t = text.strip()
    # Regex-strip any ```<lang>? ... ``` block — match is greedy enough
    # to capture the entire fenced section even when there's text around it.
    m = re.search(r"```(?:json|javascript|js)?\s*\n?(.*?)\n?```", t, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback: line-based strip (older path, covers edge cases the regex
    # doesn't match like an unclosed fence)
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def _parse_json_array(raw: str) -> Optional[list]:
    if not raw:
        return None
    cleaned = _strip_code_fence(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        # Last-ditch: find the first [...] block
        m = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not m:
            return None
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, list):
        return None
    return parsed


_REQUIRED_EXTRACT_KEYS = {"title", "url", "description", "category"}
_REQUIRED_SCORE_KEYS = {"title", "url", "description", "score", "rationale"}


def _validate_extract(items: list) -> bool:
    for el in items:
        if not isinstance(el, dict):
            return False
        if not _REQUIRED_EXTRACT_KEYS.issubset(el.keys()):
            return False
    return True


def _validate_score(items: list) -> bool:
    for el in items:
        if not isinstance(el, dict):
            return False
        if not _REQUIRED_SCORE_KEYS.issubset(el.keys()):
            return False
        if not isinstance(el.get("score"), (int, float)):
            return False
    return True


def _call(
    client: Optional[anthropic.Anthropic],
    model: str,
    prompt: str,
    max_tokens: int = 8000,
    *,
    provider: str = "anthropic",
    ollama_base_url: str = "",
    anthropic_api_key: str = "",
) -> str:
    """Route an LLM call through either Anthropic SDK or the llm_client abstraction."""
    if provider == "anthropic" and client is not None:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text

    # Use llm_client for Ollama (or Anthropic without an existing client)
    from .llm_client import llm_call

    return llm_call(
        prompt,
        provider=provider,
        model=model,
        json_mode=True,  # both extract + score expect JSON output
        max_tokens=max_tokens,
        anthropic_api_key=anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", ""),
        ollama_base_url=ollama_base_url,
    )


def extract_items(
    body_text: str,
    client: Optional[anthropic.Anthropic] = None,
    model: str = DEFAULT_MODEL,
) -> list:
    """Parse a newsletter body into a list of story dicts."""
    if not body_text or not body_text.strip():
        return []

    if client is None:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    prompts = [
        _EXTRACT_PROMPT.format(body=body_text.strip()),
        _EXTRACT_RETRY_PROMPT.format(body=body_text.strip()),
    ]

    last_raw = ""
    for attempt, prompt in enumerate(prompts):
        raw = _call(client, model, prompt)
        last_raw = raw
        parsed = _parse_json_array(raw)
        if parsed is None:
            logger.warning("extract_items: JSON parse failed on attempt %d", attempt + 1)
            continue
        if not _validate_extract(parsed):
            logger.warning(
                "extract_items: schema validation failed on attempt %d", attempt + 1
            )
            continue
        return parsed

    raise ValueError(
        f"extract_items failed after retry; last raw output: {last_raw!r}"
    )


def score_topics(
    items: list,
    client: Optional[anthropic.Anthropic] = None,
    top_n: int = 2,
    model: str = DEFAULT_MODEL,
    *,
    provider: str = "anthropic",
    ollama_base_url: str = "",
    anthropic_api_key: str = "",
) -> list:
    """Score items and return the top N in posting order (highest first)."""
    if not items:
        return []

    if client is None and provider == "anthropic":
        client = anthropic.Anthropic(api_key=anthropic_api_key or os.getenv("ANTHROPIC_API_KEY"))

    items_json = json.dumps(items, ensure_ascii=False)
    prompts = [
        _SCORE_PROMPT.format(items_json=items_json),
        _SCORE_RETRY_PROMPT.format(items_json=items_json),
    ]

    last_raw = ""
    scored: Optional[list] = None
    for attempt, prompt in enumerate(prompts):
        raw = _call(
            client, model, prompt,
            provider=provider, ollama_base_url=ollama_base_url,
            anthropic_api_key=anthropic_api_key,
        )
        last_raw = raw
        parsed = _parse_json_array(raw)
        if parsed is None:
            logger.warning("score_topics: JSON parse failed on attempt %d", attempt + 1)
            continue
        if not _validate_score(parsed):
            logger.warning(
                "score_topics: schema validation failed on attempt %d", attempt + 1
            )
            continue
        scored = parsed
        break

    if scored is None:
        raise ValueError(
            f"score_topics failed after retry; last raw output: {last_raw!r}"
        )

    # Defensive: re-sort by score descending in case the model got it wrong
    scored.sort(key=lambda el: el.get("score", 0), reverse=True)
    return scored[:top_n]
