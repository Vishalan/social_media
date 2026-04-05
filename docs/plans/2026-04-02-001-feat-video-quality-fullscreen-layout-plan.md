---
title: "feat: Full-screen b-roll layout, flat cards, stock video, short avatar"
type: feat
status: completed
date: 2026-04-02
origin: docs/brainstorms/2026-04-02-001-video-quality-fullscreen-layout-requirements.md
---

# feat: Full-screen b-roll layout, flat cards, stock video, short avatar

## Overview

Five improvements to close the quality gap between the current pipeline output and a reference high-performing video. The reference video uses full-screen b-roll during body segments (no talking-head overlay), cinematic stock footage, flat bold typography cards, and a minimal avatar appearance at hook and CTA only. The current pipeline overlays the avatar on b-roll for the entire video duration and generates an expensive full-duration avatar clip even though the avatar appears for only ~6 seconds.

## Problem Frame

Analysis of the reference video ("Axios Just Got Attacked") revealed five concrete gaps in the current pipeline output (see origin doc). The two highest-impact changes are (1) making body b-roll fill the entire 9:16 frame and (2) trimming avatar generation to only the ~6s where the face actually appears, cutting avatar cost by ~85%.

## Requirements Trace

- R1. Full-screen body layout — b-roll fills the entire 9:16 frame during body segments; avatar composited only at hook (~3s) and CTA (~3s)
- R2. Short avatar generation — only ~6s of avatar requested; WIP placeholder also switches to 6s once R1 is live
- R3. Flat-design `headline_burst` redesign — solid color backgrounds, ≥180px typography, no gradients
- R4. `stock_video` b-roll type — Pexels video API, cinematic clips, added to timeline planner
- R5. Content-crop browser screenshots — article bounding box used to crop viewport to content column

## Scope Boundaries

- No changes to voiceover or script generation
- No fal.ai video generation (Wan2.1 / ComfyUI) — stock video fills that role
- No short-form clip extraction changes
- Pexels only (not Pixabay, Getty, etc.)
- YouTube upload and social posting out of scope

## Context & Research

### Relevant Code and Patterns

- `video_edit/video_editor.py` — `AvatarLayout` enum (imported from `avatar_gen/layout.py`); `_assemble_half_screen()` (lines 126-206) already has hook / body / CTA three-segment structure with `HOOK_DURATION_S = 3.0` and `CTA_DURATION_S = 3.0` class constants; `_assemble_broll_only()` already scales b-roll to full `OUTPUT_WIDTH × OUTPUT_HEIGHT` — new method should mirror this pattern for body segment
- `avatar_gen/layout.py` — `AvatarLayout` enum with HALF_SCREEN, FULL_SCREEN, STITCHED, SKIPPED; new `BROLL_BODY` value goes here
- `avatar_gen/veed_client.py` — `VeedFabricClient._submit()` posts `{image_url, audio_url, resolution}` with no duration param; fal.ai endpoint (`https://queue.fal.run/veed/fabric-1.0`) does not accept a duration parameter; short avatar must be achieved by trimming the audio before upload
- `smoke_e2e.py` — `step_avatar(topic, audio_url, audio_duration)` calls `_make_wip_avatar(output_path, audio_duration)`; `step_upload()` uploads the audio and returns `audio_url`; `step_broll()` uses `target_duration_s = max(6.0, audio_duration - 6.0)`
- `broll_gen/factory.py` — generator registration via `if type_name == ...` branches; new generators require a branch here
- `broll_gen/selector.py` — `_VALID_TYPES` frozenset and `_RESPONSE_SCHEMA` enum arrays must include new type name
- `broll_gen/browser_visit.py` — `_TIMELINE_SCHEMA` has its own type enum for the mixed-timeline planner; must also include `"stock_video"`
- `broll_gen/image_montage.py` — Pexels image API pattern to follow: `{"Authorization": pexels_api_key}` (no `Bearer` prefix), `pexels_api_key` constructor injection, key flows from `smoke_e2e.py` via `gen_kwargs = {"pexels_api_key": os.environ.get("PEXELS_API_KEY", ""), ...}` — no change to `step_broll()` needed
- `broll_gen/headline_burst.py` — `_GRADIENTS` list and `_draw_gradient()` are the only change targets; `_render_line_frame()` receives `gradient_top, gradient_bot` from both `render_lines_clip` and `HeadlineBurstGenerator.generate`; both call sites must also be updated
- `broll_gen/browser_visit.py` — `_FIND_POSITIONS_JS` already detects `articleEl` and computes `articleTopPx`/`articleBottomPx` but returns only `article_bottom_pct`; `_capture_sections()` takes `page.screenshot(path=str(png_path))` at line 392 — `clip` keyword argument supported by Playwright

### Institutional Learnings

- **Pexels auth gotcha** (`docs/solutions/`): Use `{"Authorization": api_key}` with no `Bearer` prefix — Pexels will silently 401 otherwise
- **Ken Burns black frames** (`docs/solutions/`): `setpts=PTS-STARTPTS` must follow `zoompan` in every filter chain feeding into `xfade`; applies to both stock video clips and cropped screenshots
- **FFmpeg concat last-frame rule** (`docs/solutions/`): Always repeat last frame with `duration 0.001` in concat demuxer or the final frame is silently dropped
- **scale before crop** (`docs/solutions/`): Normalize input width with `scale=1080:-1` before cropping; cropped screenshots will have variable widths depending on article container

## Key Technical Decisions

- **`AvatarLayout.BROLL_BODY` over modifying HALF_SCREEN**: Adding a new enum value is backward-compatible, keeps `_assemble_half_screen` untouched, and makes the intent explicit in the call site. The new `_assemble_broll_body()` method reuses the three-segment logic from `_assemble_half_screen` but scales b-roll to full `OUTPUT_WIDTH × OUTPUT_HEIGHT` during the body segment and removes the `body_avatar` composite.
- **Short avatar via audio trim before upload**: The fal.ai VEED endpoint accepts no `max_duration` param. The cost-efficient approach trims the audio to `[0 → HOOK_DURATION_S] + [total - CTA_DURATION_S → total]` concatenated into a 6s clip, uploads that as the avatar audio URL, and generates a 6s avatar. In `_assemble_broll_body()`, `hook = avatar.subclipped(0, HOOK_DURATION_S)` and `cta = avatar.subclipped(HOOK_DURATION_S, HOOK_DURATION_S + CTA_DURATION_S)`. The original full-duration audio still drives the voice track.
- **`AvatarWindow` dataclass**: A lightweight `AvatarWindow(hook_end: float, cta_start: float, avatar_is_short: bool)` struct is computed once in `main()` and threaded to both `step_avatar()` and `step_assemble()`. This is the shared contract that prevents the `avatar.subclipped(57.0, 60.0)` crash identified in flow analysis (C1).
- **Flat design via `_FLAT_COLORS` list**: Replace `_GRADIENTS` (five dark gradient tuples) with `_FLAT_COLORS` (five bold solid colors cycling per line: e.g., `(255, 215, 0)` yellow, `(30, 30, 220)` deep blue, `(220, 50, 50)` coral, `(15, 160, 80)` emerald, `(240, 240, 240)` off-white with dark text). Change `_render_line_frame()`'s signature to accept `flat_color: tuple` instead of `gradient_top, gradient_bot`; update both call sites. Increase `max_size` in `_auto_font_size` call from `160` to `220`. For off-white cards, invert text and shadow colors.
- **stock_video query strategy — one query per video** (not per segment): At 3 videos/day the per-segment approach would require ~900 Pexels video API calls/month, exceeding the free tier. One query per video uses ~90/month. Query text is `job.topic["title"]` + `" technology"`. Per-segment relevance can be upgraded when the channel warrants a Pexels Pro plan.
- **`_FIND_POSITIONS_JS` extension for pixel bounding box**: Add `article_left_px`, `article_right_px`, and `article_width_px` to the return object alongside existing fields. `getBoundingClientRect()` on the already-detected `articleEl` provides these. Pass as `clip={"x": article_left_px, "y": 0, "width": article_width_px, "height": _VIEWPORT_H}` to `page.screenshot()`. The Ken Burns renderer needs no changes since `scale=1080:-1` normalizes any input width.
- **Per-segment `stock_video` fallback** within mixed timeline: `_render_all_segments()` falls back to `render_lines_clip()` (headline_burst) for any segment whose type is `stock_video` when the generator raises `BrollError`. This keeps the timeline length intact without cascading to the outer `step_broll()` retry loop.
- **Font validation at import time**: Add a module-level assertion in `headline_burst.py` that raises `ImportError` (or logs a critical warning) when all `_BOLD_CANDIDATES` fail and only the bitmap default would be loaded. This surfaces the font-path issue on Linux deploy immediately rather than silently producing 10px text.

## Open Questions

### Resolved During Planning

- **Does fal.ai accept a `max_duration` param?** No — `VeedFabricClient._submit()` posts only `{image_url, audio_url, resolution}`. Short avatar must be achieved by trimming the audio before upload.
- **Does `_FIND_POSITIONS_JS` already return pixel bounding box?** No — it returns fractional scroll positions and `article_bottom_pct`. The JS must be extended to call `getBoundingClientRect()` on `articleEl` and return `article_left_px`, `article_right_px`, `article_width_px`.
- **Do R1 and R2 share a timing contract?** Yes — the `AvatarWindow` dataclass resolves the C1 critical gap identified in flow analysis. It is computed in `main()` and threaded to `step_avatar()` and `step_assemble()`.

### Deferred to Implementation

- Confirm Pexels video API free-tier rate limit (photo and video endpoints share the key but may have separate video quotas)
- Confirm exact `video_files[]` response shape and which quality field to prefer (`hd`, `sd`, `link`) — read from a live API call in implementation
- Off-white flat color on `headline_burst`: determine whether text should always be black for those cards or follow a per-color contrast rule

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
Audio (full duration)
  │
  ├─► step_upload()         → full_audio_url        (for voice track)
  │
  ├─► _trim_avatar_audio()  → avatar_audio (6s)
  │       └─► step_upload() → short_audio_url        (for avatar gen)
  │
  ├─► step_avatar()         → avatar.mp4 (6s)
  │       [uses short_audio_url; WIP placeholder also 6s]
  │
  ├─► step_broll()          → broll.mp4 (body duration = total - 6s)
  │
  └─► step_assemble(layout=BROLL_BODY, avatar_window=AvatarWindow(...))
          │
          ├─ hook (0→3s): avatar.subclipped(0, 3)       → full 1080×1920
          ├─ body (3s→N-3s): broll scaled to 1080×1920  → full 1080×1920 (no avatar)
          └─ CTA (N-3s→N): avatar.subclipped(3, 6)      → full 1080×1920

AvatarWindow(hook_end=3.0, cta_start=total-3.0, avatar_is_short=True)
  computed once in main(), passed to step_avatar() and step_assemble()
```

## Implementation Units

- [x] **Unit 1: Flat-design `headline_burst` redesign (R3)**

**Goal:** Replace dark-gradient card backgrounds with flat bold solid colors and increase typography to ≥180px.

**Requirements:** R3

**Dependencies:** None

**Files:**
- Modify: `scripts/broll_gen/headline_burst.py`

**Approach:**
- Replace the `_GRADIENTS` list with `_FLAT_COLORS` — five bold solid RGB tuples (yellow, deep blue, coral, emerald, off-white)
- Replace `_draw_gradient(img, top, bot)` call inside `_render_line_frame` with a single solid fill (`Image.new("RGB", (_W, _H), flat_color)` or `draw.rectangle`)
- Update `_render_line_frame()` signature: `flat_color: tuple` replaces `gradient_top, gradient_bot` params
- Update both call sites: `render_lines_clip` (cycles via `_FLAT_COLORS[l_idx % len(_FLAT_COLORS)]`) and `HeadlineBurstGenerator.generate` (same)
- Increase `max_size` argument in `_auto_font_size()` call from `160` to `220`; adjust `min_size` to `80` to keep a readable floor
- For the off-white card color, set text fill to `(20, 20, 20)` dark; for all other colors keep `(255, 255, 255)` white
- Add a module-level font-path validation: if all `_BOLD_CANDIDATES` fail and `ImageFont.load_default()` would be used, log a `CRITICAL` warning with the missing paths

**Patterns to follow:**
- `broll_gen/stats_card.py` — uses a fixed solid dark background via `_draw_gradient(img)` with `_BG_TOP = (10, 10, 22)` — the flat approach is simpler than this (no per-row loop needed)
- Existing `_render_line_frame` accent bars and label logic remain unchanged

**Test scenarios:**
- Rendering 3 lines produces 3 distinct solid-color backgrounds (no gradient visible)
- Text font is ≥180px for a short line (≤4 words) that fits within `max_text_w`
- Off-white card renders with dark text (not white-on-white)
- `render_lines_clip` and `HeadlineBurstGenerator.generate` both produce valid MP4s with the new style

**Verification:**
- Running `render_lines_clip(["AI $1T valuation", "15x faster", "Zero latency"], 4.5, out, tmp)` produces an MP4 where no card has a gradient (inspect by extracting a frame with FFmpeg)
- No `load_default()` fallback warning fires on macOS dev environment

---

- [x] **Unit 2: Content-crop browser screenshots (R5)**

**Goal:** Crop each viewport screenshot to the article content column width before Ken Burns rendering, eliminating sidebar and whitespace from b-roll.

**Requirements:** R5

**Dependencies:** None

**Files:**
- Modify: `scripts/broll_gen/browser_visit.py`

**Approach:**
- Extend `_FIND_POSITIONS_JS` return value: add `article_left_px`, `article_right_px`, `article_width_px` computed via `articleEl.getBoundingClientRect()` on the already-detected `articleEl`. Fallback values when no article element is found: `article_left_px = 0`, `article_width_px = _VIEWPORT_W` (full viewport width).
- Update `_capture_sections()` to read the new fields from the JS result dict; build a `clip_rect = {"x": article_left_px, "y": 0, "width": article_width_px, "height": _VIEWPORT_H}` and pass it to every `page.screenshot()` call via the `clip=` keyword argument
- No changes to `_render_browser_clip` — FFmpeg's `scale=1080:-1` normalizes whatever input width is given
- Run the `< 200 words` body text check before the bounding box detection to guard against paywalled/blank pages (already exists — verify it fires before the JS call)

**Patterns to follow:**
- `broll_gen/browser_visit.py` — existing `_FIND_POSITIONS_JS` structure and `_capture_sections()` loop
- `page.screenshot(path=..., clip={"x", "y", "width", "height"})` — Playwright standard API

**Test scenarios:**
- Article with a known narrow content column (e.g., a VentureBeat article) produces screenshots that are narrower than 1080px in raw form and expand to full 1080 after `scale=1080:-1` in the Ken Burns step
- Page with no detected article element falls back to full viewport crop (no crash)
- Paywalled page still triggers `BrollError` before the bounding box detection is attempted

**Verification:**
- A smoke run screenshot PNG for a browser b-roll clip has width < 1080 before Ken Burns (inspect raw PNG dimensions)
- The final MP4 from `_render_browser_clip` is still 1080px wide (FFmpeg scale normalizes it)

---

- [x] **Unit 3: `stock_video` b-roll generator (R4)**

**Goal:** New generator that fetches cinematic video clips from Pexels, trims them to the target duration, and registers as a first-class b-roll type.

**Requirements:** R4

**Dependencies:** None

**Files:**
- Create: `scripts/broll_gen/stock_video.py`
- Modify: `scripts/broll_gen/factory.py`
- Modify: `scripts/broll_gen/selector.py`
- Modify: `scripts/broll_gen/browser_visit.py` (add `"stock_video"` to `_TIMELINE_SCHEMA` type enum)

**Approach:**
- `StockVideoGenerator(BrollBase)` with `__init__(self, pexels_api_key: str = "")` mirroring `ImageMontageGenerator`
- `generate(job, target_duration_s, output_path)`: build query from `job.topic["title"]` + `" technology"`; call `_fetch_video_clips(query)` → download best `hd` file per result (fall back to `sd`); trim each clip to `target_duration_s / n_clips` with FFmpeg; xfade-concatenate; raise `BrollError` if 0 results
- Pexels video endpoint: `GET https://api.pexels.com/videos/search?query=...&per_page=5&orientation=portrait`; header `{"Authorization": pexels_api_key}` — no `Bearer` prefix
- Response field: `data["videos"][i]["video_files"]` — pick the file where `file_type == "video/mp4"` and `quality` is `"hd"` (prefer) or `"sd"` (fallback); `"link"` is the download URL
- Download with `httpx.AsyncClient` streaming to temp file; re-encode to pipeline spec with `libx264 / yuv420p`
- Use `asyncio.to_thread(subprocess.run, ...)` for all FFmpeg calls (matches all other generators)
- Raise `BrollError` (not bare exceptions) for: zero results, HTTP errors, FFmpeg failure
- Register in `factory.py` with `if type_name == "stock_video": return StockVideoGenerator(pexels_api_key=kwargs.get("pexels_api_key", ""))`
- Add `"stock_video"` to `_VALID_TYPES` frozenset, both `"primary"` and `"fallback"` enum arrays in `selector.py`, and the `_SYSTEM_PROMPT` description
- Add `"stock_video"` to `_TIMELINE_SCHEMA`'s type enum in `browser_visit.py`; update `_plan_timeline()`'s system prompt to describe it as "cinematic footage for emotional or context-setting beats"
- In `_render_all_segments()` in `browser_visit.py`, add a per-segment try/except for `stock_video` segments that falls back to `render_lines_clip()` (headline_burst)

**Patterns to follow:**
- `broll_gen/image_montage.py` — Pexels photo API pattern, constructor injection, `BrollError` usage
- `broll_gen/browser_visit.py` — `_render_browser_clip()` for xfade-concatenation FFmpeg pattern
- `broll_gen/stats_card.py` — `asyncio.to_thread(subprocess.run, ...)` pattern

**Test scenarios:**
- Valid Pexels API key + query "AI technology" returns ≥1 result and produces a trimmed MP4
- Zero results raises `BrollError` (triggering fallback in `step_broll()`)
- Invalid or empty API key produces `BrollError` (not a bare `httpx` exception)
- Clip shorter than `target_duration_s` is padded via freeze-last-frame (`_fill_to_duration` pattern)

**Verification:**
- `make_broll_generator("stock_video", pexels_api_key="...")` returns a `StockVideoGenerator` without `ValueError`
- A smoke run with `BROLL_PRIMARY_TYPE=stock_video` (or similar env override) completes and produces a non-empty MP4

---

- [x] **Unit 4: Full-screen body layout + short avatar (R1, R2)**

**Goal:** Avatar appears only at hook (~3s) and CTA (~3s); body b-roll fills the entire 9:16 frame; avatar generation cost drops ~85% by trimming the audio to 6s before upload.

**Requirements:** R1, R2

**Dependencies:** None (Units 1–3 are independent; this unit touches different files)

**Files:**
- Modify: `scripts/avatar_gen/layout.py`
- Modify: `scripts/video_edit/video_editor.py`
- Modify: `scripts/smoke_e2e.py`

**Approach:**

*Step A — `AvatarWindow` dataclass:*
- Define `AvatarWindow` as a simple dataclass (or `NamedTuple`) in a new `avatar_gen/window.py` or inline in `smoke_e2e.py`: fields `hook_end: float`, `cta_start: float`. Computed in `main()` as `AvatarWindow(hook_end=VideoEditor.HOOK_DURATION_S, cta_start=max(VideoEditor.HOOK_DURATION_S, audio_duration - VideoEditor.CTA_DURATION_S))`.

*Step B — `AvatarLayout.BROLL_BODY`:*
- Add `BROLL_BODY = "broll_body"` to `avatar_gen/layout.py`

*Step C — `VideoEditor._assemble_broll_body()`:*
- New private method mirroring `_assemble_half_screen` three-segment structure but:
  - Hook (0 → `hook_end`): `avatar.subclipped(0, HOOK_DURATION_S)` → resized to `OUTPUT_WIDTH × OUTPUT_HEIGHT`, full screen
  - Body (`hook_end` → `cta_start`): b-roll resized to full `OUTPUT_WIDTH × OUTPUT_HEIGHT` (no avatar, no `body_avatar`, no `body_bg` composite — just `_fill_to_duration(broll_full, body_duration)`)
  - CTA (`cta_start` → end): `avatar.subclipped(HOOK_DURATION_S, HOOK_DURATION_S + CTA_DURATION_S)` → full screen
  - Avatar is expected to be 6s; use `min(avatar.duration, ...)` guards identically to `_assemble_half_screen`
- Add dispatch in `VideoEditor.assemble()`: `if layout == AvatarLayout.BROLL_BODY: return self._assemble_broll_body(...)`
- b-roll is loaded with `VideoFileClip(broll_path).resized((OUTPUT_WIDTH, OUTPUT_HEIGHT))` — no half-screen slot sizing

*Step D — Short audio trim in `smoke_e2e.py`:*
- Add helper `_trim_avatar_audio(audio_path, hook_s, cta_s, total_s) -> str` that uses FFmpeg to:
  1. Extract first `hook_s` seconds: `ffmpeg -ss 0 -t {hook_s} -i audio_path`
  2. Extract last `cta_s` seconds: `ffmpeg -ss {total_s - cta_s} -t {cta_s} -i audio_path`
  3. Concatenate both into a single temp `.mp3` (use FFmpeg concat demuxer with a two-entry txt file)
  4. Return the temp file path (caller is responsible for cleanup in `finally`)
- In `main()`, non-reuse path (`SMOKE_USE_VEED`): after computing `audio_duration` (lines 597-601), call `_trim_avatar_audio()` → temp `short_audio_path`; call `step_upload(short_audio_path)` → `short_audio_url`; call `step_avatar(topic, short_audio_url, audio_duration)` with the **full** `audio_duration` still flowing to `step_broll` and `step_assemble`
- Update `step_avatar()`: when computing WIP placeholder duration, use `min(audio_duration, VideoEditor.HOOK_DURATION_S + VideoEditor.CTA_DURATION_S)` (i.e., 6.0s) instead of the raw `audio_duration`
- In `main()`, both reuse and non-reuse paths: change the `step_assemble()` call to pass `layout=AvatarLayout.BROLL_BODY`
- `_assemble_broll_body()` reads `HOOK_DURATION_S` and `CTA_DURATION_S` from `VideoEditor` class constants directly — no new parameter needed for the timing values
- **Backward-compatibility for `SMOKE_REUSE_AVATAR` with old full-duration cached clips:** In `_assemble_broll_body()`, detect clip length: if `avatar.duration > HOOK_DURATION_S + CTA_DURATION_S + 5` (i.e., clearly a full-duration clip), take the CTA window from the end of the clip (`avatar.subclipped(total_duration - CTA_DURATION_S, total_duration)`) rather than fixed seconds 3-6. This means old cached clips still produce a correct CTA (speaker says CTA words) while new short clips use seconds 3-6. The `total_duration` value is already known in `_assemble_broll_body()` from `audio.duration`.

**Patterns to follow:**
- `video_edit/video_editor.py` — `_assemble_broll_only()` for full-frame b-roll resize pattern; `_assemble_half_screen()` for three-segment hook/body/CTA structure and `_fill_to_duration` usage
- `smoke_e2e.py` — `_make_wip_avatar()` for FFmpeg subprocess pattern; `step_upload()` call pattern

**Test scenarios:**
- `_assemble_broll_body()` with a 6s avatar + 60s b-roll + 66s audio produces a 66s video where frames 0–3 and 63–66 are avatar, frames 3–63 are b-roll (inspect with `ffprobe`)
- `_trim_avatar_audio()` with a 60s audio produces a 6s temp file whose content matches the first 3s + last 3s of the original
- WIP placeholder path (`SMOKE_USE_VEED` not set) generates a 6s black placeholder clip
- `AvatarLayout.BROLL_BODY` dispatches correctly to `_assemble_broll_body()` in `VideoEditor.assemble()`

**Verification:**
- A full smoke run (with WIP avatar) completes without error and the final MP4 has b-roll occupying the full frame from 3s to `total-3s` (no avatar strip visible in the middle body section)
- WIP avatar placeholder is 6s (not full audio duration)

## System-Wide Impact

- **Interaction graph:** `step_avatar()`, `step_upload()`, and `step_assemble()` in `smoke_e2e.py` have their signatures and call order modified by Unit 4. `VideoEditor.assemble()` dispatch path is extended. `BrollSelector.select()` must recognise `"stock_video"` as a valid type. `BrowserVisitGenerator._render_all_segments()` gains a per-segment fallback.
- **Error propagation:** `StockVideoGenerator.generate()` must raise `BrollError` for all failure modes (zero results, HTTP error, FFmpeg failure) so `step_broll()`'s existing try/except loop catches them and falls back to the next generator type.
- **State lifecycle risks:** `_trim_avatar_audio()` writes a temp file; it must be cleaned up after `step_upload()` succeeds. Use `tempfile.NamedTemporaryFile` or an explicit `os.unlink()` in a `finally` block.
- **API surface parity:** `SMOKE_REUSE_AVATAR=1` path bypasses `step_avatar()` entirely. After Unit 4, `step_assemble()` will be called with `layout=BROLL_BODY`; the reuse path must pass a compatible avatar (6s clip or have `_assemble_broll_body` fall back gracefully when the cached avatar is full-duration).
- **Integration coverage:** The WIP placeholder path must exercise the same `_assemble_broll_body()` code path as the real VEED path. After Unit 4, the WIP placeholder should generate a 6s clip so the CTA subclip logic is covered in every dev smoke run.

## Risks & Dependencies

- **Pexels video free-tier quota (R4):** Portrait-orientation filter (`orientation=portrait`) may reduce available results for tech queries — test in implementation and fall back to removing the orientation filter if results < 3
- **fal.ai audio upload for short clip (R2):** The 6s concatenated audio is uploaded to catbox/0x0 via `step_upload()`; verify that the upload service doesn't impose a minimum file size or content-type restriction for short MP3s
- **`SMOKE_REUSE_AVATAR=1` compatibility (R1/R2):** Resolved in Unit 4 via the `avatar.duration > HOOK_DURATION_S + CTA_DURATION_S + 5` guard in `_assemble_broll_body()`. Old full-duration clips will have their CTA taken from the clip's end; new 6s clips use the fixed 3–6s window. No layout switch needed.
- **Font on Linux deploy (R3):** Unit 1 adds a `CRITICAL` log warning but does not block execution; a deploy to Ubuntu without `fonts-dejavu` will produce small fallback text. Add DejaVu installation to the deploy checklist.

## Documentation / Operational Notes

- After this plan ships, the `SMOKE_USE_VEED=1` path is ~85% cheaper (~$0.48/video at 480p × 6s vs $4.80 for 60s)
- Monitor the assembled video at ~3s and ~(total-3s) boundaries in the first few real-VEED runs to confirm the hook/CTA avatar timing feels natural
- The `SMOKE_REUSE_AVATAR=1` workflow will produce a hybrid result (HALF_SCREEN layout with full-duration cached avatar) until the cached clip is replaced with a 6s one

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-02-001-video-quality-fullscreen-layout-requirements.md](../brainstorms/2026-04-02-001-video-quality-fullscreen-layout-requirements.md)
- Related code: `video_edit/video_editor.py:_assemble_half_screen` (lines 126-206), `avatar_gen/layout.py`, `broll_gen/headline_burst.py:_render_line_frame`, `broll_gen/browser_visit.py:_FIND_POSITIONS_JS`, `avatar_gen/veed_client.py:_submit`
- Institutional learnings: `docs/solutions/workflow-issues/intelligent-broll-type-selection-gpu-phase-gating-2026-03-29.md`
