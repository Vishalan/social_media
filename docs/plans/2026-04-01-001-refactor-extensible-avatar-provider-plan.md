---
title: "refactor: Extensible avatar provider layer with VEED Fabric 1.0 as primary backend"
type: refactor
status: active
date: 2026-04-01
---

# refactor: Extensible avatar provider layer with VEED Fabric 1.0 as primary backend

## Overview

Replace Kling v2 Pro with VEED Fabric 1.0 as the primary avatar generation backend, and formalise the multi-provider contract so future providers (LTX-2.3, Kling, HeyGen) can be added or swapped via config without touching pipeline logic. Introduce an explicit `AvatarLayout` enum on `VideoJob` to replace the current implicit boolean flags, and teach `VideoEditor` to dispatch on four named layout modes: `full_screen`, `half_screen`, `stitched`, and `skipped`.

## Problem Frame

The pipeline currently has one live avatar backend (Kling v2 Pro at $0.115/s) and a second mostly-unused one (HeyGen). VEED Fabric 1.0 is ~30% cheaper ($0.08/s at 480p) and takes the same inputs (image URL + audio URL) over the same fal.ai async queue.

Beyond cost, the content format is evolving: videos will mix full-screen avatar, half-screen avatar-beside-b-roll, and pure b-roll segments. Avatar clips may need to span multiple API calls when a provider has a duration cap (LTX-2.3 caps at 20s). All of this must be expressible in the pipeline without hardcoding layout decisions per provider.

## Requirements Trace

- R1. VEED Fabric 1.0 (`veed/fabric-1.0` on fal.ai) replaces Kling v2 Pro as the default avatar provider
- R2. Adding a new provider requires only a new file in `avatar_gen/` + one line in `factory.py`
- R3. Four named layout modes are supported and explicitly tracked on `VideoJob`: `full_screen`, `half_screen`, `stitched`, `skipped`
- R4. Stitching (for providers with per-call duration caps) is handled in the pipeline as a pre-assembly step, keeping individual provider clients simple
- R5. `needs_portrait_crop` is a property on the client, not a config string comparison in the pipeline
- R6. Smoke test covers VEED Fabric end-to-end

## Scope Boundaries

- HeyGen client is **not** modified (still present, still works)
- LTX-2.3 is **not** implemented now — stitching infrastructure is added, but the LTX client itself is a future unit
- `VideoEditor` gets a `layout` parameter but the four layout renderers don't need to be pixel-perfect yet — `half_screen` behaviour should match current output exactly, others can be functional stubs
- `smoke_kling.py` is updated to support VEED but the Kling path is kept for reference

## Context & Research

### Relevant Code and Patterns

- `scripts/avatar_gen/base.py` — `AvatarClient(ABC)` with single `generate(audio_url, output_path) -> str` method; `AvatarQualityError`
- `scripts/avatar_gen/kling_client.py` — reference implementation: `_FAL_SUBMIT_URL`, `_submit()`, `_poll_until_complete()`, `_download()`, `_validate()`; `KlingAvatarClient` constructor takes `(fal_api_key, avatar_image_url, output_dir)`
- `scripts/avatar_gen/factory.py` — `make_avatar_client(config: dict) -> AvatarClient`; dispatches on `config["avatar_provider"]`
- `scripts/avatar_gen/__init__.py` — exports `AvatarClient`, `AvatarQualityError`, `KlingAvatarClient`, `HeyGenAvatarClient`
- `scripts/broll_gen/base.py` — mirror of the avatar ABC pattern; shows how `BrollBase` + factory + `__init__` exports are structured
- `scripts/commoncreed_pipeline.py:79` — `VideoJob` dataclass; `_assemble()` (line ~471); `_generate_script_voice_avatar()` (line ~501)
- `scripts/video_edit/video_editor.py:32` — `VideoEditor.assemble(avatar_path, broll_path, audio_path, caption_segments, output_path, crop_to_portrait=False)`

### Institutional Learnings

- The `AvatarClient` ABC was built expressly to allow provider swaps via `AVATAR_PROVIDER` env var — this refactor is exactly the intended use (see `docs/plans/2026-03-29-002-refactor-heygen-avatar-integration-plan.md`)
- Phase 2 skip-guard pattern: always check `if job.broll_path: continue` in GPU phase loops to prevent overwriting successful Phase 1 results (see `docs/solutions/workflow-issues/intelligent-broll-type-selection-gpu-phase-gating-2026-03-29.md`)
- Log the winning provider name on every job for cost attribution
- fal.ai auth is `Authorization: Key {fal_key}` — not Bearer

## Key Technical Decisions

- **VEED Fabric client reuses KlingAvatarClient's structure verbatim**: Same fal.ai queue pattern (submit → poll → download → validate). Only the submit URL (`https://queue.fal.run/veed/fabric-1.0`) and result payload shape change. This minimises new code and review surface.

- **`AvatarLayout` enum on `VideoJob`, not a separate DTO**: Layout is a property of the job's content intent, not just assembly. Putting it on `VideoJob` lets Phase 1 (avatar generation) and Phase 3 (assembly) both read the same field without passing extra arguments.

- **Stitching lives in the pipeline as a pre-assembly step, not inside individual clients**: Clients stay simple — they generate one clip per call. The pipeline splices audio, generates n clips, and concatenates before handing `avatar_path` to `VideoEditor`. This mirrors how silence trimming works. Clients signal their duration cap via a `max_duration_s: float | None` property (None = no cap).

- **`needs_portrait_crop` becomes a property on `AvatarClient` subclasses**: Removes the `config["avatar_provider"] == "heygen"` string comparison from `_assemble()`. Each client declares its own crop requirement. VEED Fabric outputs 9:16 natively at 480p → `needs_portrait_crop = False`.

- **`VideoEditor.assemble()` gains a `layout: AvatarLayout` parameter**: The existing `crop_to_portrait` parameter stays for now (populated from `client.needs_portrait_crop` by the pipeline). The four layout modes are dispatched inside `assemble()` — `half_screen` must match current output exactly; others can be functional stubs until the content formats are finalised.

- **Default provider becomes `"veed"` in config and `.env.example`**: `AVATAR_PROVIDER=veed`. Kling remains available via `AVATAR_PROVIDER=kling`.

## Open Questions

### Resolved During Planning

- **Does VEED Fabric return the same fal.ai response shape as Kling?** Deferred to implementation — test against live endpoint. The result extraction path (`data["video"]["url"]`) may differ; wrap in a `_extract_video_url(data)` helper so only one method changes if the shape is different.
- **Does VEED Fabric's 480p output need `crop_to_portrait=True`?** No — VEED takes an image + audio and produces a lip-synced clip in the same aspect ratio as the input image. We provide a 9:16 portrait image, so output is 9:16. `needs_portrait_crop = False`.

### Deferred to Implementation

- **Exact VEED Fabric response JSON shape**: Inspect the first live response and adjust `_extract_video_url()` accordingly.
- **Whether VEED 480p output needs upscaling before `VideoEditor` compositing**: `VideoEditor` composites at 1080×1920. MoviePy's `.resized()` will scale up — check if quality is acceptable; if not, add a simple `lanczos` resize in `VeedFabricClient._post_process()`.
- **Whether `stitched` layout mode should stitch inside the client or via a pipeline helper**: Decided as pipeline helper for now; revisit if an LTX client would be cleaner with internal stitching.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
AvatarClient (ABC)
  ├── generate(audio_url, output_path) -> str        ← unchanged
  ├── needs_portrait_crop: bool                      ← NEW property
  └── max_duration_s: float | None                   ← NEW property (None = no cap)

Concrete clients
  ├── KlingAvatarClient     needs_portrait_crop=False  max_duration_s=None
  ├── HeyGenAvatarClient    needs_portrait_crop=True   max_duration_s=None
  └── VeedFabricClient      needs_portrait_crop=False  max_duration_s=None

factory.make_avatar_client(config)
  dispatches on config["avatar_provider"]:
    "kling"  → KlingAvatarClient
    "heygen" → HeyGenAvatarClient
    "veed"   → VeedFabricClient       ← NEW
    "ltx"    → LTXAvatarClient        ← stub slot, not yet implemented

VideoJob (dataclass)
  + avatar_layout: AvatarLayout = AvatarLayout.HALF_SCREEN   ← NEW
  + broll_only: bool  (keep as derived alias)

AvatarLayout (str enum)
  FULL_SCREEN  — avatar takes the whole frame (hook/CTA already do this within half_screen)
  HALF_SCREEN  — avatar bottom half, b-roll top half  ← current default
  STITCHED     — pipeline stitches n clips before assembly (for duration-capped providers)
  SKIPPED      — no avatar generated; b-roll fills full screen

Pipeline _assemble() dispatch
  SKIPPED     → VideoEditor.assemble(layout=SKIPPED)  # b-roll fills frame
  HALF_SCREEN → VideoEditor.assemble(layout=HALF_SCREEN, crop=client.needs_portrait_crop)
  FULL_SCREEN → VideoEditor.assemble(layout=FULL_SCREEN)
  STITCHED    → stitch_avatar_clips(job) → VideoEditor.assemble(layout=HALF_SCREEN, ...)
```

## Implementation Units

- [ ] **Unit 1: `VeedFabricClient` class**

  **Goal:** A working fal.ai-backed avatar client for VEED Fabric 1.0, producing a lip-synced 9:16 MP4 from image + audio URL.

  **Requirements:** R1, R2

  **Dependencies:** None — `AvatarClient` ABC already exists

  **Files:**
  - Create: `scripts/avatar_gen/veed_client.py`
  - Modify: `scripts/avatar_gen/__init__.py` (add export)
  - Test: `scripts/avatar_gen/test_veed_client.py`

  **Approach:**
  - Copy `KlingAvatarClient` structure exactly; change `_FAL_SUBMIT_URL` to `https://queue.fal.run/veed/fabric-1.0`
  - Constructor: `(fal_api_key, avatar_image_url, resolution="480p", output_dir="output/avatar")`; `resolution` maps to `"480p"` or `"720p"` in the submit payload
  - Add `_extract_video_url(data: dict) -> str` helper (also add to `KlingAvatarClient` for consistency) to isolate payload shape differences
  - Properties: `needs_portrait_crop = False`, `max_duration_s = None`
  - On first live run, inspect raw `data` before extraction and adjust if VEED's shape differs from Kling's `{"video": {"url": "..."}}`

  **Patterns to follow:**
  - `scripts/avatar_gen/kling_client.py` — verbatim structure
  - `scripts/broll_gen/base.py` — how abstract base + concrete client + `__all__` exports are organised

  **Test scenarios:**
  - Submit payload contains `image_url`, `audio_url`, and `resolution` key
  - `_extract_video_url` returns correct URL from both Kling-shaped and VEED-shaped responses
  - `AvatarQualityError` raised when `_validate` receives a zero-byte file
  - `needs_portrait_crop` is `False`
  - `max_duration_s` is `None`

  **Verification:**
  - `VeedFabricClient` instantiates without error
  - Unit tests pass; `isinstance(client, AvatarClient)` is `True`
  - Smoke test (Unit 5) runs against the live endpoint

---

- [ ] **Unit 2: `AvatarClient` base property contract + factory update**

  **Goal:** Add `needs_portrait_crop` and `max_duration_s` as abstract properties to `AvatarClient`; register `"veed"` in the factory; update `.env.example` default.

  **Requirements:** R2, R5

  **Dependencies:** Unit 1

  **Files:**
  - Modify: `scripts/avatar_gen/base.py`
  - Modify: `scripts/avatar_gen/factory.py`
  - Modify: `scripts/avatar_gen/kling_client.py` (add property implementations)
  - Modify: `scripts/avatar_gen/heygen_client.py` (add property implementations)
  - Modify: `.env.example` (`AVATAR_PROVIDER=veed`)

  **Approach:**
  - Add `@property @abstractmethod needs_portrait_crop(self) -> bool` and `@property @abstractmethod max_duration_s(self) -> float | None` to `AvatarClient`
  - `KlingAvatarClient`: `needs_portrait_crop = False`, `max_duration_s = None`
  - `HeyGenAvatarClient`: `needs_portrait_crop = True`, `max_duration_s = None`
  - `factory.py`: add `elif provider == "veed": return VeedFabricClient(...)` branch; add `elif provider == "ltx": raise NotImplementedError(...)` slot comment
  - Update `factory.py` docstring to list all valid provider strings

  **Patterns to follow:**
  - Existing `make_avatar_client()` dispatch in `factory.py`

  **Test scenarios:**
  - `make_avatar_client({"avatar_provider": "veed", ...})` returns `VeedFabricClient`
  - `make_avatar_client({"avatar_provider": "unknown", ...})` raises `ValueError`
  - All three concrete clients satisfy the ABC (no `TypeError` on instantiation)

  **Verification:**
  - `make_avatar_client` returns correct type for all registered providers
  - All existing avatar tests still pass

---

- [ ] **Unit 3: `AvatarLayout` enum + `VideoJob` update + pipeline `_assemble()` dispatch**

  **Goal:** Replace implicit `broll_only` boolean with an explicit `AvatarLayout` enum on `VideoJob`; update `_assemble()` and `_generate_script_voice_avatar()` to set and consume it.

  **Requirements:** R3, R4, R5

  **Dependencies:** Unit 2

  **Files:**
  - Modify: `scripts/commoncreed_pipeline.py`

  **Approach:**
  - Define `AvatarLayout(str, Enum)` with four values at the top of `commoncreed_pipeline.py` (or in a new `scripts/avatar_gen/layout.py` if it needs to be imported by `video_editor.py`)
  - Add `avatar_layout: AvatarLayout = AvatarLayout.HALF_SCREEN` field to `VideoJob`; keep `broll_only` as a computed alias (`@property`) that returns `self.avatar_layout == AvatarLayout.SKIPPED` to avoid breaking any existing guard checks
  - `_generate_script_voice_avatar()`: on `AvatarQualityError`, set `job.avatar_layout = AvatarLayout.SKIPPED` (instead of `job.broll_only = True`)
  - `_assemble()`: dispatch on `job.avatar_layout`:
    - `SKIPPED` → call `video_editor.assemble()` with broll as both avatar and broll (current fallback behaviour)
    - `HALF_SCREEN` → current normal path; populate `crop_to_portrait` from `self.avatar_client.needs_portrait_crop`
    - `FULL_SCREEN` → call `video_editor.assemble(layout=FULL_SCREEN)`
    - `STITCHED` → call `stitch_avatar_clips(job, self.avatar_client)` first, then assemble as `HALF_SCREEN`
  - Remove the `config["avatar_provider"] == "heygen"` string comparison from `_assemble()`

  **Patterns to follow:**
  - `broll_gen`'s `BrollType` / `needs_gpu_broll` flag pattern — same shape
  - Existing `_assemble()` logic for the `SKIPPED` and `HALF_SCREEN` branches (preserve current behaviour exactly)

  **Test scenarios:**
  - `AvatarLayout.SKIPPED` → assembler receives broll in both slots
  - `AvatarLayout.HALF_SCREEN` → assembler receives avatar + broll separately, `crop_to_portrait` from client property
  - `AvatarQualityError` during generation → `job.avatar_layout == AvatarLayout.SKIPPED`
  - `job.broll_only` still returns `True` when `avatar_layout == SKIPPED` (backwards compat)

  **Verification:**
  - Pipeline assembles a video in both `HALF_SCREEN` and `SKIPPED` layout without error
  - No `AttributeError` when `broll_only` is accessed on existing code paths

---

- [ ] **Unit 4: `VideoEditor.assemble()` layout parameter**

  **Goal:** Accept `layout: AvatarLayout` in `VideoEditor.assemble()` and route to the correct compositing path for each mode.

  **Requirements:** R3

  **Dependencies:** Unit 3

  **Files:**
  - Modify: `scripts/video_edit/video_editor.py`
  - Test: `scripts/video_edit/test_video_editor.py` (extend existing or create)

  **Approach:**
  - Add `layout: AvatarLayout = AvatarLayout.HALF_SCREEN` parameter to `assemble()`
  - `HALF_SCREEN`: existing compositing path — must produce identical output to current behaviour
  - `SKIPPED`: b-roll fills full frame (already exists as the `broll_only` path — just rename the branch)
  - `FULL_SCREEN`: avatar fills full frame — functional stub acceptable (resize avatar to 1080×1920, no b-roll overlay); mark with `# TODO: refine for production`
  - `STITCHED`: treated identically to `HALF_SCREEN` at this layer (stitching happens before `assemble()` is called; the stitched file is passed as `avatar_path`)
  - Keep `crop_to_portrait` parameter as-is; it is orthogonal to layout

  **Patterns to follow:**
  - Existing `HOOK_DURATION_S` / `CTA_DURATION_S` compositing logic in `video_editor.py`
  - MoviePy 2.x API: `.resized()`, `.with_audio()`, `.with_position()` (already ported in this codebase)

  **Test scenarios:**
  - `layout=HALF_SCREEN` produces the same composite geometry as the pre-refactor `assemble()` call
  - `layout=SKIPPED` fills the full 1080×1920 frame with b-roll
  - `layout=FULL_SCREEN` produces a non-zero output file (stub is acceptable)
  - Unknown layout value raises `ValueError`

  **Verification:**
  - Tests pass; no `MoviePy` import errors
  - A manual spot-check of `HALF_SCREEN` output is visually unchanged from the current pipeline

---

- [ ] **Unit 5: Smoke test + pipeline config wiring**

  **Goal:** Update `smoke_kling.py` (or create `smoke_avatar.py`) to test VEED Fabric end-to-end; set `AVATAR_PROVIDER=veed` as the default in config.

  **Requirements:** R1, R6

  **Dependencies:** Unit 1, Unit 2

  **Files:**
  - Modify: `scripts/smoke_kling.py` (rename or extend to `smoke_avatar.py`)
  - Modify: `config/settings.py` or `.env.example` — default provider
  - Modify: `scripts/commoncreed_pipeline.py` — `make_avatar_client` call passes VEED config keys

  **Approach:**
  - Rename `smoke_kling.py` → `smoke_avatar.py`; parameterise the provider via `AVATAR_PROVIDER` env var so the same script tests whichever provider is configured
  - `step_kling()` becomes `step_avatar(provider_name, audio_url)` — dispatches through `make_avatar_client` rather than instantiating `KlingAvatarClient` directly
  - Add `VEED_AVATAR_IMAGE_URL` env var (can reuse `KLING_AVATAR_IMAGE_URL` value) to `.env.example`
  - `commoncreed_pipeline.py` config block: add `veed_avatar_image_url` key; `make_avatar_client` receives it

  **Patterns to follow:**
  - Current `smoke_kling.py` step structure
  - `_env()` helper for required env var assertions

  **Test scenarios:**
  - With `AVATAR_PROVIDER=veed`: smoke test completes steps 1–5 (voice → upload → submit → poll → download)
  - With `AVATAR_PROVIDER=kling`: same script works unchanged (regression guard)
  - Missing `VEED_AVATAR_IMAGE_URL` exits with clear error message

  **Verification:**
  - `python3 smoke_avatar.py` with `AVATAR_PROVIDER=veed` produces a non-zero `.mp4` in `output/avatar/`
  - Output file is playable and shows lip-sync to the test audio

## System-Wide Impact

- **Interaction graph:** `commoncreed_pipeline._generate_script_voice_avatar()` → `VeedFabricClient.generate()` → fal.ai queue → `_assemble()` → `VideoEditor.assemble()`. No callbacks or observers; changes are confined to Phase 1 and Phase 3 of the pipeline.
- **Error propagation:** `AvatarQualityError` is caught in `_generate_script_voice_avatar()` with one auto-retry; on second failure, sets `avatar_layout = SKIPPED`. The `SKIPPED` path already handles graceful fallback. No new error types introduced.
- **State lifecycle risks:** `audio_url` must remain valid for the full VEED generation window. catbox.moe URLs (used in smoke test) are temporary — production pipeline should use a more durable upload (Ayrshare on paid plan, or an S3/R2 pre-signed URL).
- **API surface parity:** `smoke_avatar.py` acts as the integration surface for all providers — adding a new provider means adding a test branch here, not a new smoke test file.
- **Integration coverage:** The smoke test (Unit 5) is the primary cross-layer proof. Unit tests in Units 1–4 cover individual components; only the smoke test proves the full chain.

## Risks & Dependencies

- **VEED Fabric response shape unknown until first live call**: Mitigated by the `_extract_video_url()` helper isolating this to one method.
- **catbox.moe audio URLs may expire before VEED completes**: For smoke tests this is acceptable. Production pipeline should not depend on catbox.moe — this is a known limitation already tracked.
- **`broll_only` alias must not break existing guards**: The `@property` alias approach ensures backward compatibility without a codebase-wide find/replace.
- **fal.ai account balance**: Live smoke test requires a top-up. Unit tests should mock the HTTP layer to run offline.

## Sources & References

- Related plan: [docs/plans/2026-03-29-002-refactor-heygen-avatar-integration-plan.md](docs/plans/2026-03-29-002-refactor-heygen-avatar-integration-plan.md)
- Related learning: [docs/solutions/workflow-issues/intelligent-broll-type-selection-gpu-phase-gating-2026-03-29.md](docs/solutions/workflow-issues/intelligent-broll-type-selection-gpu-phase-gating-2026-03-29.md)
- VEED Fabric 1.0 on fal.ai: `veed/fabric-1.0` — verified live, $0.08/s at 480p
- Kling v1 Pro on fal.ai: `fal-ai/kling-video/v1/pro/ai-avatar` — verified live, $0.115/s
