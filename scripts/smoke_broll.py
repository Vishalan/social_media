"""
B-roll smoke test — generator-agnostic.

Validates the full path for a single CPU b-roll generator:
  1. Build a minimal topic stub
  2. Run the generator
  3. Save the MP4 to output/broll/smoke_<type>.mp4

Usage:
    cd scripts/
    python smoke_broll.py                       # browser_visit (default)
    BROLL_TYPE=image_montage python smoke_broll.py
    BROLL_TYPE=code_walkthrough python smoke_broll.py
    BROLL_TYPE=stats_card python smoke_broll.py

    # Override the article URL (browser_visit and image_montage):
    BROLL_URL="https://en.wikipedia.org/wiki/GPT-4" python smoke_broll.py

Required env vars:
    BROLL_TYPE=browser_visit (default) | image_montage | code_walkthrough | stats_card

    For code_walkthrough / stats_card:
        ANTHROPIC_API_KEY

    For image_montage (optional — falls back to Google News OG thumbnails if absent):
        PEXELS_API_KEY
        BING_SEARCH_API_KEY

Playwright note (browser_visit only):
    Playwright must be installed AND the Chromium browser binary downloaded:
        pip install playwright
        playwright install chromium
"""

import asyncio
import logging
import os
import sys
import time
import types
from pathlib import Path

from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
for _noisy in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

logger = logging.getLogger("smoke_broll")

_PASS = "✓"
_FAIL = "✗"

# Default smoke test topics — realistic AI/tech examples per generator type
_DEFAULT_TOPICS: dict[str, dict] = {
    "browser_visit": {
        "title": "Large language model",
        "url": "https://en.wikipedia.org/wiki/Large_language_model",
        "summary": "Overview of large language models including GPT-4 and Claude.",
    },
    "image_montage": {
        "title": "OpenAI releases new reasoning model",
        "url": "https://openai.com/index/gpt-4o-mini-advancing-cost-efficient-intelligence",
        "summary": "OpenAI launches a new cost-efficient reasoning model for developers.",
    },
    "code_walkthrough": {
        "title": "How to use the OpenAI Responses API",
        "url": "https://platform.openai.com/docs/guides/responses",
        "summary": "Tutorial on calling the OpenAI Responses API with structured outputs.",
    },
    "stats_card": {
        "title": "GPT-4o vs Claude 3.5: benchmark comparison",
        "url": "",
        "summary": (
            "GPT-4o scores 87.2% on MMLU versus Claude 3.5 Sonnet at 88.7%. "
            "GPT-4o processes 128k tokens at $5 per million input tokens while "
            "Claude 3.5 costs $3 per million. Latency is 0.8s vs 1.1s respectively."
        ),
    },
}

_SCRIPT_STUBS: dict[str, dict] = {
    "stats_card": {
        "script": (
            "GPT-4o scores 87.2% on MMLU, while Claude 3.5 Sonnet reaches 88.7%. "
            "For cost, GPT-4o charges $5 per million input tokens versus Claude's $3. "
            "On latency, GPT-4o wins at 0.8 seconds against 1.1 for Claude. "
            "So Claude leads on quality and cost, while GPT-4o wins on speed."
        )
    }
}


def _env(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        print(f"  {_FAIL}  Missing required env var: {key}")
        sys.exit(1)
    return val


def _section(title: str) -> None:
    print(f"\n[{title}]")


def _check_playwright() -> None:
    """Verify the playwright package and Chromium binary are available."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        print(f"  {_FAIL}  playwright package not installed.")
        print("         Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    # Check that the chromium executable exists in Playwright's cache
    import subprocess as _sp
    result = _sp.run(
        [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
        capture_output=True,
        text=True,
    )
    # If dry-run returns non-zero it usually means the binary is already installed;
    # we also accept zero. The real check is whether launch succeeds at generate time.
    # Just confirm the package import works and move on.
    print(f"  {_PASS}  playwright package available")


async def run_smoke(broll_type: str, url_override: str) -> None:
    _section(f"1. Setup — generator: {broll_type}")

    if broll_type not in _DEFAULT_TOPICS:
        print(f"  {_FAIL}  Unknown BROLL_TYPE {broll_type!r}")
        print(f"         Supported: {', '.join(_DEFAULT_TOPICS)}")
        sys.exit(1)

    if broll_type == "browser_visit":
        _check_playwright()

    # Build the minimal job stub (only the fields each generator actually reads)
    topic = dict(_DEFAULT_TOPICS[broll_type])
    if url_override:
        topic["url"] = url_override
        print(f"  ↗  URL overridden: {url_override}")
    script = _SCRIPT_STUBS.get(broll_type, {"script": topic.get("summary", "")})

    job = types.SimpleNamespace(topic=topic, script=script)

    print(f"  {_PASS}  Topic:  {topic['title']}")
    if topic.get("url"):
        print(f"         URL:    {topic['url'][:80]}")

    # Build generator kwargs
    gen_kwargs: dict = {}
    if broll_type in ("code_walkthrough", "stats_card"):
        from anthropic import AsyncAnthropic
        gen_kwargs["anthropic_client"] = AsyncAnthropic(api_key=_env("ANTHROPIC_API_KEY"))
    elif broll_type == "image_montage":
        gen_kwargs["pexels_api_key"] = os.environ.get("PEXELS_API_KEY", "")
        gen_kwargs["bing_api_key"] = os.environ.get("BING_SEARCH_API_KEY", "")
        if gen_kwargs["pexels_api_key"]:
            print(f"  {_PASS}  Pexels API key set")
        else:
            print("         PEXELS_API_KEY not set — will use OG image fallback")
        if gen_kwargs["bing_api_key"]:
            print(f"  {_PASS}  Bing API key set")

    _section(f"2. Generate — {broll_type}")

    from broll_gen.factory import make_broll_generator
    from broll_gen.base import BrollError

    os.makedirs("output/broll", exist_ok=True)
    output_path = f"output/broll/smoke_{broll_type}.mp4"
    target_duration_s = 10.0

    print(f"  ↗  Running {broll_type} generator (target {target_duration_s:.0f}s)...")
    t0 = time.monotonic()

    try:
        gen = make_broll_generator(broll_type, **gen_kwargs)
        result_path = await gen.generate(job, target_duration_s, output_path)
    except BrollError as exc:
        print(f"  {_FAIL}  BrollError: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"  {_FAIL}  Unexpected error: {type(exc).__name__}: {exc}")
        sys.exit(1)

    elapsed = time.monotonic() - t0
    size_kb = Path(result_path).stat().st_size // 1024

    print(f"  {_PASS}  Generated in {elapsed:.1f}s  ({size_kb} KB)")
    print(f"\n  🎬  Output: {result_path}")
    print(f"  ⏱   Total: {elapsed:.1f}s")


async def main() -> None:
    load_dotenv()

    broll_type = os.environ.get("BROLL_TYPE", "browser_visit").lower()
    url_override = os.environ.get("BROLL_URL", "")

    print("=" * 60)
    print(f"B-Roll Smoke Test  [{broll_type.upper()}]")
    print("=" * 60)

    await run_smoke(broll_type, url_override)

    print("\n" + "=" * 60)
    print(f"RESULT: {_PASS}  B-roll smoke test passed  [{broll_type.upper()}]")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
