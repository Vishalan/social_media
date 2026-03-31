"""
CommonCreed pipeline smoke test.

Exercises every component against real APIs but spends NO GPU and posts NOTHING.
Run this to verify keys and pipeline wiring before a live run.

Usage:
    cd scripts/
    python smoke_test.py

Checks:
    1. News sourcing — fetch 3 real AI & Technology topics
    2. Script generation — generate one short-form script (Anthropic)
    3. B-roll selection — AI type selection for the topic (Claude haiku)
    4. CPU b-roll — image_montage with Pexels or fallback (fastest CPU type)
    5. Voiceover — ElevenLabs voice generate for short script
    6. Avatar client — connectivity check (NOT full generation, saves $)
    7. Telegram — send a test alert to owner

Exit 0 on full pass, 1 on any failure.
"""

import asyncio
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("smoke_test")

# ── silence noisy sub-loggers ──────────────────────────────────────────────
for _noisy in ("httpx", "httpcore", "anthropic", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)


def _env(key: str, required: bool = True) -> str:
    val = os.environ.get(key, "")
    if required and not val:
        _fail(f"Missing required env var: {key}")
    return val


_PASS = "✓"
_FAIL = "✗"
_SKIP = "–"
_failures: list[str] = []


def _ok(label: str, detail: str = "") -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  {_PASS}  {label}{suffix}")


def _fail(label: str, detail: str = "") -> None:
    suffix = f"  ({detail})" if detail else ""
    print(f"  {_FAIL}  {label}{suffix}")
    _failures.append(label)


def _skip(label: str, reason: str = "") -> None:
    suffix = f"  ({reason})" if reason else ""
    print(f"  {_SKIP}  {label} [skipped]{suffix}")


# ── 1. News sourcing ───────────────────────────────────────────────────────

def check_news() -> list[dict]:
    print("\n[1] News sourcing")
    try:
        from analytics.tracker import AnalyticsTracker
        from news_sourcing.news_sourcer import NewsSourcer

        os.makedirs("output", exist_ok=True)
        tracker = AnalyticsTracker(db_path="output/smoke_test_analytics.db")
        sourcer = NewsSourcer(tracker=tracker, telegram_bot=None, max_topics=3)
        topics = sourcer.fetch()
        _ok(f"Fetched {len(topics)} topics")
        for t in topics:
            print(f"       • {t['title'][:80]}")
        return topics
    except Exception as exc:
        _fail("News sourcing", str(exc))
        return []


# ── 2. Script generation ───────────────────────────────────────────────────

def check_script(topic: dict) -> dict:
    print("\n[2] Script generation (Anthropic)")
    try:
        from content_gen.script_generator import ScriptGenerator

        gen = ScriptGenerator(
            api_provider="anthropic",
            api_key=_env("ANTHROPIC_API_KEY"),
            output_dir="output/scripts",
        )
        t0 = time.monotonic()
        script = gen.generate_short_form(topic["title"], niche="AI & Technology")
        elapsed = time.monotonic() - t0
        _ok(f"Script generated in {elapsed:.1f}s", f"hook: {script.get('hook','')[:60]}")
        return script
    except Exception as exc:
        _fail("Script generation", str(exc))
        return {}


# ── 3. B-roll type selection ───────────────────────────────────────────────

async def check_selector(topic: dict, script: dict) -> list[str]:
    print("\n[3] B-roll type selection (Claude haiku)")
    try:
        from anthropic import AsyncAnthropic
        from broll_gen.selector import BrollSelector

        client = AsyncAnthropic(api_key=_env("ANTHROPIC_API_KEY"))
        selector = BrollSelector(client)
        script_text = script.get("script", topic.get("summary", ""))
        t0 = time.monotonic()
        types = await selector.select(topic["title"], topic["url"], script_text)
        elapsed = time.monotonic() - t0
        _ok(f"Selected in {elapsed:.1f}s", f"primary={types[0]}, fallback={types[1]}")
        return types
    except Exception as exc:
        _fail("B-roll selector", str(exc))
        return ["image_montage", "ai_video"]


# ── 4. CPU b-roll generation ───────────────────────────────────────────────

async def check_broll(topic: dict, script: dict, selected_types: list[str]) -> None:
    print("\n[4] CPU b-roll generation")
    import os
    from pathlib import Path
    from broll_gen import BrollError, make_broll_generator
    from commoncreed_pipeline import VideoJob

    os.makedirs("output/video", exist_ok=True)
    output_path = "output/video/smoke_test_broll.mp4"

    job = VideoJob(
        topic=topic,
        script=script,
        trimmed_audio_path="",
        avatar_path="",
    )

    pexels_key = os.environ.get("PEXELS_API_KEY", "")
    bing_key = os.environ.get("BING_SEARCH_API_KEY", "")

    from anthropic import AsyncAnthropic
    anthropic_client = AsyncAnthropic(api_key=_env("ANTHROPIC_API_KEY"))

    # Try selected types first, then sweep remaining CPU types
    all_cpu = ["browser_visit", "image_montage", "code_walkthrough", "stats_card"]
    ordered = selected_types + [t for t in all_cpu if t not in selected_types]

    for type_name in ordered:
        if type_name == "ai_video":
            continue
        try:
            gen = make_broll_generator(
                type_name,
                anthropic_client=anthropic_client,
                pexels_api_key=pexels_key,
                bing_api_key=bing_key,
            )
            t0 = time.monotonic()
            path = await gen.generate(job, target_duration_s=20.0, output_path=output_path)
            elapsed = time.monotonic() - t0
            size_kb = Path(path).stat().st_size // 1024
            _ok(f"{type_name} succeeded in {elapsed:.1f}s", f"{size_kb} KB → {path}")
            return
        except BrollError as exc:
            print(f"       {_SKIP} {type_name} → BrollError: {exc}")
        except Exception as exc:
            print(f"       {_SKIP} {type_name} → {type(exc).__name__}: {exc}")

    _fail("All CPU b-roll generators", "no type produced output — check PEXELS_API_KEY or Anthropic credits")


# ── 5. Voiceover ───────────────────────────────────────────────────────────

def check_voice(script: dict) -> None:
    print("\n[5] Voiceover (ElevenLabs)")
    try:
        from voiceover.voice_generator import VoiceGenerator
        import os

        os.makedirs("output/audio", exist_ok=True)
        gen = VoiceGenerator(api_key=_env("ELEVENLABS_API_KEY"))
        # Use hook text only (~5s) to keep cost minimal
        text = script.get("hook", "Testing the CommonCreed pipeline voice synthesis.")
        t0 = time.monotonic()
        path = gen.generate(
            text,
            "output/audio/smoke_test_voice.mp3",
            voice_id=_env("ELEVENLABS_VOICE_ID"),
        )
        elapsed = time.monotonic() - t0
        from pathlib import Path
        size_kb = Path(path).stat().st_size // 1024
        _ok(f"Voice generated in {elapsed:.1f}s", f"{size_kb} KB → {path}")
    except Exception as exc:
        _fail("Voiceover", str(exc))


# ── 6. Avatar connectivity check ───────────────────────────────────────────

def check_avatar_connectivity() -> None:
    print("\n[6] Avatar client connectivity")
    provider = os.environ.get("AVATAR_PROVIDER", "kling").lower()
    try:
        if provider == "kling":
            import httpx
            # Verify fal.ai is reachable (no actual generation)
            resp = httpx.get("https://fal.run/health", timeout=5.0)
            if resp.status_code < 500:
                _ok(f"Kling/fal.ai reachable (HTTP {resp.status_code})")
            else:
                _fail(f"Kling/fal.ai returned {resp.status_code}")
        elif provider == "heygen":
            import httpx
            resp = httpx.get(
                "https://api.heygen.com/v1/user/remaining_quota",
                headers={"X-Api-Key": _env("HEYGEN_API_KEY")},
                timeout=5.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                remaining = data.get("data", {}).get("remaining_quota", "?")
                _ok(f"HeyGen reachable", f"remaining quota: {remaining}")
            else:
                _fail(f"HeyGen returned {resp.status_code}", resp.text[:100])
        else:
            _skip("Avatar connectivity", f"unknown provider: {provider}")
    except Exception as exc:
        _fail("Avatar connectivity", str(exc))

    # Check portrait image URL is accessible
    portrait_url = os.environ.get("KLING_AVATAR_IMAGE_URL", "")
    if portrait_url and provider == "kling":
        try:
            import httpx
            resp = httpx.head(portrait_url, timeout=5.0, follow_redirects=True)
            if resp.status_code == 200:
                _ok("Portrait image URL accessible", portrait_url[:60])
            else:
                _fail("Portrait image URL", f"HTTP {resp.status_code} — {portrait_url}")
        except Exception as exc:
            _fail("Portrait image URL", str(exc))


# ── 7. Telegram alert ──────────────────────────────────────────────────────

async def check_telegram() -> None:
    print("\n[7] Telegram alert")
    try:
        from approval.telegram_bot import TelegramApprovalBot

        bot = TelegramApprovalBot(
            bot_token=_env("TELEGRAM_BOT_TOKEN"),
            owner_user_id=int(_env("TELEGRAM_OWNER_USER_ID")),
        )
        await bot.send_alert("🔥 CommonCreed smoke test — all systems go!")
        _ok("Telegram alert sent")
    except Exception as exc:
        _fail("Telegram alert", str(exc))


# ── Main ───────────────────────────────────────────────────────────────────

async def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    print("=" * 60)
    print("CommonCreed Pipeline Smoke Test")
    print("=" * 60)

    # 1. News
    topics = check_news()
    topic = topics[0] if topics else {
        "title": "OpenAI releases new GPT-5 API",
        "url": "https://openai.com/blog/gpt-5",
        "summary": "OpenAI has released GPT-5 with improved reasoning capabilities.",
        "source": "fallback",
    }

    # 2. Script
    script = check_script(topic)
    if not script:
        script = {"hook": "AI is changing everything.", "script": topic["title"], "visual_cues": "tech"}

    # 3. B-roll selector
    selected_types = await check_selector(topic, script)

    # 4. CPU b-roll
    await check_broll(topic, script, selected_types)

    # 5. Voice
    check_voice(script)

    # 6. Avatar connectivity
    check_avatar_connectivity()

    # 7. Telegram
    await check_telegram()

    # ── Summary ──
    print("\n" + "=" * 60)
    if _failures:
        print(f"RESULT: {_FAIL}  {len(_failures)} check(s) failed:")
        for f in _failures:
            print(f"        • {f}")
        sys.exit(1)
    else:
        print(f"RESULT: {_PASS}  All checks passed — pipeline is ready")
        print("=" * 60)
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
