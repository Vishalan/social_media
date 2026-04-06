---
title: "feat: Eye-catching thumbnail engine with platform-aware cover delivery"
type: feat
status: completed
date: 2026-04-06
origin: docs/brainstorms/2026-04-06-thumbnail-engine-requirements.md
---

# feat: Eye-Catching Thumbnail Engine

## Overview

Add a thumbnail generation step to the CommonCreed video pipeline that produces a 1080x1920 PNG per video (LLM-generated headline + avatar cutout + on-topic background), bakes it as a held first frame in the final MP4 for TikTok compliance, and delivers it as an explicit cover via Postiz for YouTube and Instagram. This is the first feature to integrate with the new self-hosted Postiz posting layer (replacing Ayrshare).

## Problem Frame

CommonCreed currently ships videos with whatever frame IG/YT/TikTok auto-pick — usually a mid-talk avatar shot with no topic context. Thumbnails are the highest-leverage CTR lever, and the current pipeline leaves it to chance. (see origin: docs/brainstorms/2026-04-06-thumbnail-engine-requirements.md)

## Requirements Trace

- R1. Per-video 1080x1920 thumbnail PNG saved next to final MP4
- R2. Picked up as cover on IG/YT (Postiz API) and TikTok (baked first frame + `video_cover_timestamp_ms=0`)
- R3. MrBeast tech-news look — bold headline, avatar cutout, on-topic background
- R4. Headline + face inside center-safe zone; survives 1:1 crop
- R5. LLM-generated punchy 3-5 word headline (Claude Haiku)
- R6. Pexels/article image background with darken overlay; gradient fallback
- R7. Cached avatar cutout (one-time bg removal)
- R8. Pipeline-safe with text-only fallback on any failure
- R9. < $0.02/video added cost, < 10s added time, no GPU

## Scope Boundaries

- NOT building Postiz deployment itself — assumes Postiz is reachable on Synology/Portainer (separate ops task)
- NOT removing the existing Ayrshare code path in this plan — leave it dormant; full removal is a follow-up
- NOT generating thumbnail variants for A/B testing
- NOT swapping the avatar portrait per video
- NOT building a thumbnail editor UI

## Context & Research

### Relevant Code and Patterns

- `scripts/content_gen/script_generator.py` — `ScriptGenerator` already uses Claude (Haiku for cheap calls). Mirror its prompt/response pattern for headline generation.
- `scripts/broll_gen/` — existing Pexels/article image fetch pipeline. Reuse its image discovery output rather than re-fetching.
- `scripts/video_edit/video_editor.py` — `_assemble_broll_body()` builds the unified `final_make_frame(t)`. The held first frame must integrate here without disturbing the avatar sync timeline. Critical: hook/pip1/pip2/cta windows are computed from `audio_duration` — the held frame must NOT shift those windows.
- `scripts/smoke_e2e.py` — pipeline orchestrator with `step_*` functions and `_compute_avatar_windows()`. New `step_thumbnail()` slots in here.
- `scripts/posting/social_poster.py` — `SocialPoster` class. Add a new `PostizPoster` backend alongside existing Ayrshare path.
- `assets/logos/owner-portrait-9x16.jpg` — source portrait for cutout (765x1360).
- `output/debug_avatar/` — existing debug-asset pattern for verifying intermediate artifacts.

### Institutional Learnings

- `docs/solutions/integration-issues/avatar-lip-sync-desync-across-segments-2026-04-05.md` — avatar sync depends on `audio_duration` driving `_compute_avatar_windows()`. **Any prepended frame must add to the visual timeline only, not the audio timeline that drives avatar windows.** This is the single biggest risk in this plan.

### External References

- Postiz public API: `POST /public/v1/posts` with API key auth — per-platform settings dict supports `thumbnail` (YT), `coverUrl` (IG), and `videoCoverTimestampMs` (TikTok). Verify exact field names at integration time.
- TikTok Content Posting API: only `video_cover_timestamp_ms` is honored — confirmed in `reference_tiktok_cover_limit` memory.
- `rembg` (CPU ONNX, MIT) — local one-time portrait background removal, ~2s on first run, then cached.

## Key Technical Decisions

- **Thumbnail step runs BEFORE final video assembly** — needs to exist on disk so the held first frame can reference it, and so Postiz can upload the standalone PNG. Slot in after `step_script` (script available for headline) and before `step_assemble`.
- **Held frame is added at the visual layer only** — `final_make_frame(t)` gets a `_THUMBNAIL_HOLD_S = 0.5` prepend, but `audio_duration` and `_compute_avatar_windows()` continue to operate on the speech audio only. The first 0.5s of the video plays the thumbnail with silent audio; speech starts at t=0.5s. This keeps the avatar sync algorithm completely untouched.
- **Compositing in Pillow, not MoviePy or FFmpeg filters** — Pillow gives pixel-precise control over text layout, drop shadows, and the safe-zone constraint. Output is a single PNG; MoviePy ingests it as an ImageClip for the held frame.
- **Headline via Claude Haiku, single call, deterministic prompt** — Reuse the same `anthropic.Anthropic` client already in `script_generator.py`. Prompt asks for exactly one 3-5 word headline, ALL CAPS, no punctuation. Cost ~$0.0005/video.
- **Avatar cutout cached on disk under `assets/logos/owner-portrait-9x16-cutout.png`** — generated once with `rembg`, committed-or-gitignored per existing asset convention. Pipeline checks-then-generates so first-time setup is automatic.
- **Background image source is the b-roll pipeline's first article image** — already on-topic and already fetched. If unavailable, fall back to a branded gradient (no extra Pexels call needed).
- **Postiz integration is a NEW backend, not a replacement of `SocialPoster`** — add `PostizPoster` as a sibling class. The pipeline picks the backend via `POSTING_BACKEND` env var (`postiz` | `ayrshare`). Default to `postiz` once the new path is verified end-to-end. This keeps the working Ayrshare path as a rollback.
- **Failure isolation** — `step_thumbnail()` is wrapped in try/except. On failure, write a minimal text-only fallback PNG (headline on solid color), log a warning, and continue. The pipeline never breaks for thumbnail reasons.

## Open Questions

### Resolved During Planning

- **Where does the held first frame attach?** Inside `final_make_frame(t)` in `video_editor.py`, gated by a constant `_THUMBNAIL_HOLD_S`. Audio timeline is offset by the same constant, but `_compute_avatar_windows()` is NOT — it operates on the speech-only audio reference.
- **Is the headline LLM call separate or part of script generation?** Separate — keeps script generation untouched and allows headline regeneration without re-running script. Same Haiku client.
- **How is Postiz picked vs Ayrshare?** `POSTING_BACKEND` env var with `postiz` default once integration is verified. Both classes implement the same `post(video_path, caption, thumbnail_path)` interface.

### Deferred to Implementation

- Exact Postiz API field names for per-platform thumbnail upload — verify against the running Postiz instance at integration time. The API has evolved across versions.
- Font choice — check what's installed on the pipeline host (Inter Black, Anton, Bebas Neue are candidates). Bundle one in `assets/fonts/` if nothing suitable is present.
- Whether the held first frame survives the existing FFmpeg encoder settings as a clean keyframe — verify with `ffprobe` on the first generated video. If not, force a keyframe at t=0 via `-force_key_frames`.
- `rembg` model variant — `u2net` vs `u2netp` (lighter). Decide based on cutout quality on the first run.
- Whether to commit the cutout PNG or gitignore it — check existing `assets/` convention.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
┌─────────────────┐
│  step_script    │  → script.json (existing, unchanged)
└────────┬────────┘
         │
┌────────▼────────┐
│ step_thumbnail  │  NEW
│                 │  1. Headline = Haiku(script)
│                 │  2. Background = first b-roll image (or gradient)
│                 │  3. Cutout = cached owner-portrait cutout
│                 │  4. Compose in Pillow → 1080x1920 PNG
│                 │  5. Save → output/<run>/thumbnail.png
└────────┬────────┘
         │
┌────────▼────────┐
│  step_avatar    │  (existing — unchanged, uses speech audio only)
└────────┬────────┘
         │
┌────────▼────────┐
│  step_broll     │  (existing — unchanged)
└────────┬────────┘
         │
┌────────▼────────┐
│  step_assemble  │  MODIFIED
│                 │  final_make_frame(t):
│                 │    if t < HOLD: return thumbnail
│                 │    else:        existing logic with t -= HOLD
│                 │  audio:
│                 │    silence(HOLD) ++ existing speech track
│                 │  avatar windows: UNCHANGED (speech-only timeline)
└────────┬────────┘
         │
┌────────▼────────┐
│   step_post     │  MODIFIED
│                 │  PostizPoster.post(video, caption, thumbnail_path)
│                 │  → YT: thumbnail upload
│                 │  → IG: cover upload
│                 │  → TT: videoCoverTimestampMs=0
└─────────────────┘
```

Key invariant: the speech audio timeline that drives `_compute_avatar_windows()` is never shifted by the thumbnail. Only the final composed audio + video timeline is offset.

## Implementation Units

- [x] **Unit 1: Headline generator**

**Goal:** Generate a punchy 3-5 word ALL CAPS headline from the script using Claude Haiku.

**Requirements:** R5

**Dependencies:** None

**Files:**
- Create: `scripts/thumbnail_gen/__init__.py`
- Create: `scripts/thumbnail_gen/headline.py`
- Create: `scripts/thumbnail_gen/tests/test_headline.py`

**Approach:**
- New module `thumbnail_gen.headline.generate_headline(script_text: str, client) -> str`
- Reuse the existing `anthropic.Anthropic` client construction pattern from `scripts/content_gen/script_generator.py`
- Single Haiku call, temperature low (0.4), explicit prompt asking for exactly one 3-5 word headline, ALL CAPS, no punctuation, no quotes
- Validate response: enforce word count 2-6, strip punctuation, uppercase. If validation fails, retry once; on second failure raise — caller handles fallback.

**Patterns to follow:**
- `scripts/content_gen/script_generator.py` Haiku invocation pattern

**Test scenarios:**
- Returns 3-5 word ALL CAPS string for a normal script
- Strips trailing punctuation and quotes from model output
- Raises after one retry on persistently invalid output
- Empty script input raises ValueError before calling the model

**Verification:**
- Unit tests pass; manual smoke shows headlines like "AI BREAKS THE INTERNET" or "GOOGLE'S NEW BOMB"

---

- [x] **Unit 2: Cached portrait cutout**

**Goal:** Produce a transparent-background portrait cutout once, cache it on disk, reuse forever.

**Requirements:** R7

**Dependencies:** None (parallel with Unit 1)

**Files:**
- Create: `scripts/thumbnail_gen/cutout.py`
- Modify: `requirements.txt` (add `rembg`)
- Create or use: `assets/logos/owner-portrait-9x16-cutout.png` (generated artifact)

**Approach:**
- New module function `ensure_portrait_cutout(source_path, cache_path) -> Path`
- If cache file exists and is newer than source, return it. Otherwise run `rembg` once on the source and write to cache.
- Wrap `rembg` import in a try block — if not installed, raise a clear ImportError with install hint.
- Function is called once per pipeline run from `step_thumbnail`.

**Test scenarios:**
- Cache hit returns existing path without invoking rembg
- Cache miss generates the cutout and persists it
- Source file newer than cache invalidates cache
- Output PNG has alpha channel and matches source dimensions

**Verification:**
- Running the function twice in the same session only invokes rembg once
- Generated cutout opens in any image viewer with transparent background

---

- [x] **Unit 3: Pillow compositor**

**Goal:** Compose the final 1080x1920 thumbnail PNG from headline + background image + cutout, respecting safe zones.

**Requirements:** R1, R3, R4, R6

**Dependencies:** Unit 2

**Files:**
- Create: `scripts/thumbnail_gen/compositor.py`
- Create: `scripts/thumbnail_gen/tests/test_compositor.py`
- Create: `assets/fonts/` directory with one bundled bold font (e.g., Inter Black or Anton TTF) — or document fallback to system font
- Create: `scripts/thumbnail_gen/tests/fixtures/sample_bg.jpg`

**Approach:**
- `compose_thumbnail(headline: str, background_path: Path | None, cutout_path: Path, output_path: Path) -> Path`
- Canvas: 1080x1920 RGB
- Background: load image, center-crop to 1080x1920, apply 50% darken gradient (top→bottom or radial)
- If `background_path` is None or load fails: render branded gradient (two-color vertical)
- Cutout: scale to 60% canvas height, paste right-aligned with bottom anchor at y=1536 (just above the bottom UI safe zone)
- Headline: bold font, white text with strong drop shadow, size auto-fit so the longest word fits within 80% canvas width, vertical-centered in the middle safe zone (y range 290-1530)
- Add a bright accent bar/box behind one keyword for visual punch (optional polish)
- Save as PNG, return path

**Safe zones (R4):**
- Top reserved (UI): y=0 to y=288 (15%)
- Bottom reserved (UI): y=1536 to y=1920 (20%)
- 1:1 center crop survives: x=0 to x=1080 (full width), y=420 to y=1500
- Headline must fit in y=420 to y=1500 for grid-view survival

**Test scenarios:**
- Composes successfully with valid bg image
- Composes successfully with `background_path=None` (gradient fallback)
- Composes successfully when bg load raises (gradient fallback)
- Long headline (5 words, longest word 12 chars) fits within 80% width
- Output dimensions are exactly 1080x1920
- Output has non-zero pixels in the center safe zone (sanity check)

**Verification:**
- Generate thumbnails for 3 sample headlines and visually inspect at 200px width — headline readable, face recognizable

---

- [x] **Unit 4: Pipeline integration as `step_thumbnail`**

**Goal:** Wire the thumbnail step into the smoke_e2e pipeline with full failure isolation.

**Requirements:** R1, R8, R9

**Dependencies:** Units 1, 2, 3

**Files:**
- Modify: `scripts/smoke_e2e.py`
- Modify: `scripts/pipeline.py` (if it has a separate orchestration path)
- Create: `scripts/thumbnail_gen/tests/test_pipeline_integration.py`

**Approach:**
- New function `step_thumbnail(script, run_dir, config)` that:
  1. Calls `generate_headline(script_text)` — on failure, use first 3-5 words of script as fallback
  2. Resolves background image from b-roll pipeline output (first available article image), or None
  3. Calls `ensure_portrait_cutout(...)` — on failure, render text-only thumbnail
  4. Calls `compose_thumbnail(...)` to write `<run_dir>/thumbnail.png`
  5. Returns the path
- Wrap the entire step in try/except. On any unhandled exception, write a minimal text-only fallback PNG (just headline on solid dark background) and log a warning. The step ALWAYS returns a valid path.
- Slot the call in `smoke_e2e.py` after script generation and before avatar/broll generation (so b-roll image discovery results, if cached, can be reused — otherwise pass None).
- Total step time budget: < 10s (rembg first-run excluded — that's a one-time install cost).

**Test scenarios:**
- Happy path: produces a valid PNG and returns its path
- Headline LLM failure: falls back to script-derived headline, still produces PNG
- Cutout module unavailable: text-only fallback PNG produced
- Compositor failure: text-only fallback PNG produced
- Step never raises out of `smoke_e2e.py`

**Verification:**
- Run smoke pipeline end-to-end; `<run_dir>/thumbnail.png` exists and is valid
- Verify with a forced headline failure that the pipeline still completes and produces a fallback thumbnail

---

- [x] **Unit 5: Held first frame in video assembly**

**Goal:** Prepend a 0.5s held thumbnail frame to the final video without disturbing the avatar sync timeline.

**Requirements:** R2 (TikTok path), R3

**Dependencies:** Unit 4

**Files:**
- Modify: `scripts/video_edit/video_editor.py` — `_assemble_broll_body()` and `final_make_frame()`
- Create: `scripts/video_edit/tests/test_thumbnail_hold.py`

**Approach:**
- Add module constant `_THUMBNAIL_HOLD_S = 0.5`
- In `_assemble_broll_body()`, accept new optional parameter `thumbnail_path: Path | None = None`
- If `thumbnail_path` is provided:
  - Load thumbnail as a static numpy array once, outside `final_make_frame`
  - Modify `final_make_frame(t)` to return `thumbnail_array` when `t < _THUMBNAIL_HOLD_S`, else recurse into existing logic with `t' = t - _THUMBNAIL_HOLD_S`
  - Build final audio as `silence(_THUMBNAIL_HOLD_S) + existing_speech_audio` using MoviePy `concatenate_audioclips` or numpy padding
  - Final video duration becomes `existing_duration + _THUMBNAIL_HOLD_S`
- **CRITICAL invariant**: `_compute_avatar_windows()` continues to receive the speech-only `audio_duration`. The hold offset is applied ONLY when assembling the final video — avatar windows are never shifted.
- After encoding, run `ffprobe` (or programmatic equivalent) to verify a keyframe exists at t=0. If not, set `ffmpeg_params=["-force_key_frames", "0"]` on the MoviePy write call.

**Execution note:** Test-first for the avatar-sync invariant. Write a regression test that asserts `_compute_avatar_windows()` returns identical windows whether or not a thumbnail is prepended. The avatar sync solution doc explicitly warns against shifting this timeline.

**Patterns to follow:**
- Existing `final_make_frame(t)` unified-render pattern in `video_editor.py`
- Pre-read frames into memory pattern already used for avatar arrays

**Test scenarios:**
- Thumbnail-prepended video has a frame matching the thumbnail PNG at t=0
- Speech audio starts at exactly t=0.5s in the final track
- Avatar windows from `_compute_avatar_windows()` are byte-identical with and without `thumbnail_path`
- Final duration = speech_duration + 0.5
- `ffprobe` reports a keyframe at t=0 (or force-keyframes flag is in the write args)
- `thumbnail_path=None` produces identical output to current behavior (zero-impact regression test)

**Verification:**
- Visual inspection: first ~0.5s of generated video shows the thumbnail, then video continues identically to current pipeline
- Avatar sync regression test from the prior solution doc still passes
- No regression in the working VEED avatar pipeline

---

- [x] **Unit 6: Postiz posting backend**

**Goal:** Add a `PostizPoster` backend that posts video + thumbnail to YT/IG/TikTok via the self-hosted Postiz API, selectable via env var.

**Requirements:** R2 (YT/IG paths)

**Dependencies:** Unit 5 (so videos with held frames are available for verification)

**Files:**
- Create: `scripts/posting/postiz_poster.py`
- Modify: `scripts/posting/social_poster.py` — add backend dispatch
- Modify: `scripts/posting/__init__.py` — export `PostizPoster`
- Modify: `config/settings.py` — add `POSTIZ_BASE_URL`, `POSTIZ_API_KEY`, `POSTING_BACKEND`
- Modify: `.env.example` — add Postiz vars
- Create: `scripts/posting/tests/test_postiz_poster.py`

**Approach:**
- New class `PostizPoster(base_url, api_key)` with method `post(video_path, caption, thumbnail_path, platforms: list[str])`
- POST to `<base_url>/public/v1/posts` with multipart: video file, caption, per-platform settings dict
  - `youtube`: `{ "thumbnail": <thumbnail file or url> }`
  - `instagram`: `{ "coverUrl": <thumbnail url> }` (verify exact field at integration time)
  - `tiktok`: `{ "videoCoverTimestampMs": 0 }`
- Auth header: `Authorization: <api_key>` (verify scheme at integration time — could be `Bearer` or raw)
- Retry policy: 2 retries with exponential backoff on 5xx; fail fast on 4xx
- Add factory function `make_poster(config) -> Poster` in `social_poster.py` that returns `PostizPoster` or `AyrsharePoster` based on `POSTING_BACKEND` env var (default: `postiz`)
- Existing Ayrshare code stays untouched as a rollback path

**Patterns to follow:**
- Existing `SocialPoster` interface — keep `PostizPoster` API-compatible so the pipeline doesn't care which backend is active
- `httpx` async client pattern from `scripts/avatar_gen/veed_client.py` if Postiz needs async; otherwise sync `requests` is fine

**Test scenarios:**
- Successful post returns the Postiz response with post IDs
- 5xx response retries twice then raises
- 4xx response raises immediately with the API error body
- Missing thumbnail_path raises ValueError before calling the API
- Factory returns `PostizPoster` when `POSTING_BACKEND=postiz`, `AyrsharePoster` when `=ayrshare`
- Mock-based unit tests for HTTP behavior; one optional integration test gated by env var that hits a real Postiz instance

**Verification:**
- Unit tests pass
- Manual integration test against the user's Synology Postiz instance: post one video, confirm it appears on IG/YT/TT with the generated thumbnail as cover
- Verify TikTok cover specifically — should match the held first frame, not a random mid-video frame

---

- [x] **Unit 7: End-to-end smoke test with cost gate**

**Goal:** Run the full pipeline once with the new thumbnail step + Postiz backend (in dry-run mode if possible) and verify all success criteria.

**Requirements:** All

**Dependencies:** Units 1-6

**Files:**
- Modify: `scripts/smoke_e2e.py` — extend the existing smoke run to assert thumbnail.png exists
- Create: `scripts/thumbnail_gen/tests/test_smoke_thumbnail.py` (optional integration test)

**Approach:**
- Run the existing smoke pipeline with one short topic
- Assert `output/<run>/thumbnail.png` exists, is 1080x1920, and has visible content
- Assert final video duration = speech_duration + 0.5s
- Assert avatar lip sync regression test still passes (from prior solution doc)
- Assert pipeline run-time delta < 10s vs prior baseline (rembg cache warm)
- Assert added cost < $0.02 (Haiku call only)
- For Postiz: run with `POSTIZ_DRY_RUN=1` if implemented, or stub the HTTP layer; manual real-post verification is a separate step

**Test scenarios:**
- Full happy path
- Thumbnail step forced to fail → fallback PNG produced, pipeline completes
- Postiz backend selected → factory dispatches correctly

**Verification:**
- Smoke run produces a valid thumbnail and a valid video
- All existing pipeline tests still pass
- Manual real-post test (separate from automated smoke) shows thumbnails on IG/YT/TT

## System-Wide Impact

- **Interaction graph:** New `step_thumbnail` slots between `step_script` and `step_assemble` in `smoke_e2e.py`. `_assemble_broll_body()` in `video_editor.py` gains one optional parameter. `social_poster.py` gains a factory + new backend class. No other modules touched.
- **Error propagation:** Thumbnail failures are caught and degraded to a text-only fallback inside `step_thumbnail` — failures never propagate to the caller. Postiz HTTP failures use retry-then-raise; the caller (pipeline) decides whether to abort or continue.
- **State lifecycle risks:** The held-frame logic must not shift the speech audio timeline that drives `_compute_avatar_windows()`. This is the single biggest correctness risk. Mitigated by the regression test in Unit 5 and by passing speech-only audio_duration explicitly to the windows function.
- **API surface parity:** `PostizPoster` and `AyrsharePoster` both implement the same `post(video, caption, thumbnail, platforms)` interface so the pipeline is backend-agnostic. The factory pattern ensures only one place chooses.
- **Integration coverage:** Unit-test the avatar-windows invariant directly. Smoke-test the full pipeline. Manual real-post verification on first 3 published videos to confirm covers actually appear on the platforms.

## Risks & Dependencies

- **Avatar sync regression** (highest risk): The held first frame could shift timestamps that the avatar sync algorithm depends on. Mitigated by routing the offset only through the visual/final-audio assembly and explicitly testing window invariance with and without the prepend.
- **Postiz API field uncertainty**: Exact field names for per-platform thumbnail upload may have evolved. Mitigated by deferring exact field names to integration time, isolating them in `postiz_poster.py`, and gating the rollout on a manual real-post verification.
- **Synology hardware capacity**: User mentioned Portainer on Synology but didn't specify the model. Postiz + Postgres + Redis needs ~1-2GB RAM. Mitigated by treating Postiz deployment as a separate ops task; this plan only consumes the API.
- **TikTok keyframe at t=0**: If FFmpeg's default encoder doesn't produce a clean keyframe at t=0, TikTok may grab a slightly later frame. Mitigated by `ffprobe` verification + `-force_key_frames 0` fallback.
- **rembg model download on first run**: ~150MB one-time download. Mitigated by documenting it in the README and pre-warming on the pipeline host.
- **Postiz AGPL license**: Acceptable for self-hosted internal use. No redistribution risk.

## Documentation / Operational Notes

- Add Postiz config keys to `.env.example`: `POSTIZ_BASE_URL`, `POSTIZ_API_KEY`, `POSTING_BACKEND`
- Add a one-paragraph note to `README.md` about the new thumbnail step and the Postiz backend
- Document the rembg first-run model download
- Manual ops task (out of scope for this plan): deploy Postiz on the user's Synology via Portainer using the official `docker-compose.yml`, complete OAuth for IG business / YT channel / TikTok creator / X
- Once Postiz path is verified on 3+ real posts, follow-up plan: remove Ayrshare entirely

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-06-thumbnail-engine-requirements.md](../brainstorms/2026-04-06-thumbnail-engine-requirements.md)
- Related code: `scripts/video_edit/video_editor.py`, `scripts/smoke_e2e.py`, `scripts/posting/social_poster.py`, `scripts/content_gen/script_generator.py`
- Related learning: `docs/solutions/integration-issues/avatar-lip-sync-desync-across-segments-2026-04-05.md`
- Related memories: `project_posting_layer.md`, `reference_tiktok_cover_limit.md`
- External: Postiz docs (`docs.postiz.com`), TikTok Content Posting API, `rembg` (`danielgatis/rembg`)
