---
title: "refactor: Replace EchoMimicV3 with HeyGen Avatar IV"
type: refactor
status: completed
date: 2026-03-29
origin: docs/brainstorms/2026-03-27-commoncreed-content-pipeline-requirements.md
supersedes: docs/plans/2026-03-27-001-feat-commoncreed-avatar-pipeline-plan.md
---

# Refactor: Replace EchoMimicV3 with HeyGen Avatar IV

## Overview

VS1 validation (completed 2026-03-28) showed EchoMimicV3 does not meet the quality bar for @commoncreed. Per the fallback path in the original plan (Unit 0 decision gate), this plan replaces the avatar generation backend with HeyGen Avatar IV — the safest, most established commercial avatar platform — while preserving the rest of the pipeline (news sourcing, scripting, voice, b-roll, video assembly, Telegram approval, social posting) unchanged.

The key structural simplification: avatar generation moves from the RunPod GPU phase (ComfyUI-dependent) to a cloud REST API call. RunPod is still needed for b-roll generation via ComfyUI, but the pod-on window shrinks.

## ⚠ Critical Findings from API Research (2026-03-29)

Two findings from HeyGen API research materially affect the implementation strategy. Both must be resolved before Unit 1 begins.

### 1. Cost at full volume is not viable at retail pricing

HeyGen Avatar IV billing is **1 credit = 1 second of output video**.

| Scenario | Credits/month | Est. retail cost |
|----------|--------------|-----------------|
| 75 videos × 45s (target) | 3,375 | ~$1,700–$3,400/month |
| 30 videos × 45s (1/day) | 1,350 | ~$675–$1,350/month |
| Pro plan includes | 100 | ~1.7 min of Avatar IV |

**None of these are viable before the channel generates revenue.** The original $140-190/month estimate was wrong — it assumed per-plan pricing, not per-second credit consumption.

**Revised strategy (two options — owner must choose before implementation):**

**Option A — Kling AI Avatar v2.6 as primary pipeline**
- Uses fal.ai API: `$0.115/sec × 45s × 75 videos ≈ $388/month`
- Quality: 8/10 (vs HeyGen 9/10) — excellent upper-body, slightly less hand expressiveness
- Reliable commercial API, Chinese provider (same geo-risk level as HeyGen's cloud)
- Endpoint: `fal.ai/models/fal-ai/kling-video/ai-avatar/v2/pro`
- **Recommended for the daily automated pipeline at target volume**

**Option B — HeyGen at reduced launch volume**
- Start with 1 video/day (30/month) while channel grows: ~$775/month
- Contact HeyGen sales for Enterprise custom rates once channel hits 20K followers
- **Recommended only if quality delta vs Kling is unacceptable after A/B test**

**Plan decision:** This plan implements a `AvatarClient` abstraction with a HeyGen backend AND a Kling backend, selectable via `AVATAR_PROVIDER` env var. This lets the owner A/B test quality vs. cost without re-architecting.

### 2. HeyGen portrait 9:16 API bug

`POST /v2/video/generate` pads portrait requests with black bars (letterboxing) — confirmed bug as of March 2026. The dedicated `/v2/video/av4/generate` endpoint is less tested but may work correctly.

**Workaround:** Generate HeyGen video at 16:9 (landscape), then crop to 9:16 (center crop) in `VideoEditor.assemble()` before the avatar is composited with b-roll. No workaround needed for Kling — its Avatar v2 Pro supports native portrait output.

**Impact on plan:** `VideoEditor` gains an optional `crop_to_portrait` parameter for the avatar input clip (used only when `AVATAR_PROVIDER=heygen`).

## Problem Frame

EchoMimicV3 failed the VS1 quality gate. The pipeline skeleton (all modules in `scripts/`) already exists per plan 001. Only the avatar generation backend needs to be swapped. HeyGen Avatar IV provides:
- Full upper-body with motion-capture-derived hand gestures (addresses the user's full-body/hand requirement)
- Hyper-realistic quality rated highest among commercial options
- Stable REST API with no GPU infrastructure overhead
- Custom Instant Avatar trained once from owner's reference video

(see origin: `docs/brainstorms/2026-03-27-commoncreed-content-pipeline-requirements.md`)

## Requirements Trace

- **R4** — AI avatar video generated from owner's reference footage. *Changed:* "using EchoMimic V3" → "using HeyGen Avatar IV via REST API". Fallback (face presence check, retry, b-roll-only flag) preserved.
- **R5** — B-roll via ComfyUI on RunPod. *Unchanged.*
- **R6** — VideoEditor assembles final video. *Unchanged.* VideoEditor takes a local `avatar_path` file — HeyGenAvatarClient downloads the video before handoff.
- **R7/R8** — Telegram approval, social posting. *Unchanged.*
- **R1-R3, R9-R11** — News sourcing, scripting, voiceover, project structure, deploy scripts. *Unchanged.*
- **VS3** — HeyGen is the "HeyGen API bridge" outcome of VS3 in the original plan.

## Scope Boundaries

- **Not in scope:** Rebuilding any module other than `avatar_gen/`. All other modules (VideoEditor, TelegramApprovalBot, NewsSourcer, SocialPoster, ComfyUIClient, VoiceGenerator, ScriptGenerator) are used unchanged.
- **Not in scope:** Replacing ElevenLabs with HeyGen TTS (voice quality from ElevenLabs is preserved; HeyGen receives audio URL).
- **Not in scope:** Migrating b-roll generation away from ComfyUI on RunPod.
- **Not in scope:** Full-body below-waist shots — HeyGen Avatar IV produces upper-body (chest up) with expressive arm/hand gestures, which is the industry standard for short-form content.
- **Not in scope:** HunyuanVideo-Avatar or other open-source alternatives (revisit if both HeyGen and Kling are unsatisfactory).
- **Not in scope:** Enterprise pricing negotiation with HeyGen (owner action, not a code task).

## Context & Research

### Relevant Code and Patterns

- `scripts/avatar_gen/echomimic_client.py` — existing `EchoMimicClient` to be replaced. Provides the interface pattern: `__init__(comfyui_client, output_dir)`, `generate(reference_video_path, audio_path, output_path, seed)`, `AvatarQualityError`. New client mirrors this interface where practical but drops `comfyui_client` dependency.
- `scripts/commoncreed_pipeline.py` — `CommonCreedPipeline._generate_assets()` instantiates and calls `EchoMimicClient`. `VideoJob` dataclass holds `avatar_path` (local file). Both need updating.
- `scripts/gpu/pod_manager.py` — `PodManager` async context manager. Avatar generation was inside the pod-on context. After this refactor, only b-roll generation remains inside it.
- `scripts/video_gen/comfyui_client.py` — `ComfyUIClient.generate_broll()` pattern shows async file download after workflow completion. `HeyGenAvatarClient._download_video()` follows the same local-file pattern.
- `scripts/posting/social_poster.py` — resolved in plan 001: Ayrshare uses multipart file upload (local path), not a public URL. No video hosting infrastructure needed for the final video.
- `comfyui_workflows/echomimic_v3_avatar.json` — superseded. Keep file in place with a comment, do not delete (audit trail).

### Institutional Learnings

- Plan 001 resolved: "Ayrshare uses multipart file upload (local path), not a public URL" — eliminates S3/R2 need for the assembled video.
- Plan 001 resolved: "Telegram `sendVideo()` hosts inline" — TelegramApprovalBot sends local file, no hosting required.
- Audio hosting for HeyGen is the one NEW hosting requirement: ElevenLabs audio must be at a publicly accessible URL for HeyGen's `voice.audio_url` parameter. Approach: upload to Ayrshare `/media/upload` before HeyGen call, or use a short-lived S3 pre-signed URL. Ayrshare upload is preferred (no new infrastructure).

### External References

- HeyGen API v2 docs: `https://docs.heygen.com/reference/create-an-avatar-video-v2`
- HeyGen Instant Avatar creation API: `https://docs.heygen.com/reference/create-an-instant-avatar`
- HeyGen video status polling: `GET https://api.heygen.com/v1/video_status.get?video_id={id}`
- HeyGen video generation (with custom audio): POST body includes `voice: {type: "audio", audio_url: "..."}` for ElevenLabs audio passthrough.
- Ayrshare media upload: `POST https://api.ayrshare.com/api/media/upload` (returns `url` field).

## Key Technical Decisions

- **Dual-provider abstraction (`AVATAR_PROVIDER` env var):** Rather than implementing only HeyGen, this plan builds a thin `AvatarClient` interface with two backends: `HeyGenAvatarClient` and `KlingAvatarClient`. `AVATAR_PROVIDER=heygen` or `AVATAR_PROVIDER=kling` selects at runtime. This resolves the cost/quality tradeoff without re-architecting when the owner decides which to use long-term. The interface is identical: `generate(audio_url, output_path) → str`.

- **ElevenLabs audio passthrough (both providers):** Both HeyGen (`voice.type: "audio", voice.audio_url`) and Kling Avatar v2 Pro (photo + audio URL) support supplying pre-generated audio for lip-sync. *Decision: keep ElevenLabs as the voice source.* Reasons: existing `VoiceGenerator` already produces the owner's cloned voice; avoids duplicating voice clone setup in two systems.

- **Audio hosting mechanism:** ElevenLabs `.mp3` must be at a public URL for both HeyGen and Kling. *Decision: upload to Ayrshare `/media/upload` endpoint* before the avatar call. Rationale: Ayrshare is already a dependency; no new services needed. URLs expire after 24h — well within the pipeline window.

- **Phase restructuring:** Avatar generation no longer needs RunPod (both HeyGen and Kling are cloud APIs):
  - Phase 1 (CPU + cloud APIs, pod OFF): news → script → ElevenLabs voice → audio upload → avatar generation → download avatar MP4
  - Phase 2 (RunPod GPU, pod ON): b-roll generation via ComfyUI
  - Phase 3 (CPU, pod OFF): silence trim → VideoEditor assemble → Telegram approval → SocialPoster post
  - RunPod pod-on time: ~25 min → ~10 min (b-roll only). GPU cost: ~$0.86/day → ~$0.35/day.

- **HeyGen portrait workaround:** Generate at 16:9, crop to 9:16 via FFmpeg center crop in `VideoEditor.assemble()` when `AVATAR_PROVIDER=heygen`. Kling native portrait (`aspect_ratio: "9:16"`) needs no crop. `VideoEditor` gains optional `input_aspect: Literal["16:9", "9:16"]` parameter for the avatar clip.

- **HeyGen generation queue:** Standard queue can take 24-36 hours (unacceptable for a daily pipeline). *Decision: require Pro API plan or higher* for priority queue access (5-15 min generation time). This is the minimum viable plan tier for automated use. Add a 20-minute timeout before `AvatarQualityError` is raised.

- **Drop `reference_video_path` from runtime config:** Owner's reference video used once during one-time avatar setup (HeyGen Instant Avatar training or Kling avatar photo upload). Runtime config only needs `HEYGEN_AVATAR_ID` or `KLING_AVATAR_PHOTO_URL`. `reference_video_path` stays in `.env.example` marked as setup-only.

- **Quality check:** File size > 0 and duration ≥ expected × 0.9. OpenCV face detection omitted — both providers guarantee identity preservation by design.

## Open Questions

### Resolved During Planning

- **Audio hosting for HeyGen:** Ayrshare `/media/upload`. No new infrastructure. (see Key Technical Decisions)
- **Phase structure after removing EchoMimic from GPU phase:** Three-phase restructure. Pod-on only for b-roll. (see Key Technical Decisions)
- **HeyGen video format compatibility with VideoEditor:** HeyGen Avatar IV outputs MP4/H.264 at configurable aspect ratio. Request `aspect_ratio: "9:16"` to get vertical output. VideoEditor accepts any MP4 input and re-encodes to 1080x1920 via FFmpeg. Compatible.
- **Does HeyGen Avatar IV support 9:16 vertical output?** Yes — `aspect_ratio` parameter in the video generation API supports `"9:16"`.

### Deferred to Implementation

- **Exact HeyGen polling interval and timeout:** Generation time for a 45s video varies (typically 2-5 min). Implementation should use 10s polling with a 10-minute timeout before raising `AvatarQualityError`.
- **Ayrshare audio upload expiry:** Confirm Ayrshare media URLs remain valid for at least 15 minutes (the expected HeyGen generation window). If not, use httpx to serve a temp file or switch to S3 pre-signed URL.
- **HeyGen rate limits:** Free tier is limited; Pro plan supports concurrent generations. Confirm whether 3 sequential generations within the daily run window hits any limits.
- **Video duration mismatch tolerance:** HeyGen may trim trailing silence. The 0.9× duration check is a starting heuristic; adjust if false positives occur.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
CommonCreedPipeline.run_daily()
  │
  ├── Phase 1 (CPU / cloud APIs — pod OFF)
  │   for each topic:
  │     ScriptGenerator.generate_short_form(topic)
  │     VoiceGenerator.generate(script_text) → audio.mp3
  │     SocialPoster.upload_media(audio.mp3) → audio_url   ← NEW
  │     HeyGenAvatarClient.generate(audio_url) → avatar.mp4  ← NEW
  │
  ├── Phase 2 (RunPod pod ON — b-roll only)
  │   async with PodManager(config) as comfyui_url:
  │     for each topic:
  │       ComfyUIClient.generate_broll(...) → broll.mp4
  │
  └── Phase 3 (CPU — pod OFF)
      for each topic:
        VideoEditor.trim_silence(audio.mp3) → trimmed.mp3
        VideoEditor.assemble(avatar.mp4, broll.mp4, trimmed.mp3) → final.mp4
        TelegramApprovalBot.request_approval(final.mp4) → "approve"/"reject"
        SocialPoster.post_all_short_form(final.mp4, ...)
```

```
HeyGenAvatarClient.generate(audio_url, output_path):
  POST /v2/video/generate
    avatar_id: HEYGEN_AVATAR_ID
    voice: {type: "audio", audio_url: audio_url}
    aspect_ratio: "9:16"
  → video_id

  poll GET /v1/video_status.get?video_id=...
    until status == "completed" or timeout
  → video_url

  download video_url → output_path
  validate output file (size, duration check)
```

## Implementation Units

- [ ] **Unit 1: AvatarClient abstraction + HeyGen and Kling backends**

**Goal:** Replace `EchoMimicClient` with a provider-agnostic `AvatarClient` interface and two concrete backends — `HeyGenAvatarClient` and `KlingAvatarClient` — selectable via `AVATAR_PROVIDER` env var.

**Requirements:** R4

**Dependencies:** None (standalone module)

**Files:**
- Create: `scripts/avatar_gen/base.py` — `AvatarClient` abstract base class and `AvatarQualityError`
- Create: `scripts/avatar_gen/heygen_client.py` — HeyGen Avatar IV backend
- Create: `scripts/avatar_gen/kling_client.py` — Kling AI Avatar v2 Pro backend (via fal.ai)
- Create: `scripts/avatar_gen/factory.py` — `make_avatar_client(config) → AvatarClient` factory
- Modify: `scripts/avatar_gen/__init__.py` — export `make_avatar_client`, `AvatarQualityError`
- Test: `scripts/avatar_gen/test_avatar_clients.py`

**Approach:**
- `AvatarClient` abstract base: `generate(audio_url: str, output_path: str) -> str`
- `HeyGenAvatarClient.__init__(api_key, avatar_id, output_dir)`:
  - POST `/v2/video/av4/generate` first (dedicated Avatar IV endpoint); fall back to `/v2/video/generate` with `use_avatar_iv_model: true` if av4 returns 404
  - Voice: `{"type": "audio", "audio_url": audio_url}`
  - Dimension: `{"width": 1920, "height": 1080}` (landscape, then FFmpeg crop to 9:16 in VideoEditor)
  - Poll `/v1/video_status.get?video_id=...` every 10s, 20-minute timeout
  - Download `video_url` from completed response to `output_path`
- `KlingAvatarClient.__init__(fal_api_key, avatar_image_url, output_dir)`:
  - POST to `fal.ai/models/fal-ai/kling-video/ai-avatar/v2/pro`
  - Params: `image_url` (avatar photo URL), `audio_url`, `aspect_ratio: "9:16"`
  - Poll fal.ai status endpoint; 15-minute timeout
  - Download result to `output_path`
- `make_avatar_client(config)`: reads `AVATAR_PROVIDER` from config, returns appropriate backend
- Auth: HeyGen uses `X-Api-Key` header; Kling via fal.ai uses `Authorization: Key {fal_key}`
- Use `httpx` (already in requirements) for both — async, consistent with codebase

**Patterns to follow:**
- `scripts/gpu/pod_manager.py` — async polling with `time.monotonic()` deadline
- `scripts/video_gen/comfyui_client.py` — async file download pattern
- `scripts/avatar_gen/echomimic_client.py` — `AvatarQualityError` semantics to preserve

**Test scenarios:**
- HeyGen happy path: mock returns `completed` after 2 polls; file downloaded
- HeyGen error status: `AvatarQualityError` raised
- HeyGen 20-min timeout exceeded: `AvatarQualityError` with descriptive message
- Kling happy path: mock fal.ai returns completed; native 9:16 file downloaded
- Both: file size 0 → `AvatarQualityError`
- `make_avatar_client` with `AVATAR_PROVIDER=heygen` → `HeyGenAvatarClient`
- `make_avatar_client` with `AVATAR_PROVIDER=kling` → `KlingAvatarClient`

**Verification:**
- All unit tests pass with mocked HTTP
- `generate()` returns valid local MP4 path in both mock scenarios
- Factory correctly routes to both backends

---

- [ ] **Unit 2: Audio upload helper on SocialPoster**

**Goal:** Upload ElevenLabs audio to Ayrshare `/media/upload` and return a public URL for HeyGen's `audio_url` parameter.

**Requirements:** R4 (enables ElevenLabs passthrough to HeyGen)

**Dependencies:** Unit 1 (HeyGenAvatarClient needs this URL)

**Files:**
- Modify: `scripts/posting/social_poster.py` — add `upload_media(file_path)` → str method
- Test: extend existing SocialPoster tests

**Approach:**
- `upload_media(file_path)` — POST multipart to `https://api.ayrshare.com/api/media/upload` with `Authorization: Bearer {api_key}` header
- Returns the `url` field from the JSON response
- Works for both audio (MP3) and video (MP4) files — reusable for future needs
- Raise `RuntimeError` if upload fails (non-200 response)

**Patterns to follow:**
- `SocialPoster._make_request()` — existing retry/rate-limit wrapper; reuse for this call
- `SocialPoster.post_instagram_reel()` — shows multipart upload pattern to Ayrshare

**Test scenarios:**
- Successful upload returns URL string
- Non-200 response raises `RuntimeError` with response body in message

**Verification:**
- `upload_media()` returns a string URL when called with a test MP3 file against Ayrshare sandbox

---

- [ ] **Unit 3: Restructure CommonCreedPipeline phases**

**Goal:** Replace EchoMimicClient with HeyGenAvatarClient; move avatar generation out of RunPod GPU phase; restructure into three phases (CPU/cloud → GPU → CPU).

**Requirements:** R4, R5

**Dependencies:** Unit 1, Unit 2

**Files:**
- Modify: `scripts/commoncreed_pipeline.py`
- Test: `scripts/test_commoncreed_pipeline.py` (update existing integration tests)

**Approach:**
- Remove `EchoMimicClient` import and instantiation; add `HeyGenAvatarClient`
- `_generate_assets(topic)` flow:
  1. `ScriptGenerator.generate_short_form()`
  2. `VoiceGenerator.generate()` → local audio file
  3. `SocialPoster.upload_media(audio_path)` → `audio_url`
  4. `HeyGenAvatarClient.generate(audio_url, output_path)` → local avatar MP4
  - Steps 1-4 happen BEFORE `PodManager` context (pod is OFF)
- `_phase1_with_pod()` now only wraps b-roll generation (ComfyUIClient calls)
- `_generate_assets()` returns a partially-filled `VideoJob`; b-roll path filled in Phase 2
- Remove `reference_video_path` from runtime config reads (no longer needed per run)
- Update `VideoJob` dataclass: remove `avatar_backup_path` field (HeyGen retry uses new API call, not a pre-generated backup). Add `audio_url: str` field for the Ayrshare-hosted audio URL.
- Update `config` dict: add `heygen_api_key`, `heygen_avatar_id` keys (from env vars).

**Patterns to follow:**
- Existing three-phase structure in `commoncreed_pipeline.py`
- `PodManager` context manager usage — keep identical, just with reduced scope

**Test scenarios:**
- Avatar generation fails (HeyGen error): `AvatarQualityError` caught, retry with new seed, then b-roll-only fallback
- Pod fails to start: exception propagates, Telegram alert sent, no partial posting
- All 3 topics succeed: all `VideoJob` objects have `avatar_path` and `broll_path` set before Phase 3

**Verification:**
- `run_daily()` completes end-to-end with mocked HeyGen and ComfyUI responses
- Pod is started only once (for b-roll phase) and stopped after, verified by mock call counts

---

- [ ] **Unit 4: One-time avatar setup script**

**Goal:** CLI tool to upload owner's reference video to HeyGen, create Instant Avatar, and print the `HEYGEN_AVATAR_ID` to add to `.env`.

**Requirements:** R4 (prerequisite to running the pipeline)

**Dependencies:** None (standalone)

**Files:**
- Create: `scripts/avatar_gen/setup_heygen_avatar.py`

**Approach:**
- Click CLI: `python setup_heygen_avatar.py --video /path/to/reference.mp4 --name "CommonCreed Avatar"`
- POST to HeyGen Instant Avatar creation endpoint with multipart video upload
- Poll avatar training status until `completed`
- Print: `HEYGEN_AVATAR_ID=<id>` — copy this to `.env`
- Separate from the main pipeline (run once by owner, not automated)

**Patterns to follow:**
- `scripts/pipeline.py` — Click CLI pattern with `@click.command` and `@click.option`
- Polling pattern from `HeyGenAvatarClient`

**Test scenarios:**
- Video file not found: clear error message before any API call
- Avatar creation fails (HeyGen error): print error body and exit non-zero

**Verification:**
- Running the script against HeyGen API with owner's reference video prints a valid `HEYGEN_AVATAR_ID`

---

- [ ] **Unit 5: Configuration and environment updates**

**Goal:** Add HeyGen config to `.env.example`, `config/settings.py`, and update `requirements.txt` if needed.

**Requirements:** R9 (pipeline fits existing project structure)

**Dependencies:** None

**Files:**
- Modify: `.env.example`
- Modify: `config/settings.py`
- Modify: `requirements.txt` (only if new package needed)

**Approach:**
- `.env.example`: Add section `# ─── Avatar Provider ─────────────────────────────────────` with:
  - `AVATAR_PROVIDER=kling` (or `heygen` — default to kling for cost)
  - `HEYGEN_API_KEY=your-heygen-api-key`
  - `HEYGEN_AVATAR_ID=your-avatar-id` (from setup script)
  - `FAL_API_KEY=your-fal-api-key` (for Kling via fal.ai)
  - `KLING_AVATAR_IMAGE_URL=https://...` (public URL to owner's portrait photo for Kling)
  - Comment `REFERENCE_VIDEO_PATH` as "HeyGen setup-only, not used at runtime"
- `config/settings.py`: Add avatar provider section reading all new env vars
- `requirements.txt`: No new packages — `httpx` handles both APIs. Add comment noting fal.ai and HeyGen use httpx.
- `comfyui_workflows/echomimic_v3_avatar.json`: Add `"_comment"` key: `"superseded by HeyGen/Kling avatar client (2026-03-29) — kept for reference"`

**Verification:**
- `config/settings.py` loads without error with updated `.env`
- All new env vars documented in `.env.example`

---

## System-Wide Impact

- **Interaction graph:** `CommonCreedPipeline._generate_assets()` is the only call site for `EchoMimicClient`. `PodManager` context manager scope shrinks. No other modules are affected.
- **Error propagation:** `AvatarQualityError` propagation path unchanged — caught in `_finalize_job()`, triggers retry → b-roll-only fallback → Telegram alert. Same behavior, different raise point (HeyGen HTTP error vs. OpenCV face check).
- **State lifecycle risks:** Audio files uploaded to Ayrshare are ephemeral. If HeyGen poll times out and audio URL expires, the retry will fail. Mitigation: 10-minute poll timeout is well within Ayrshare's URL validity window.
- **API surface parity:** No external interfaces change. `HeyGenAvatarClient` is internal to the pipeline.
- **Integration coverage:** End-to-end test should mock both Ayrshare media upload (Unit 2) and HeyGen API (Unit 1) to prove the three-phase flow connects correctly.

## Risks & Dependencies

- **HeyGen retail cost at volume (HIGH):** 1 credit = 1 second. 75 videos/month × 45s = 3,375 credits → ~$1,700–$3,400/month. Mitigation: start with `AVATAR_PROVIDER=kling` (~$388/month) as the default pipeline; switch to HeyGen only after channel revenue justifies it OR after Enterprise rate negotiation.

- **HeyGen portrait API bug (MEDIUM):** `/v2/video/generate` letterboxes portrait output. Confirmed as of March 2026. Mitigation: generate at 16:9, FFmpeg center crop in `VideoEditor`. If `/v2/video/av4/generate` (dedicated Avatar IV endpoint) handles portrait correctly in testing, switch to that and remove the crop step.

- **HeyGen generation queue time (HIGH):** Standard queue = 24-36 hours. Unacceptable for daily pipeline. Mitigation: require Pro plan or higher for priority queue (5-15 min). Document this as a hard prerequisite.

- **Ayrshare audio URL validity:** If provider takes longer than expected, the audio URL may expire. Mitigation: 15-minute URL lifetime confirmed sufficient for Kling; HeyGen 20-minute timeout is the risk edge — upload audio immediately before avatar call, not earlier.

- **Kling AI geo-risk (LOW):** Kuaishou (Chinese company) could face the same policy-change risk as ByteDance tools. Mitigation: `AvatarClient` abstraction means switching providers requires only a config change, not a code rewrite.

- **Instagram Reels API advanced access:** Still a blocking dependency per plan 001 — apply immediately in parallel with implementation. Not changed by this plan.

- **fal.ai as Kling intermediary:** fal.ai is a third-party API host for Kling, adding a dependency layer. Mitigation: Kling's own API (`klingai.com/global/dev`) can be used directly if fal.ai has availability issues; the `KlingAvatarClient` endpoint is a single constant to swap.

## Documentation / Operational Notes

- Run `scripts/avatar_gen/setup_heygen_avatar.py` once before first pipeline run to obtain `HEYGEN_AVATAR_ID`.
- Monitor HeyGen dashboard for credit consumption after first week.
- If monthly HeyGen cost exceeds $400, revisit HunyuanVideo-Avatar (open-source, ~$50/month self-hosted) as Phase 2 upgrade path.
- `comfyui_workflows/echomimic_v3_avatar.json` and `deploy/runpod/setup_echomimic.sh` are kept in-repo as reference but are no longer part of the active pipeline.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-03-27-commoncreed-content-pipeline-requirements.md](docs/brainstorms/2026-03-27-commoncreed-content-pipeline-requirements.md)
- **Superseded plan:** [docs/plans/2026-03-27-001-feat-commoncreed-avatar-pipeline-plan.md](docs/plans/2026-03-27-001-feat-commoncreed-avatar-pipeline-plan.md)
- Existing avatar client: `scripts/avatar_gen/echomimic_client.py`
- Existing pipeline orchestrator: `scripts/commoncreed_pipeline.py`
- HeyGen API v2 reference: `https://docs.heygen.com/reference/create-an-avatar-video-v2`
- HeyGen Instant Avatar API: `https://docs.heygen.com/reference/create-an-instant-avatar`
- Technology research: March 2026 landscape analysis (conversation context, 2026-03-29)
