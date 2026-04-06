"""
Headline generation for thumbnails.

Generates a punchy 3-5 word ALL CAPS headline from a script using Claude Haiku,
suitable for an Instagram Reels thumbnail.
"""

import logging
import os
import re
import string
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

_PROMPT = """Read the following short video script and write EXACTLY one headline \
for an Instagram Reels thumbnail.

Requirements:
- EXACTLY 3 to 5 words
- ALL CAPS
- Punctuation: NONE except for periods inside version numbers and hyphens \
inside model names (see below)
- No quotes, no preamble, no explanation, no labels
- Output ONLY the headline itself on a single line
- CRITICAL: Preserve product names, brand names, and proper nouns from the \
script EXACTLY as written. Do not substitute, abbreviate, or "correct" them. \
If the script says "Veo" do NOT write "Vevo". If it says "Claude Opus" do NOT \
write "Claude".
- CRITICAL: Version numbers and model names must keep their internal punctuation. \
"3.1" must NOT become "3 1" or "31". "4.6" must NOT become "4 6" or "46". \
"GPT-4" must NOT become "GPT 4". Write version numbers as a SINGLE TOKEN with \
the period intact: "VEO 3.1", "CLAUDE 4.6", "GPT-4".{must_include_clause}

Script:
\"\"\"
{script}
\"\"\"
"""

_VERSION_PATTERN = re.compile(r"\b[A-Za-z]+\s+(\d+\.\d+)\b|(\d+\.\d+)")


_PROPER_NOUN_PATTERN = re.compile(r"\b[A-Z][A-Za-z0-9]{2,}\b")
# Common stopwords that look like proper nouns at sentence starts but aren't
_STOPWORD_PROPER = {
    "The", "This", "That", "These", "Those", "And", "But", "For", "With",
    "From", "Into", "About", "After", "Before", "When", "Where", "Why",
    "How", "What", "Who", "Which", "While", "Just", "Now", "Here", "There",
    "Like", "You", "Your", "They", "Their", "Will", "Have", "Has", "Had",
    "Can", "Could", "Would", "Should", "Been", "Being", "Does", "Did",
    "Are", "Was", "Were", "Hold", "Honestly",
}

# Generic parent brands handled by the logo badge — the headline doesn't need to
# preserve these because they're already visually represented. We force the
# specific product name (Veo, Claude, Opus, Llama, etc.) to survive instead.
_GENERIC_BRANDS_LOWER = {
    "google", "openai", "anthropic", "meta", "microsoft", "apple", "nvidia",
    "amazon", "aws", "netflix", "tesla", "spacex", "tiktok", "instagram",
    "youtube", "github", "deepmind", "mistral", "perplexity", "midjourney",
    "runway", "cohere", "vercel", "supabase", "cloudflare", "databricks",
    "snowflake",
}


def _extract_must_include(script_text: str, max_terms: int = 3) -> list[str]:
    """Extract the specific product/proper-noun terms from a script.

    Returns up to N capitalized terms in first-occurrence order, excluding:
    - sentence-start stopwords
    - generic parent brands that the logo badge already represents
      (so "Veo" survives instead of "Google")
    """
    seen: dict[str, int] = {}
    for m in _PROPER_NOUN_PATTERN.finditer(script_text):
        word = m.group(0)
        if word in _STOPWORD_PROPER:
            continue
        if word.lower() in _GENERIC_BRANDS_LOWER:
            continue
        if word not in seen:
            seen[word] = m.start()
    ordered = sorted(seen.items(), key=lambda kv: kv[1])
    return [w for w, _ in ordered[:max_terms]]


def _clean(text: str) -> str:
    """Strip whitespace, surrounding quotes, and unwanted punctuation; uppercase.

    Preserves periods and hyphens INSIDE alphanumeric tokens so version numbers
    and model names survive: "Veo 3.1" → "VEO 3.1", "GPT-4" → "GPT-4".
    Strips other punctuation entirely.
    """
    if text is None:
        return ""
    cleaned = text.strip()
    # Strip surrounding quotes (single, double, smart) repeatedly
    quote_chars = "\"'`\u2018\u2019\u201c\u201d"
    while len(cleaned) >= 2 and cleaned[0] in quote_chars and cleaned[-1] in quote_chars:
        cleaned = cleaned[1:-1].strip()
    # Strip all punctuation EXCEPT . and - (which we handle next)
    keep = {".", "-"}
    to_strip = "".join(c for c in (string.punctuation + "\u2018\u2019\u201c\u201d") if c not in keep)
    cleaned = cleaned.translate(str.maketrans("", "", to_strip))
    # Periods/hyphens are only kept when they sit between alphanumerics (e.g. "3.1", "GPT-4").
    # Strip them when they're at word boundaries or stand alone (e.g. "VEO." or "- HELLO").
    cleaned = re.sub(r"(?<![A-Za-z0-9])[.\-]+", " ", cleaned)
    cleaned = re.sub(r"[.\-]+(?![A-Za-z0-9])", " ", cleaned)
    # Collapse internal whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.upper()


def _is_valid(headline: str) -> bool:
    if not headline:
        return False
    words = headline.split()
    return 2 <= len(words) <= 6


def generate_headline(
    script_text: str,
    client: Optional[anthropic.Anthropic] = None,
    model: str = DEFAULT_MODEL,
) -> str:
    """
    Generate a 3-5 word ALL CAPS headline from a script.

    Args:
        script_text: The source script text.
        client: An optional Anthropic client. If None, one is constructed
            from the ANTHROPIC_API_KEY environment variable.
        model: The Claude model to use.

    Returns:
        A cleaned, validated, ALL CAPS headline string.

    Raises:
        ValueError: If the script is empty/whitespace, or if the model
            fails to produce a valid headline after one retry.
    """
    if not script_text or not script_text.strip():
        raise ValueError("script_text must be non-empty")

    if client is None:
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Auto-extract proper nouns from the script that MUST survive into the headline
    must_include = _extract_must_include(script_text)
    # Also extract version numbers (e.g. "3.1", "4.6") — these must appear with the period
    version_numbers = sorted({m.group(1) or m.group(2) for m in _VERSION_PATTERN.finditer(script_text)} - {None})
    must_include_versions = [v for v in version_numbers if v]

    must_clauses = []
    if must_include:
        must_clauses.append(
            "The following product/brand terms from the script MUST appear in the "
            "headline EXACTLY as spelled (at least one of them): " + ", ".join(must_include)
        )
    if must_include_versions:
        must_clauses.append(
            "The following version numbers MUST appear in the headline EXACTLY as "
            "written, with the period intact: " + ", ".join(must_include_versions)
        )
    clause = ("\n- " + "\n- ".join(must_clauses)) if must_clauses else ""

    prompt = _PROMPT.format(script=script_text.strip(), must_include_clause=clause)

    upper_must_include = [t.upper() for t in must_include]
    # Version numbers are already in canonical form (digits + period)
    required_versions = list(must_include_versions)

    last_raw = ""
    for attempt in range(2):
        response = client.messages.create(
            model=model,
            max_tokens=50,
            temperature=0.4,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        last_raw = raw
        cleaned = _clean(raw)
        if not _is_valid(cleaned):
            logger.warning(
                "Invalid headline shape on attempt %d: %r (cleaned: %r)",
                attempt + 1, raw, cleaned,
            )
            continue
        # If we extracted proper nouns from the script, at least one must appear
        if upper_must_include and not any(term in cleaned for term in upper_must_include):
            logger.warning(
                "Headline missing required terms %s on attempt %d: %r",
                upper_must_include, attempt + 1, cleaned,
            )
            continue
        # Version numbers must survive verbatim with the period
        if required_versions and not all(v in cleaned for v in required_versions):
            logger.warning(
                "Headline missing required version(s) %s on attempt %d: %r",
                required_versions, attempt + 1, cleaned,
            )
            continue
        return cleaned

    raise ValueError(f"Failed to generate valid headline after retry. Last output: {last_raw!r}")
