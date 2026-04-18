---
date: 2026-04-18
topic: engagement-layer-v2
---

# Engagement Layer v2 — Synced Phone-Highlight, Animated Captions, Tweet & A/B Reveals, Cinematic Charts

## Problem Frame

Today's CommonCreed shorts ship with seven b-roll generators (browser_visit, image_montage, code_walkthrough, stats_card, ai_video, emphasis_card, stock_video) plus bold overlay titles. The visual layer works, but the channel still reads as "automated 2024" against the 2026 retention bar:

- B-roll segments mostly look like passive Ken-Burns scrolls of a webpage. They communicate "here is the article" but never deliver the goosebump moment of "the words I am hearing right now are highlighted on the screen as I read along."
- Burned-in captions exist (faster-whisper word timestamps already flow through `VideoEditor.assemble`) but render as static blocks. Top tech-news shorts in 2026 universally use word/phrase-level animated captions that pop, scale, or color the active token, paired with a sub-200 ms SFX transient on every cut.
- Story beats that are tailor-made for AI news — a Sam Altman tweet, a "Sora 2 vs Veo 3" benchmark — currently render as generic browser visits or stat cards instead of as the dedicated visual formats viewers expect from MattVidPro / Matt Wolfe / TLDR News shorts.
- Animated charts and data visualizations (numbers ticking up as they're spoken) require a programmatic video toolchain we don't have.

This brainstorm captures the engagement-layer techniques that all share the same substrate: existing audio + script + word timestamps, processed via FFmpeg / Playwright / a small Remotion sidecar. None of the work in this doc requires GPU-side changes, no new stock-clip mining, no avatar changes.

Two adjacent ideas — sourcing real third-party footage clips, and stylized animated hooks (Ghibli) — are deferred to sibling brainstorms (see *Spin-Off Brainstorms* below). They're real and important; they're just architecturally distinct enough that bundling them here would balloon the planning surface.

## Requirements

### Tier A — Ship first (table-stakes for 2026)

- **R1. Phone-mockup synced article highlight as a new b-roll type.** A vertical 1080×1920 view of a phone screen rendering the article being narrated, with the currently-spoken phrase highlighted in a colored box. The view auto-scrolls so the active phrase stays in the upper third of the screen. Visually matches the reference frame at `docs/ideas/text_highlight.png`. Selectable by the existing `BrollSelector` for any topic with a fetchable article URL.

- **R2. Animated word-level captions burned into every short.** Replace today's static caption block with a per-word reveal where each word fades/pops in at its spoken timestamp, with the active word highlighted in the brand color. Applied uniformly across all final shorts (avatar segments, b-roll segments, emphasis cards). Continues to use the existing `caption_segments` data structure produced by faster-whisper.

- **R3. Zoom-punch on keyword segments.** A 1.05–1.20× scale snap (3–6 frames) timed to the start of every "high-value token" — proper nouns, model names, dollar figures, percentages — paired with a sub-200 ms SFX transient. The Claude timeline planner emits a `keyword_punch` event list; the renderer applies it during final assembly.

- **R4. SFX library + auto-placement.** A vetted, license-clean library of ~15 short transient SFX (whoosh, pop, ding, thud, tick, swoop). Stored in-repo. The renderer auto-places one SFX at every visible cut, every overlay reveal, and every keyword-punch from R3. Volume normalized to sit under the voiceover.

### Tier B — Differentiator formats (second wave)

- **R5. Tweet/X-post reveal as a new b-roll type.** Renders a styled X (formerly Twitter) post card — author name, handle, verified mark, body text, like-counter, optional embedded image — as a slide-in clip. The like counter animates from 0 → final value across ~1.5 s. Designed for AI-news topics where the source material is or quotes a tweet from a known figure (founders, researchers, journalists). Selectable when the topic content surfaces a quoted statement attributable to a named person.

- **R6. A/B split-screen comparison as a new b-roll type.** Vertical 50/50 split frame with two contrasted visuals (model A vs model B, before/after, two screenshots) and a center wipe transition that reveals each side. Selectable when the topic is fundamentally a comparison (keywords like "vs", two named models, two products, "before/after").

- **R7. Editing-rhythm rules in the timeline planner.** The Haiku timeline planner is taught the 2026 rhythm: cut every 2–4 s; place a b-roll cut, image, or text card on every concrete proper-noun or numeric token; insert a "burst sequence" (5–10 quick cuts) approximately every 15 s as a retention reset. The planner emits a denser segment timeline than today.

### Tier C — Cinematic data visualization

- **R8. Remotion sidecar for templated animated charts and diagrams.** A small Node-based microservice (Remotion + Chrome Headless) packaged as a separate Docker container alongside the existing sidecar, exposing a single HTTP endpoint that takes a JSON spec (chart type, data points, voiceover audio, target duration) and returns an MP4. Used by a new `cinematic_chart` b-roll type for any topic that has clear numeric comparisons (benchmark scores, model sizes, cost figures) where a static `stats_card` no longer reads as engaging enough.

## Success Criteria

- After Tier A ships, viewers watching a short on a muted feed can identify the topic and the key facts from on-screen visuals alone, in the first 5 seconds.
- The synced phone-highlight visibly tracks the voiceover at the phrase level — when the voiceover speaks the phrase "GPT-5 just launched", that exact phrase is the active highlighted region on screen at the same moment.
- Every final short carries (a) animated captions, (b) at least one keyword-punch + SFX moment in the first 3 s, (c) at least one cut every 4 s during the body.
- After Tier B ships, the channel produces at least one tweet-reveal beat or A/B-split beat per video on topics where they apply (target: ≥40% of shipped videos use one of the two new formats).
- Tier C is considered successful when the cinematic chart format ships at least once per week as a hero beat in a benchmark/release video without manual intervention.
- Operationally: the Tier A renderer adds no more than 90 s to a 60 s short's total render time on the existing CPU pipeline. Tier C adds no more than 60 s when invoked.

## Scope Boundaries

- **No source-video clipping.** Mining YouTube / Reddit / NASA / archive.org for real third-party footage is a separate brainstorm (`source-clipping-pipeline`). The phone-highlight in R1 is rendered from cleaned article text in our own HTML template — never a screenshot of the live page.
- **No stylized animated hook visuals.** Ghibli/anime-style hooks requiring local GPU generation are a separate brainstorm (`stylized-hook-visuals`). The hook segment in this doc keeps using existing avatar / browser / image-montage formats.
- **No avatar lip-sync or generation changes.** The avatar provider continues to be selected as today. R2 captions are layered on top of the assembled video, not generated by the avatar.
- **No new social-caption / metadata changes.** `caption_gen.py` (which writes IG captions and YT titles) is unchanged. R2's "captions" refers to burned-in on-video subtitle text, not the social copy.
- **Existing b-roll types remain unchanged.** R1, R5, R6 are net-new generators added to the catalog. The existing seven generators keep working; the `BrollSelector` is extended, not rewritten.
- **No multi-segment composition refactor.** The `VideoEditor.assemble()` contract continues to take one b-roll path per video. Internal segments within b-roll generators (multi-shot timelines) remain a generator-internal concern, as they are today for `browser_visit`.
- **Tier C may slip without blocking Tiers A and B.** R8 introduces a new Docker container and a new language runtime (Node) into the deployment surface. If that proves materially more painful than expected, Tier C ships separately or is scoped down to "static animated chart PNG sequence rendered via Pillow" as a fallback.

## Key Decisions

- **Phrase-level highlight, not per-word, in R1.** Per-word strobing reads as anxious in 9:16 at arm's length; phrases of 3–7 words land cleanly. Phrase boundaries come from punctuation in the script + small-gap heuristics, with timestamps from the existing word-level data.
- **DOM-based highlight rendering for R1, not FFmpeg `drawbox` + `drawtext`.** Multi-line rounded highlight boxes with proper wrapping require CSS `box-decoration-break: clone`; FFmpeg primitives can't reproduce this cleanly. The phone view is a Playwright-rendered HTML template, screenshotted once per timeline event.
- **Article text is extracted, not screenshotted.** Article HTML is fetched and parsed with a clean-text extractor (Trafilatura or equivalent), then re-rendered into our own phone template. This sidesteps paywalls, JS-heavy DOMs, font fallbacks, and CMP banners — and gives stable per-word DOM coordinates.
- **R1 and R2 reuse existing `caption_segments`; do not introduce WhisperX in this work.** Faster-whisper word timestamps already flow through `VideoEditor.assemble`. They're accurate enough for phrase-level highlighting and animated captions. Upgrading to WhisperX (forced alignment) is a follow-up improvement, not a prerequisite.
- **Highlight color is brand-controlled, not article-adaptive.** Use a single CommonCreed accent color for the highlight box across all videos. This sacrifices some per-video aesthetics for stronger channel identity at the thumbnail-feed level. (If readability suffers on dark-mode articles, the phone template forces a light background.)
- **Brand palette derived from the CommonCreed wordmark** (navy + sky blue + white). Locked values for this work:
  - Highlight box fill (R1 phone-highlight, R2 active caption word background): `#5C9BFF` (CommonCreed sky blue)
  - Text on highlight box: `#FFFFFF` (matches the "Creed" wordmark)
  - Inactive caption word color: `#FFFFFF` with `#1E3A8A` (CommonCreed navy) drop-shadow at ~70% opacity
  - Emphasis card background (existing R3 from prior work): keep as today, but verify it doesn't clash with the new accent
  - Tweet-card chrome (R5): use white card on a navy `#1E3A8A` matte instead of X's native dark theme — keeps it on-brand
  - A/B split divider (R6): 6 px `#5C9BFF` line with a soft white glow
- **Success metric is a composite, not a single number.** Tier A is judged against a small dashboard:
  1. **Primary (decision metric):** combined retention score = average of (IG Reels view-through-rate from Postiz analytics, 14-day pre vs post) and (YT Shorts average view duration % from YT Studio export, 14-day pre vs post). Target: ≥10% improvement over baseline.
  2. **Secondary (sanity check):** first-3-second drop-off rate. Target: improve or hold flat — never regress.
  3. **Per-platform guardrail:** no platform regresses by more than 5% on its native retention metric.
  4. **Operational guardrail:** added render time per short stays within the budget defined in *Success Criteria* (≤ 90 s for Tier A; ≤ 60 s for Tier C).

  Tier A is shipped successfully iff (1) clears +10%, (2) does not regress, (3) no per-platform > 5% loss, and (4) render time stays in budget. A composite avoids over-fitting to one platform's noisy weekly data, and the guardrails prevent shipping a "wins on average, breaks on one platform" regression.
- **Captions in R2 are rendered via FFmpeg + ASS subtitles with karaoke timing tags**, not per-frame compositing. ASS files generated from existing word timestamps are the cheapest path that supports per-word styling and color tweens.
- **SFX library is a one-time vendor-vetted asset bundle**, checked into the repo (license must permit commercial use). No SFX-licensing API; no per-video SFX generation; no AI-generated SFX. Predictability and zero-runtime-cost are more important than variety here.
- **Remotion for Tier C, not Hyperframes / Motion Canvas / Manim.** Hyperframes was open-sourced 2026-04-17 and has no production track record. Motion Canvas has no real headless-rendering path. Manim is a math-explainer tool. Remotion is the only option that is genuinely production-headless on Linux, audio-frame-accurate, and free at solo-operator scale.
- **A/B split (R6) sources its two sides from existing b-roll generators.** Each side is rendered as a tall ½-width clip via the same primitives (browser_visit, image_montage, stats_card). The split-screen generator is a composer, not a separate fetcher.
- **The tweet-reveal generator (R5) does not query the X API.** Tweet content is reconstructed from text quoted in the source article; the visual is a static styled card we render ourselves. This avoids OAuth, rate limits, and changing T&Cs. Author handle / verified status / tweet text come from the article content, with Haiku filling in any missing fields conservatively.
- **Editing-rhythm rules (R7) ship as a system-prompt update to the existing timeline planner.** No new planner; same Haiku call, denser segment output. If the resulting timelines exceed the avatar+b-roll duration budget, the planner is asked to compact, not the renderer to truncate.

## Dependencies / Assumptions

- `faster-whisper` is already part of the pipeline and produces per-word timestamps in `caption_segments`. (Verified — `scripts/commoncreed_pipeline.py:580`, `scripts/video_edit/video_editor.py:135`.)
- Playwright is already installed and used by `browser_visit`. R1 reuses the same Playwright instance with iPhone-14 device emulation.
- FFmpeg has libass support enabled (required for ASS karaoke subtitles in R2). Verify on the production Ubuntu box before planning.
- The `BrollSelector` is the canonical extension point for new b-roll types. R1, R5, R6, plus the Tier-C `cinematic_chart` are all added to its catalog.
- The Haiku timeline planner is the canonical extension point for R7 and for `keyword_punch` event emission in R3.
- The Tier C Remotion sidecar shares the existing Portainer-managed deployment plane (`192.168.29.237`, Keychain `commoncreed-portainer-new`) but lives in its own container.
- Brand color for R1 highlight + R2 active-word color is decided product-side; assumed to be a single value that survives both light and dark templates.

## Outstanding Questions

### Resolve Before Planning

- _(All blocking questions resolved. See *Key Decisions* for brand palette and success metric resolutions.)_

### Deferred to Planning

- **[Affects R1][Technical]** Should the phone template render once with all phrases pre-marked and animate via CSS, or should we render N PNGs (one per timeline event) and concat in FFmpeg? The latter is simpler, the former is faster on long articles. Decide during planning based on a benchmark.
- **[Affects R1][Needs research]** How does the phone template handle articles longer than ~6 paragraphs? Crop to lead + 2 paragraphs picked by Haiku, or render full and rely on auto-scroll? Decide when planning the article-extraction step.
- **[Affects R2][Technical]** ASS karaoke vs FFmpeg drawtext per-word: ASS is cleaner for color tweens but requires libass; drawtext works with stock FFmpeg. Confirm libass on the production server, then pick.
- **[Affects R3][Technical]** Where does the keyword-punch effect run — inside the avatar segment renderer, the b-roll segment renderer, or a final-pass overlay? Likely the latter, but verify the cleanest insertion point in `VideoEditor`.
- **[Affects R4][Needs research]** Which specific SFX pack do we use? Candidates include free CC0 Pops & Dings collections; needs a sampling pass + license confirmation.
- **[Affects R5][Technical]** Tweet-card visual style: stay close to the current X dark theme, or build a CommonCreed-branded variant? Either way, render as a Pillow- or Playwright-driven template.
- **[Affects R5][Technical]** How does the planner detect that an article quotes a known figure? Likely Claude Haiku in the existing topic-selection step, returning a structured `tweet_quote` field when applicable.
- **[Affects R6][Technical]** A/B split asset sourcing on benchmark topics — both sides may want to be `stats_card` variants; can the existing stats card render at half-width without layout breakage?
- **[Affects R7][Technical]** What's the maximum segment count per video the timeline planner can emit before downstream assembly times out? Need a budget so denser planning doesn't blow render times.
- **[Affects R8][Technical]** Remotion Docker base image size and Portainer wiring — straightforward but needs confirmation that the additional ~1.5 GB image is acceptable on the production server's disk.
- **[Affects R8][Technical]** What chart templates ship with Tier C? Minimum viable: animated bar chart, animated number ticker, animated line chart. Decide during planning.

## Spin-Off Brainstorms (recommended)

The other ideas in `docs/ideas/better_brolls_and_footage.md` are deferred to sibling brainstorms because they are architecturally distinct and would balloon planning here:

- **`source-clipping-pipeline`** — Mining YouTube CC-BY, Reddit, NASA / archive.org for real topic-relevant footage; transcript-based clip selection; talking-head rejection via MediaPipe; rights/attribution storage. Self-contained pre-fetch stage.
- **`stylized-hook-visuals`** — Stylized hook visuals on the local 3090: SDXL/Flux + Studio Ghibli LoRA + PuLID-Flux for character likeness, paired with light motion (Ken Burns or low-strength Wan2.1 I2V). Operates on the same GPU as avatar generation, so needs explicit scheduling design.

Both have research notes captured in this brainstorm's research transcripts; pick them up as separate `/ce:brainstorm` runs when this doc's scope is in flight.

## Next Steps

→ `/ce:plan` for structured implementation planning.
