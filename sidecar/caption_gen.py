"""
Caption + hashtag generator for CommonCreed pipeline.

Produces platform-aware captions and hashtags for Instagram and YouTube Shorts
from a completed video script. Uses a single Claude Sonnet call with a strict
JSON contract, validates the result post-hoc, retries once with a stricter
prompt, and falls back to a deterministic output on persistent failure.

This module NEVER raises out — ``generate_captions`` always returns a
usable dict, even on catastrophic LLM failure. Failure isolation is important
because captions are called from the pipeline runner (Unit 4) and we don't
want caption-gen hiccups to nuke an otherwise-complete video run.

Output shape::

    {
        "instagram": {"caption": str, "hashtags": [str, ...]},
        "youtube":   {"title": str, "description": str, "hashtags": [str, ...]},
    }

The YouTube credit line (``Credit: @vishalangharat``) is appended to
``youtube.description`` AFTER validation, so the LLM cannot drop it. This is
the R12 guarantee.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

import anthropic

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-6"

# Hard limits enforced on the LLM output (pre-credit-line append).
IG_CAPTION_MAX = 125
YT_TITLE_MAX = 100
YT_DESCRIPTION_MAX = 500  # internal budget; credit line appended after
HASHTAG_MIN = 5
HASHTAG_MAX = 10

BRAND_TAG = "#commoncreed"
YT_CREDIT_LINE = "\n\nCredit: @vishalangharat"

# Deterministic fallback hashtag set used when the LLM can't produce a valid
# response twice in a row. Always includes the brand tag.
_FALLBACK_HASHTAGS = ["#commoncreed", "#ai", "#tech", "#news", "#reels"]


_BASE_PROMPT = """You are writing social media captions for CommonCreed, a \
faceless AI news channel that posts short-form vertical videos about AI and \
tech.

Given the script and headline below, produce captions + hashtags for \
Instagram Reels and YouTube Shorts.

Output STRICT JSON matching EXACTLY this shape, with no preamble, no \
markdown fences, no explanation — only the JSON object:

{{
  "instagram": {{
    "caption": "<string, MAX {ig_cap_max} characters>",
    "hashtags": ["#tag1", "#tag2", ...]
  }},
  "youtube": {{
    "title": "<string, MAX {yt_title_max} characters>",
    "description": "<string, MAX {yt_desc_max} characters>",
    "hashtags": ["#tag1", "#tag2", ...]
  }}
}}

HARD CONSTRAINTS (violating these will cause rejection):
- instagram.caption: AT MOST {ig_cap_max} characters (this is the above-the-fold visible portion)
- instagram.hashtags: between {h_min} and {h_max} items
- youtube.title: AT MOST {yt_title_max} characters
- youtube.description: AT MOST {yt_desc_max} characters (leave ~60 chars of budget; a credit line will be appended programmatically)
- youtube.hashtags: between {h_min} and {h_max} items
- EVERY hashtag MUST start with "#" and MUST NOT contain spaces
- EVERY hashtag MUST be a single token (letters/numbers only after the #)
- The tag "#commoncreed" MUST be present in BOTH instagram.hashtags AND youtube.hashtags
- Preserve product names, brand names, and version numbers EXACTLY as they appear in the script. Do not "correct" spellings or drop periods inside version numbers (e.g. "Veo 3.1" must stay "Veo 3.1", not "Veo 31").

Headline: {headline}

Script:
\"\"\"
{script}
\"\"\"{topic_clause}

Return ONLY the JSON object. No other text."""


_STRICTER_SUFFIX = """

CRITICAL — your previous attempt FAILED validation. Re-read the constraints \
above carefully. In particular:
- Count characters in instagram.caption — it MUST be <= {ig_cap_max}.
- Count characters in youtube.title — it MUST be <= {yt_title_max}.
- Count characters in youtube.description — it MUST be <= {yt_desc_max}.
- Count hashtags in each list — each list MUST have between {h_min} and {h_max} items.
- Every hashtag MUST start with # and contain no spaces.
- #commoncreed MUST appear in BOTH hashtag lists.

Output ONLY the JSON object."""


def _build_prompt(
    script_text: str,
    headline: str,
    topic_url: Optional[str],
    stricter: bool,
) -> str:
    topic_clause = f"\n\nSource article: {topic_url}" if topic_url else ""
    prompt = _BASE_PROMPT.format(
        ig_cap_max=IG_CAPTION_MAX,
        yt_title_max=YT_TITLE_MAX,
        yt_desc_max=YT_DESCRIPTION_MAX,
        h_min=HASHTAG_MIN,
        h_max=HASHTAG_MAX,
        headline=headline,
        script=script_text.strip(),
        topic_clause=topic_clause,
    )
    if stricter:
        prompt += _STRICTER_SUFFIX.format(
            ig_cap_max=IG_CAPTION_MAX,
            yt_title_max=YT_TITLE_MAX,
            yt_desc_max=YT_DESCRIPTION_MAX,
            h_min=HASHTAG_MIN,
            h_max=HASHTAG_MAX,
        )
    return prompt


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json(raw: str) -> Optional[dict]:
    """Best-effort JSON extraction. Returns None on any failure."""
    if not raw:
        return None
    text = raw.strip()
    # Strip common markdown code fences.
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Try extracting the first {...} block.
    m = _JSON_OBJECT_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except (json.JSONDecodeError, TypeError):
        return None


def _validate_hashtags(tags: Any) -> bool:
    if not isinstance(tags, list):
        return False
    if not (HASHTAG_MIN <= len(tags) <= HASHTAG_MAX):
        return False
    for t in tags:
        if not isinstance(t, str):
            return False
        if not t.startswith("#"):
            return False
        if " " in t or "\t" in t or "\n" in t:
            return False
        if len(t) < 2:
            return False
    return True


def _has_brand_tag(tags: list) -> bool:
    return any(isinstance(t, str) and t.lower() == BRAND_TAG for t in tags)


def _validate(payload: Any) -> Optional[str]:
    """Return an error string if invalid, or None if valid."""
    if not isinstance(payload, dict):
        return "payload is not a dict"
    ig = payload.get("instagram")
    yt = payload.get("youtube")
    if not isinstance(ig, dict) or not isinstance(yt, dict):
        return "missing instagram/youtube dicts"

    ig_caption = ig.get("caption")
    if not isinstance(ig_caption, str) or not ig_caption.strip():
        return "instagram.caption missing or empty"
    if len(ig_caption) > IG_CAPTION_MAX:
        return f"instagram.caption too long ({len(ig_caption)} > {IG_CAPTION_MAX})"

    ig_tags = ig.get("hashtags")
    if not _validate_hashtags(ig_tags):
        return "instagram.hashtags failed format/count validation"
    if not _has_brand_tag(ig_tags):
        return "instagram.hashtags missing #commoncreed"

    yt_title = yt.get("title")
    if not isinstance(yt_title, str) or not yt_title.strip():
        return "youtube.title missing or empty"
    if len(yt_title) > YT_TITLE_MAX:
        return f"youtube.title too long ({len(yt_title)} > {YT_TITLE_MAX})"

    yt_desc = yt.get("description")
    if not isinstance(yt_desc, str):
        return "youtube.description missing"
    if len(yt_desc) > YT_DESCRIPTION_MAX:
        return f"youtube.description too long ({len(yt_desc)} > {YT_DESCRIPTION_MAX})"

    yt_tags = yt.get("hashtags")
    if not _validate_hashtags(yt_tags):
        return "youtube.hashtags failed format/count validation"
    if not _has_brand_tag(yt_tags):
        return "youtube.hashtags missing #commoncreed"

    return None


def _normalize(payload: dict) -> dict:
    """Return a clean dict with only the expected keys."""
    ig = payload["instagram"]
    yt = payload["youtube"]
    return {
        "instagram": {
            "caption": ig["caption"],
            "hashtags": list(ig["hashtags"]),
        },
        "youtube": {
            "title": yt["title"],
            "description": yt["description"],
            "hashtags": list(yt["hashtags"]),
        },
    }


def _deterministic_fallback(headline: str) -> dict:
    """Last-resort output when the LLM fails us twice."""
    # Clamp headline to the strictest limit so it's safe in every slot.
    safe_headline = (headline or "CommonCreed").strip()
    if len(safe_headline) > IG_CAPTION_MAX:
        safe_headline = safe_headline[:IG_CAPTION_MAX].rstrip()
    yt_title = safe_headline if len(safe_headline) <= YT_TITLE_MAX else safe_headline[:YT_TITLE_MAX].rstrip()
    return {
        "instagram": {
            "caption": safe_headline,
            "hashtags": list(_FALLBACK_HASHTAGS),
        },
        "youtube": {
            "title": yt_title,
            "description": "",
            "hashtags": list(_FALLBACK_HASHTAGS),
        },
    }


def _append_credit_line(payload: dict) -> dict:
    """Append the R12 credit line to youtube.description.

    This happens AFTER validation so the LLM cannot drop or mangle the credit.
    The final description may exceed the internal 500-char budget by the
    length of the credit line — that's acceptable because 500 is an internal
    preferred budget, not a platform hard limit (YouTube allows 5000).
    """
    payload["youtube"]["description"] = (
        payload["youtube"]["description"] + YT_CREDIT_LINE
    )
    return payload


def generate_captions(
    script_text: str,
    headline: str,
    topic_url: Optional[str] = None,
    client: Optional[anthropic.Anthropic] = None,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Generate IG + YT captions and hashtags for a completed video.

    Never raises out — on catastrophic failure, returns a deterministic
    fallback dict built from ``headline``.
    """
    if client is None:
        try:
            client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        except Exception as e:  # pragma: no cover - defensive
            logger.exception("Failed to construct Anthropic client: %s", e)
            return _append_credit_line(_deterministic_fallback(headline))

    for attempt in range(2):
        stricter = attempt > 0
        prompt = _build_prompt(script_text or "", headline or "", topic_url, stricter)
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                temperature=0.5,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text
        except Exception as e:
            logger.warning(
                "caption_gen LLM call failed on attempt %d: %s", attempt + 1, e
            )
            continue

        parsed = _parse_json(raw)
        if parsed is None:
            logger.warning(
                "caption_gen JSON parse failed on attempt %d: %r", attempt + 1, raw[:200]
            )
            continue

        err = _validate(parsed)
        if err is not None:
            logger.warning(
                "caption_gen validation failed on attempt %d: %s", attempt + 1, err
            )
            continue

        return _append_credit_line(_normalize(parsed))

    logger.warning("caption_gen falling back to deterministic output for headline %r", headline)
    return _append_credit_line(_deterministic_fallback(headline))
