---
title: Claude Haiku drops periods in version numbers when generating headlines
category: integration-issues
date: 2026-04-06
tags: [haiku, thumbnail, headline, prompt-engineering, version-numbers, anthropic]
module: thumbnail_gen
component: headline
---

# Claude Haiku drops periods in version numbers when generating headlines

## Problem

Claude Haiku, when asked to generate a short ALL-CAPS headline from a script containing version numbers like "Veo 3.1" or "Claude 4.6", consistently outputs them as separate tokens ("VEO 3 1" or "VEO 31") even when the source script has the period intact. Brand product identity gets destroyed.

## Symptoms

- Script contains `Veo 3.1 Lite` verbatim
- Live Haiku calls return `VEO 3 1 LITE CHANGES EVERYTHING` (period replaced with space)
- Same pattern reproduces 100% without a strong prompt constraint
- Validation against proper-noun preservation alone is insufficient because "Veo" survives while "3.1" does not

## What Didn't Work

1. **Relying on `_clean()` parsing to preserve periods** — the `_clean` function was already correct (it preserves `.` between alphanumerics). The problem is upstream: Haiku *itself* writes "3 1" with a space, so there is no period to preserve by the time `_clean` sees it.
2. **Adding a soft "preserve proper nouns" instruction to the prompt** — the model honored brand names (Veo, Claude) but treated version numbers as independent numeric tokens and reformatted them.
3. **Relying on must-include validation with proper nouns alone** — the validator checks for "VEO" in the output, which passes even when "3.1" got mangled. Proper-noun extraction via `\b[A-Z][A-Za-z0-9]+\b` does not capture `3.1` because it starts with a digit.

## Solution

Three coordinated changes in `scripts/thumbnail_gen/headline.py`:

**1. Explicit version-number rules in the prompt:**

```python
_PROMPT = """...
- CRITICAL: Version numbers and model names must keep their internal punctuation. \
"3.1" must NOT become "3 1" or "31". "4.6" must NOT become "4 6" or "46". \
"GPT-4" must NOT become "GPT 4". Write version numbers as a SINGLE TOKEN with \
the period intact: "VEO 3.1", "CLAUDE 4.6", "GPT-4".{must_include_clause}
..."""
```

**2. Regex extraction of version numbers from the source script:**

```python
_VERSION_PATTERN = re.compile(r"\b[A-Za-z]+\s+(\d+\.\d+)\b|(\d+\.\d+)")

version_numbers = sorted(
    {m.group(1) or m.group(2) for m in _VERSION_PATTERN.finditer(script_text)} - {None}
)
must_include_versions = [v for v in version_numbers if v]
```

These are injected into the prompt as an explicit must-include list:

```python
if must_include_versions:
    must_clauses.append(
        "The following version numbers MUST appear in the headline EXACTLY as "
        "written, with the period intact: " + ", ".join(must_include_versions)
    )
```

**3. Post-generation validation that rejects and retries:**

```python
# Version numbers must survive verbatim with the period
if required_versions and not all(v in cleaned for v in required_versions):
    logger.warning(
        "Headline missing required version(s) %s on attempt %d: %r",
        required_versions, attempt + 1, cleaned,
    )
    continue
```

Combined, the function retries on any version-number drift and raises after 2 failed attempts. Verified live: 3 consecutive Haiku calls on the same Veo 3.1 Lite script all produced `VEO 3.1 LITE CHANGES EVERYTHING` with the period intact.

## Why This Works

The prompt-level fix addresses the root cause (Haiku's default tokenization of numeric strings). The regex extraction ensures the requirement is applied dynamically — any version number found in the source script becomes a mandatory preservation target. The validator provides a safety net: even if a stronger future prompt drifts again, the retry catches it and a second attempt almost always succeeds when the first failed for a soft reason like punctuation.

Critically, version numbers are extracted as raw patterns (`3.1`, `4.6`) rather than as proper nouns. Proper-noun extraction via capital-letter patterns fundamentally cannot match `3.1` because it starts with a digit — a separate extractor is required.

## Prevention

- **When calling any LLM for structured short text with numbers in it**, test whether the model respects internal punctuation. Don't assume.
- **Extract validation requirements from source content programmatically** — if the script says "3.1", the validator must check for "3.1" specifically, not just "some number".
- **Prompt engineering rule**: for formatting constraints, give the model both the positive form ("write 3.1") AND 2-3 concrete negative examples ("NOT 3 1, NOT 31"). Negative examples of specific failure modes are more effective than general rules.
- **Regression test** the exact failure:
  ```python
  def test_preserves_version_numbers_with_dots():
      client = _make_client("VEO 3.1 LITE RELEASED")
      result = generate_headline("Google released Veo 3.1 Lite today.", client=client)
      assert "3.1" in result
  ```
- **Don't conflate proper-noun preservation with punctuation preservation** — they need separate extractors, separate prompt clauses, and separate validators. The original fix that only preserved proper nouns let the bug through because "VEO" survived while "3.1" was destroyed, and the `any()` validator passed.
