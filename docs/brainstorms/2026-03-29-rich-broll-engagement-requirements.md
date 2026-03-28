---
date: 2026-03-29
topic: rich-broll-engagement
---

# Rich B-Roll: Engagement-Driven Subordinate Footage

## Problem Frame

The current b-roll implementation is a stub — it passes a text prompt to a ComfyUI
workflow that produces generic AI video (glowing circuits, abstract tech visuals). For
an AI & Technology channel, this is forgettable: it lacks topical authenticity and does
nothing to signal "this is the actual thing I'm talking about." Viewers disengage when
the supporting footage feels disconnected from the narration.

The goal is a **type-driven b-roll system** that selects the most engaging subordinate
footage format for each specific topic — using browser screenshots, live images,
code animations, and data cards — to keep the viewer watching for the full clip duration.
GPU-generated video remains available as a universal fallback for abstract topics.

## Requirements

- **R1.** The pipeline selects the most engaging b-roll type for each topic automatically,
  based on the topic title, article URL, and generated script. Selection is driven by a
  `BrollSelector` that analyzes content signals and returns a ranked list of types to try.

- **R2.** The system supports a catalog of at minimum the following b-roll types:
  - **`browser_visit`** — Headless browser visits the topic article URL and captures a
    full-page screenshot. FFmpeg animates it with a smooth downward scroll combined with
    a subtle zoom-in, mimicking a human reading the page. Duration: full body segment.
  - **`image_montage`** — Fetches 4–6 high-quality images relevant to the topic from
    one or more image sources (Pexels API, Bing Image Search, or Google News thumbnails
    as fallbacks in priority order). Images are assembled into a Ken Burns slideshow
    (slow pan + zoom per image, cross-fade transitions) via FFmpeg. Duration: full body.
  - **`code_walkthrough`** — Claude generates a concise, relevant code snippet
    (10–20 lines) for the topic (e.g. calling a new API, running a new model). Rendered
    to an image with syntax highlighting. FFmpeg animates it with a typewriter-style
    reveal where lines appear progressively, followed by a slow scroll if the code is
    long. Triggered when the topic involves: API, model, algorithm, SDK, framework,
    library, or "how to use X". Duration: full body.
  - **`stats_card`** — Claude extracts 3–5 key numbers or comparisons from the script
    (benchmark scores, model sizes, cost figures, speed improvements). Rendered as an
    animated text card with each stat appearing sequentially with a subtle fade/slide.
    Triggered when the script contains measurable claims. Duration: full body.
  - **`ai_video`** — GPU-based ComfyUI Wan2.1 generation from a visual prompt.
    Universal fallback. Used when no CPU-based type is applicable or all CPU attempts fail.

- **R3.** Type selection follows a ranked fallback chain: the `BrollSelector` returns a
  primary type and a fallback type. If the primary generator fails (error, empty result,
  or invalid output), the fallback is attempted. If both fail, `ai_video` is used. If
  `ai_video` also fails, the pipeline falls back to the existing `broll_only` path
  (b-roll reuses the audio waveform visualisation or a static image).

- **R4.** Each generator produces a single video clip compatible with the existing
  `VideoEditor.assemble()` contract: MP4, target duration matches the body segment
  (audio duration minus hook 3s and CTA 3s), 1080×540 or better resolution.

- **R5.** The `BrollSelector` chooses types using these signals:
  - Topic URL reachable + article content → `browser_visit` first
  - Script contains measurable stats → `stats_card`
  - Topic involves code/API/model/framework keyword → `code_walkthrough`
  - Any other tech news topic → `image_montage`
  - Abstract, speculative, or no URL → `ai_video`

  Multiple signals can match; the selector returns the highest-engagement type for the
  specific content, not a rigid rule-chain.

- **R6.** Image sources for `image_montage` are tried in priority order:
  1. Pexels API (if `PEXELS_API_KEY` set) — licensed, high quality, free tier 200 req/hr
  2. Bing Image Search API (if `BING_SEARCH_API_KEY` set) — good diversity
  3. Google News RSS feed thumbnails — already fetched, zero extra API calls, low-res
     but always available as a last resort

- **R7.** All b-roll generation is **CPU-only** except `ai_video`. The three CPU types
  (`browser_visit`, `image_montage`, `code_walkthrough`, `stats_card`) run in Phase 1
  alongside avatar generation — no RunPod pod required. `ai_video` remains in Phase 2
  (GPU, pod ON) but is only invoked when the CPU path fails or is selected by the
  `BrollSelector`.

- **R8.** The `browser_visit` type must handle common failure modes gracefully:
  paywalled pages (fallback to `image_montage`), non-article URLs like video embeds
  (skip, try next type), and very long pages (crop to viewport height × 3).

- **R9.** All generated b-roll clips are saved to `output/video/` and referenced in
  `VideoJob.broll_path` exactly as today — no VideoEditor contract changes required.

- **R10.** New API keys (`PEXELS_API_KEY`, `BING_SEARCH_API_KEY`) are optional — the
  system degrades gracefully if they're absent, falling back to Google News thumbnails
  or skipping `image_montage` entirely.

## Success Criteria

- A viewer watching the body segment can identify the topic from the b-roll alone
  (no captions needed) — authentic, not generic.
- `browser_visit` or `image_montage` or `code_walkthrough` is selected for ≥ 80% of
  topics; `ai_video` is the last resort, not the default.
- GPU pod is NOT started on days when all 3 topics have CPU-viable b-roll (cost = $0
  for b-roll on those days).
- Each b-roll type produces valid output within 60 seconds for CPU types, 3 minutes for
  `ai_video`.
- Zero visible encoding artifacts or black frames in the final assembled video.

## Scope Boundaries

- One b-roll clip per video — not multiple segments or picture-in-picture (follow-on).
- `VideoEditor.assemble()` contract is unchanged — this is purely a generator-layer change.
- No live video capture (no scrolling animation of an actual browser in motion) — static
  screenshot + FFmpeg animation only. True browser recording is a future upgrade.
- No audio in b-roll clips — audio track comes from the voiceover only.
- Copyright compliance: only use Pexels/Bing licensed sources for `image_montage`;
  Google News thumbnails are used only as low-res fallback.

## Key Decisions

- **GPU stays, not as primary**: `ai_video` is always available but only invoked when
  CPU types fail or the topic is genuinely abstract. RunPod Phase 2 still exists but
  many days will skip it entirely — reducing cost without eliminating capability.
- **Single clip, not multi-segment**: Keeps VideoEditor unchanged. Multi-segment
  composition (e.g. "code walkthrough for 10s, then browser visit for 20s") is a
  compelling follow-on but adds VideoEditor complexity out of scope here.
- **BrollSelector is AI-driven**: Claude analyzes the topic rather than rigid regex
  rules — the topic "OpenAI releases new API for real-time voice" needs code_walkthrough,
  not image_montage, and only LLM analysis can catch that reliably.
- **Multi-source images, graceful degradation**: No single image source should be a
  hard dependency. The system works (at lower quality) with zero API keys.

## Dependencies / Assumptions

- Playwright (or similar headless browser) installed on the pipeline host machine.
- `PEXELS_API_KEY` and/or `BING_SEARCH_API_KEY` available as optional env vars.
- FFmpeg available on host (already assumed by VideoEditor).
- PIL/Pillow and Pygments installed (likely already in requirements.txt).
- Claude API available for `BrollSelector` and `code_walkthrough` generation
  (already required by the main pipeline).

## Outstanding Questions

### Deferred to Planning
- [Affects R2][Technical] Exact FFmpeg filter graph for Ken Burns slideshow
  (zoompan + xfade — reference existing broll_generator.json for starting point).
- [Affects R2][Technical] Playwright async API vs sync subprocess call — which is
  cleaner given the async pipeline context?
- [Affects R5][Technical] Should `BrollSelector` use a structured output Claude call
  returning JSON, or a free-text call parsed with regex? Structured output is safer.
- [Affects R7][Technical] Phase restructure: does moving CPU b-roll to Phase 1 require
  changes to the `VideoJob` dataclass or `run_daily()` control flow?
- [Affects R8][Needs research] Does Playwright handle Cloudflare/anti-bot pages cleanly,
  or does it require stealth mode plugins for news sites?

## Next Steps
→ `/ce:plan` for structured implementation planning
