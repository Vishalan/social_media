---
date: 2026-03-29
type: feat
status: active
origin: docs/brainstorms/2026-03-29-rich-broll-engagement-requirements.md
---

# feat: Rich B-Roll Engagement System

## Problem Frame

The current b-roll implementation passes a text prompt to ComfyUI/Wan2.1 and returns generic AI video (glowing circuits, abstract tech). For an AI & Technology channel this is forgettable — it lacks topical authenticity and causes viewers to disengage. The replacement is a **type-driven b-roll system** where a Claude-powered `BrollSelector` analyzes the topic and script to choose the highest-engagement subordinate footage format: browser screenshots, image montages, code walkthroughs, or stats cards. GPU video generation stays as a last resort, not the default, eliminating pod costs on days when CPU types suffice.

*(see origin: docs/brainstorms/2026-03-29-rich-broll-engagement-requirements.md)*

## Requirements Trace

| Req | Description |
|-----|-------------|
| R1 | BrollSelector analyzes content signals and returns a ranked type list |
| R2 | Catalog: `browser_visit`, `image_montage`, `code_walkthrough`, `stats_card`, `ai_video` |
| R3 | Ranked fallback chain: primary → fallback → `ai_video` → existing stub |
| R4 | Each generator produces MP4 at target duration, 1080×540+ |
| R5 | Selection signals drive type choice: URL reachability, stats in script, code keywords |
| R6 | Image sources: Pexels → Bing → Google News thumbnails |
| R7 | CPU types in Phase 1 (no pod); `ai_video` in Phase 2 (conditional pod) |
| R8 | `browser_visit` handles paywall, non-article, and long-page gracefully |
| R9 | Output to `output/video/`; `VideoJob.broll_path` unchanged |
| R10 | `PEXELS_API_KEY` and `BING_SEARCH_API_KEY` optional; graceful degradation |

## Scope Boundaries

- One b-roll clip per video — no multi-segment or picture-in-picture.
- `VideoEditor.assemble()` contract is unchanged.
- No live browser recording — static screenshot + FFmpeg animation only.
- No audio in b-roll clips.
- Copyright: Pexels/Bing licensed images only; Google News thumbnails as low-res fallback.

## High-Level Technical Design

*This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
commoncreed_pipeline.py  Phase 1
  ├─ voiceover generated (audio_duration known)
  ├─ target_duration_s = audio_duration - HOOK_DURATION_S - CTA_DURATION_S
  └─ for each job:
       BrollSelector.select(topic, url, script)
         └─ AsyncAnthropic + output_config.format (json_schema)
              → { primary: "browser_visit", fallback: "image_montage" }
       BrollFactory.make(primary).generate(job, target_duration_s, output_path)
         ├─ success → job.broll_path = output_path; job.needs_gpu_broll = False
         └─ failure → BrollFactory.make(fallback).generate(...)
              ├─ success → job.broll_path = output_path; job.needs_gpu_broll = False
              └─ failure → job.needs_gpu_broll = True  (ai_video in Phase 2)

Phase 2 gate:
  if not any(j.needs_gpu_broll for j in jobs):
      skip pod entirely   # zero GPU cost day
  else:
      start pod → AiVideoGenerator.generate() for flagged jobs
```

**FFmpeg filter strategies by type:**

| Type | Filter approach |
|------|----------------|
| `browser_visit` | Tall PNG → `crop` filter with `y='(in_h-out_h)*t/duration'` for scroll |
| `image_montage` | Per-image `zoompan` (Ken Burns) + `xfade` cross-fade between clips |
| `code_walkthrough` | PNG strip overlays with `fade=alpha=1` per progressive line reveal |
| `stats_card` | PIL-rendered frames with sequential fade-in per stat; `ffmpeg -framerate` |

## Critical Gaps (from spec-flow-analyzer)

**C1 — VideoJob schema**: `VideoJob` dataclass needs two new fields so pipeline stages can communicate b-roll state:
- `broll_type: str = ""` — records which type was selected (for logging/analytics)
- `needs_gpu_broll: bool = False` — signals Phase 2 to start GPU pod

**C2 — BrollSelector Claude failure fallback**: If the `AsyncAnthropic` call fails (network error, quota), `BrollSelector.select()` must return a hardcoded safe default (`["image_montage", "ai_video"]`) rather than propagating the exception. The pipeline must never block on Claude failure to select a b-roll type.

**C3 — `target_duration_s` threading**: Every CPU generator's `generate()` method must accept `target_duration_s: float` as a required parameter. This is computable in Phase 1 after voiceover generation and must be passed through `BrollFactory`.

**C4 — Phase 2 skip-completed-jobs**: The Phase 2 `ai_video` loop must check `if job.broll_path:` and skip jobs that already have a completed CPU b-roll clip. The condition `job.needs_gpu_broll` covers most cases but is a belt-and-suspenders guard.

## Implementation Units

---

### Unit 1 — `broll_gen/` Package Skeleton + Base Protocol

**Goal:** Create the package directory and base interface that all generators conform to. Mirrors the `avatar_gen/` package structure.

**Requirements:** R2, R3, R4

**Dependencies:** None (can land first)

**Files:**
- `scripts/broll_gen/__init__.py` — re-export `BrollBase`, `BrollResult`, `BrollError`
- `scripts/broll_gen/base.py` — abstract base class with `generate(job, target_duration_s, output_path) -> str` signature and `BrollError` exception

**Approach:**
- `BrollBase` is an abstract class (or Protocol) with one required method: `async def generate(job: VideoJob, target_duration_s: float, output_path: str) -> str`
- `BrollError` is raised when a generator cannot produce output (paywall, empty result, FFmpeg error)
- Follow the pattern in `scripts/avatar_gen/base.py` (`AvatarQualityError` pattern)
- The return value is the output file path (same as avatar clients)

**Patterns to follow:** `scripts/avatar_gen/base.py`

**Test file:** `scripts/broll_gen/test_broll_base.py` — import smoke test only (abstract class, minimal surface)

**Verification:** `from scripts.broll_gen import BrollBase, BrollError` succeeds without error.

---

### Unit 2 — VideoJob Schema Extension

**Goal:** Add `broll_type` and `needs_gpu_broll` fields to `VideoJob` so Phase 1 and Phase 2 can communicate b-roll state.

**Requirements:** C1 (critical gap), R7

**Dependencies:** Unit 1 (needs `BrollError` concept to exist for documentation clarity)

**Files:**
- `scripts/commoncreed_pipeline.py` — `VideoJob` dataclass: add `broll_type: str = ""` and `needs_gpu_broll: bool = False`

**Approach:**
- Both fields have default values so all existing construction sites are unaffected
- `broll_type` records the winning generator name (e.g. `"browser_visit"`) for logging
- `needs_gpu_broll` is the Phase 2 trigger flag; set to `True` only when all CPU generators fail

**Patterns to follow:** Existing `VideoJob` fields in `commoncreed_pipeline.py`

**Test file:** No separate test file — covered by pipeline integration tests (Unit 9)

**Verification:** `VideoJob(topic="x", url="y", script="z")` instantiates with `broll_type=""` and `needs_gpu_broll=False`.

---

### Unit 3 — `BrollSelector` (AI-driven type selection)

**Goal:** Implement the intelligence layer — a Claude-powered classifier that analyzes topic, URL, and script to return a ranked `[primary, fallback]` b-roll type list.

**Requirements:** R1, R5, C2

**Dependencies:** Unit 1

**Files:**
- `scripts/broll_gen/selector.py` — `BrollSelector` class with `async def select(topic, url, script) -> list[str]`

**Approach:**
- Uses `AsyncAnthropic` client (already a dependency in the pipeline)
- Model: `claude-haiku-4-5` — 10× cheaper than Sonnet for a classification task; latency acceptable
- Uses `output_config.format` with `json_schema` (constrained decoding) to guarantee a valid enum response:
  ```json
  {
    "type": "object",
    "properties": {
      "primary": {"type": "string", "enum": ["browser_visit","image_montage","code_walkthrough","stats_card","ai_video"]},
      "fallback": {"type": "string", "enum": ["browser_visit","image_montage","code_walkthrough","stats_card","ai_video"]}
    },
    "required": ["primary","fallback"]
  }
  ```
- System prompt encodes the R5 heuristics as guidance (not rigid rules): URL reachability hint, stats language → stats_card, code/API/model keywords → code_walkthrough, general tech news → image_montage, abstract/speculative → ai_video
- The prompt explicitly instructs the model to pick the type that will keep a viewer watching for the full clip — engagement is the optimization target
- **C2 fallback**: Wrap the entire Claude call in `try/except`; on any exception return `["image_montage", "ai_video"]`
- Do NOT check URL reachability inside BrollSelector — that is the generator's job (R8). The selector only reasons about text signals.

**Patterns to follow:** `AsyncAnthropic` usage in `commoncreed_pipeline.py` for script generation; `output_config.format` pattern from best-practices research

**Test file:** `scripts/broll_gen/test_selector.py`
- Mock `AsyncAnthropic` to return valid JSON for happy path
- Assert `select()` returns a 2-element list of valid type strings
- Mock to raise `Exception` → assert returns `["image_montage", "ai_video"]` (C2 fallback)

**Verification:** `BrollSelector().select("OpenAI new API", "https://...", "...script...")` returns `["code_walkthrough", "image_montage"]` (or similar valid pair) in test.

---

### Unit 4 — `BrowserVisitGenerator`

**Goal:** Headless browser screenshot of the topic article URL, animated as a smooth downward scroll via FFmpeg.

**Requirements:** R2 (`browser_visit`), R4, R8

**Dependencies:** Unit 1, Unit 2

**Files:**
- `scripts/broll_gen/browser_visit.py` — `BrowserVisitGenerator(BrollBase)`

**Approach:**
- Uses `patchright` (not `playwright` or `playwright-stealth`) — drop-in Playwright replacement that avoids CDP leaks (primary Cloudflare detection signal)
- Browser launch: `async with async_playwright() as p: browser = await p.chromium.launch(headless=True)`
- Viewport: 1280×720 (matches OUTPUT_WIDTH proportionally); full-page screenshot via `page.screenshot(full_page=True)`
- R8 failure detection:
  - **Paywall/login wall**: Check word count < 200 in `page.text_content("body")` OR check for `<article>` selector missing → raise `BrollError("paywall")`, caller falls back to `image_montage`
  - **Non-article URL** (video embed, redirect): Check `page.url` contains `youtube.com/watch` or `twitter.com` → raise `BrollError("non-article")`
  - **Very long page**: Cap screenshot to `viewport_height × 3 = 2160px` by cropping the PNG with Pillow before passing to FFmpeg
- FFmpeg scroll animation: `crop` filter with `y='(in_h-out_h)*t/duration'`, output 1080×540, `target_duration_s`
- Run browser and FFmpeg via `asyncio.to_thread` (follows repo convention for subprocess calls)
- Save screenshot as temp file; clean up after FFmpeg

**Patterns to follow:** `asyncio.to_thread` subprocess pattern from `learnings-researcher`; FFmpeg subprocess call from `comfyui_client.py`

**Test file:** `scripts/broll_gen/test_browser_visit.py`
- Mock `patchright` async context manager
- Happy path: returns output path, file exists
- Paywall: word count < 200 → `BrollError` raised
- Long page: tall image cropped to 3× viewport before FFmpeg

**Verification:** `BrowserVisitGenerator().generate(job, 24.0, "out.mp4")` returns path string in test; paywall test raises `BrollError`.

---

### Unit 5 — `ImageMontageGenerator`

**Goal:** Fetch 4–6 images from Pexels → Bing → Google News and assemble a Ken Burns slideshow via FFmpeg.

**Requirements:** R2 (`image_montage`), R4, R6, R10

**Dependencies:** Unit 1

**Files:**
- `scripts/broll_gen/image_montage.py` — `ImageMontageGenerator(BrollBase)` + internal `_fetch_images()` helper

**Approach:**
- Image fetch priority chain (R6, R10):
  1. **Pexels** (`PEXELS_API_KEY` env var): `httpx.AsyncClient` GET `https://api.pexels.com/v1/search`, header `Authorization: {key}` (no Bearer prefix), field `photos[n].src.landscape` for 16:9 images, 200 req/hr free tier
  2. **Bing Image Search** (`BING_SEARCH_API_KEY` env var): `https://api.bing.microsoft.com/v7.0/images/search`, header `Ocp-Apim-Subscription-Key`
  3. **Google News thumbnails**: Already present in `VideoJob` as `thumbnail_url` or extractable from the RSS feed result in the pipeline — zero extra API calls
  - If a source raises `httpx.HTTPError` or key is absent, skip silently to next source
  - Minimum 2 images required; raise `BrollError` if none found
- Download images to temp directory with `httpx.AsyncClient`
- FFmpeg Ken Burns per image: `zoompan=z='zoom+0.001':d={fps*clip_s}:s={w}x{h},setpts=PTS-STARTPTS` — **critical**: `d` must be `fps × per_clip_duration_s` (integer), and `setpts=PTS-STARTPTS` is required to reset timestamps before `xfade`
- Cross-fade between clips: `xfade=transition=fade:duration=0.5`
- Per-clip duration: `target_duration_s / num_images`; at least 3s per image
- Output: 1080×540, `target_duration_s`

**Patterns to follow:** `httpx.AsyncClient` from `avatar_gen/heygen_client.py` and `kling_client.py`

**Test file:** `scripts/broll_gen/test_image_montage.py`
- Mock `httpx.AsyncClient`: Pexels returns 2 image URLs → happy path
- Pexels key absent → falls through to Google News thumbnails
- All sources fail → `BrollError` raised

**Verification:** Returns output path in test; degrades gracefully with no API keys if Google News thumbnails present.

---

### Unit 6 — `CodeWalkthroughGenerator`

**Goal:** Generate a relevant code snippet via Claude, render it with syntax highlighting, and animate a typewriter-style reveal via FFmpeg.

**Requirements:** R2 (`code_walkthrough`), R4

**Dependencies:** Unit 1

**Files:**
- `scripts/broll_gen/code_walkthrough.py` — `CodeWalkthroughGenerator(BrollBase)`

**Approach:**
- Claude call: `AsyncAnthropic` with `claude-haiku-4-5`, prompt asking for 10–20 line code snippet relevant to the topic (calling the new API, using the new model, etc.). Free-text response (no structured output needed — just code).
- Strip markdown fences from response to get raw code
- Pygments `ImageFormatter` for PNG render: style `monokai`, font `DejaVuSans Mono` or `Courier New`, image width 1080px. Returns PNG bytes directly — no temp image write needed before FFmpeg
- FFmpeg typewriter animation: N overlay strips (one per line), each strip fades in sequentially using `fade=type=in:st={start_time}:d=0.3:alpha=1`. Lines appear every `target_duration_s / num_lines` seconds
- If code is long (>20 lines after Claude generation), crop to 20 lines before rendering
- Raise `BrollError` if Claude returns empty or non-code response

**Patterns to follow:** `AsyncAnthropic` usage for script generation; `asyncio.to_thread` for FFmpeg subprocess

**Test file:** `scripts/broll_gen/test_code_walkthrough.py`
- Mock `AsyncAnthropic` → returns code block string
- Assert Pygments renders and FFmpeg called with correct args
- Empty Claude response → `BrollError`

**Verification:** Returns output path in test with mocked Claude and FFmpeg.

---

### Unit 7 — `StatsCardGenerator`

**Goal:** Extract 3–5 measurable claims from the script via Claude and render an animated text card with sequential stat reveals.

**Requirements:** R2 (`stats_card`), R4

**Dependencies:** Unit 1

**Files:**
- `scripts/broll_gen/stats_card.py` — `StatsCardGenerator(BrollBase)`

**Approach:**
- Claude call: `AsyncAnthropic` with `output_config.format` json_schema requesting `{"stats": [{"label": str, "value": str}]}` — constrained decoding guarantees parseable output
- Model: `claude-haiku-4-5`
- PIL/Pillow renders each stat as a frame sequence: dark background, large value text, smaller label text, consistent brand colors
- Each stat appears at `(i / num_stats) * target_duration_s` seconds with a 0.4s fade
- Output frames to temp directory → `ffmpeg -framerate {fps} -pattern_type glob -i '*.png'` assembles video
- Raise `BrollError` if Claude returns < 2 stats (not enough for an engaging card)

**Patterns to follow:** PIL `ImageDraw` usage (standard library pattern); `asyncio.to_thread` for FFmpeg

**Test file:** `scripts/broll_gen/test_stats_card.py`
- Mock Claude → returns 3 stats
- Assert PIL called and FFmpeg assembles frames
- < 2 stats → `BrollError`

**Verification:** Returns output path in test.

---

### Unit 8 — `BrollFactory` + `AiVideoGenerator` wrapper

**Goal:** Central factory that instantiates the right generator by type name; thin wrapper for the existing `ai_video` path (ComfyUI/Wan2.1) conforming to `BrollBase`.

**Requirements:** R3, R2 (`ai_video`), R7

**Dependencies:** Units 4–7

**Files:**
- `scripts/broll_gen/factory.py` — `BrollFactory` with `make(type_name: str) -> BrollBase`
- `scripts/broll_gen/ai_video.py` — `AiVideoGenerator(BrollBase)` wrapping existing ComfyUI broll workflow

**Approach:**
- `BrollFactory.make()` maps type name strings to generator classes; raises `ValueError` on unknown type
- `AiVideoGenerator.generate()` calls the existing `ComfyUIClient.run_workflow()` with the `broll_generator.json` workflow — this is a thin adapter, not a rewrite
- The `AiVideoGenerator` is the only generator that requires a running GPU pod; it should raise `BrollError` (not block indefinitely) if ComfyUI is unreachable

**Patterns to follow:** `make_avatar_client()` in `scripts/avatar_gen/factory.py`; `ComfyUIClient` in `scripts/video_gen/comfyui_client.py`

**Test file:** `scripts/broll_gen/test_factory.py`
- `make("browser_visit")` returns `BrowserVisitGenerator` instance
- `make("ai_video")` returns `AiVideoGenerator` instance
- `make("unknown")` raises `ValueError`

**Verification:** All factory tests pass.

---

### Unit 9 — Pipeline Integration: Phase 1 CPU B-Roll + Phase 2 Conditional Gate

**Goal:** Wire all generators into `commoncreed_pipeline.py`: run CPU b-roll in Phase 1 after voiceover, skip Phase 2 GPU pod when all jobs have CPU b-roll.

**Requirements:** R7, C3, C4, R3

**Dependencies:** Units 1–8

**Files:**
- `scripts/commoncreed_pipeline.py` — new `_generate_broll()` method; modified `run_daily()` Phase 2 gate; `VideoJob` already updated in Unit 2
- `config/settings.py` or `scripts/config.example.json` — document `PEXELS_API_KEY`, `BING_SEARCH_API_KEY` as optional

**Approach:**
- New `_generate_broll(job: VideoJob, target_duration_s: float) -> None` method on pipeline class:
  ```
  selector = BrollSelector(anthropic_client)
  types = await selector.select(job.topic, job.url, job.script)
  primary, fallback = types[0], types[1]
  for type_name in [primary, fallback]:
      try:
          gen = BrollFactory.make(type_name)
          path = await gen.generate(job, target_duration_s, output_path)
          job.broll_path = path
          job.broll_type = type_name
          job.needs_gpu_broll = False
          return
      except BrollError:
          continue
  job.needs_gpu_broll = True  # signal Phase 2
  ```
- Call `_generate_broll()` in Phase 1 after voiceover, before avatar generation (CPU-only, no pod needed)
- `target_duration_s = audio_duration - HOOK_DURATION_S - CTA_DURATION_S` (C3)
- Phase 2 gate: `if any(j.needs_gpu_broll for j in jobs): start_pod()` else skip entirely
- Phase 2 b-roll loop: `if job.broll_path: continue` (C4 — skip completed jobs)
- Update `.env.example` to document `PEXELS_API_KEY` and `BING_SEARCH_API_KEY` as optional

**Patterns to follow:** Existing Phase 1/Phase 2 structure in `run_daily()` in `commoncreed_pipeline.py`

**Test file:** `scripts/test_pipeline_broll_integration.py`
- All CPU b-roll succeeds → `needs_gpu_broll=False` for all jobs → Phase 2 skipped
- One job fails all CPU types → `needs_gpu_broll=True` → Phase 2 invoked for that job only
- `job.broll_path` already set → Phase 2 skips that job (C4)

**Verification:** Pipeline integration tests pass; `needs_gpu_broll=False` on all jobs when CPU path works.

---

## Dependencies / Assumptions

- `patchright` added to `requirements.txt` (Playwright drop-in, fixes Cloudflare CDP detection)
- `Pygments` added to `requirements.txt` (likely already present but must be confirmed)
- `Pillow` already in `requirements.txt` (assumed by existing pipeline)
- `httpx` already in `requirements.txt` (used by avatar clients)
- `PEXELS_API_KEY` and `BING_SEARCH_API_KEY` are optional env vars; absence degrades gracefully
- `claude-haiku-4-5` model ID is correct for 2026 (verify against Anthropic model list at implementation time)
- `output_config.format` with `json_schema` is available in the current `anthropic` SDK version (verify at implementation time — SDK may use different field name)

## Deferred to Implementation

- **[Affects Unit 3][Technical]** Exact `output_config.format` field name in current `anthropic` Python SDK — may be `response_format` or similar. Check SDK version in `requirements.txt`.
- **[Affects Unit 4][Needs research]** Whether `patchright` is importable as `playwright` or requires its own import alias. Check `patchright` PyPI page at implementation time.
- **[Affects Unit 5][Technical]** Whether Google News thumbnails are already stored in `VideoJob` or must be re-fetched from RSS. Check `VideoJob` fields and RSS parsing code in pipeline.
- **[Affects Unit 6][Technical]** Exact Pygments `ImageFormatter` constructor signature and minimum PIL version for correct font rendering. Confirm at implementation time.
- **[Affects Unit 9][Technical]** Whether `HOOK_DURATION_S` and `CTA_DURATION_S` are module-level constants or config values in `commoncreed_pipeline.py`. Read the file at implementation time.

## Test Scenarios

| Scenario | Expected |
|----------|----------|
| Tech news with reachable URL, no stats, no code keywords | Selector picks `browser_visit` primary, `image_montage` fallback |
| "OpenAI releases new API for real-time voice" | Selector picks `code_walkthrough` (code/API keyword signal) |
| Article behind paywall | `browser_visit` raises `BrollError`; falls back to `image_montage` |
| Script with benchmark numbers (e.g. "3× faster, 50% cheaper") | Selector picks `stats_card` |
| Abstract/speculative topic with no URL | Selector picks `ai_video` |
| Claude API call fails during selection | Returns hardcoded `["image_montage", "ai_video"]` (C2) |
| Pexels key absent, Bing key absent | `image_montage` uses Google News thumbnails |
| All CPU types fail for one job | `needs_gpu_broll=True`; Phase 2 runs for that job only |
| All CPU types succeed for all jobs | `needs_gpu_broll=False` for all; Phase 2 pod never started |
| Phase 2 runs; one job already has `broll_path` | Phase 2 skips that job (C4) |
| FFmpeg produces 0-byte file | `BrollError` raised; fallback attempted |

## Success Criteria

*(from origin: docs/brainstorms/2026-03-29-rich-broll-engagement-requirements.md)*

- `browser_visit`, `image_montage`, or `code_walkthrough` selected for ≥ 80% of topics
- GPU pod NOT started on days when all 3 topics have CPU-viable b-roll
- CPU types produce valid output within 60 seconds; `ai_video` within 3 minutes
- Zero visible encoding artifacts or black frames in assembled video
- A viewer can identify the topic from b-roll alone (no captions)
