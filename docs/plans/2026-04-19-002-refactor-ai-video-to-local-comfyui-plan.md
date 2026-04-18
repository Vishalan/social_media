---
title: "refactor: Move ai_video b-roll off RunPod onto the local RTX 3090 ComfyUI"
type: refactor
status: queued
date: 2026-04-19
origin: (no brainstorm — follow-up from chatterbox-on-3090 work)
---

# refactor: Move `ai_video` b-roll off RunPod onto the local RTX 3090 ComfyUI

## Context

Post engage-v2, the pipeline selector almost never picks `ai_video` — the 10 CPU/Remotion b-roll types cover every concrete topic. For the rare abstract/speculative shorts where `ai_video` still wins, the pipeline currently boots a RunPod pod (~30s cold start) for a ~10s Wan2.1 1.3B render, then tears it down.

The Ubuntu server now has a live RTX 3090 serving chatterbox (~3.5 GB VRAM). It has ~20 GB of headroom — enough to run ComfyUI + Wan2.1 1.3B alongside chatterbox with zero pod lifecycle overhead and zero cloud bill.

This refactor drops the RunPod dependency entirely by pointing `COMFYUI_URL` at a local ComfyUI sidecar running on the same box.

## Goals

1. `ai_video` generation runs on the local 3090 via a new `commoncreed_comfyui` sidecar container.
2. `RUNPOD_API_KEY` is no longer required for the pipeline to boot. RunPod code paths stay in the tree (rollback path) but become unreachable in prod.
3. Concurrent chatterbox + ComfyUI requests on the same GPU do not OOM or starve each other.

## Scope Boundaries

- **Not touching the b-roll selector or registry** — `ai_video` stays registered, stays selectable, keeps its description.
- **Not re-training or replacing Wan2.1 1.3B.** Same model, same workflow JSON, different serving location.
- **Not removing the `scripts/gpu/pod_manager.py` module** — keep it around as a disabled rollback path in case local ComfyUI becomes unavailable.

## Requirements Trace

- **R1.** Launch ComfyUI with Wan2.1 1.3B on the RTX 3090 via Docker, exposed only on the compose network.
- **R2.** Share the 3090 between `commoncreed_chatterbox` and `commoncreed_comfyui`. Neither should OOM the other under normal content-production load.
- **R3.** Pipeline reads `COMFYUI_URL=http://commoncreed_comfyui:8188` from `.env` and skips the RunPod code path entirely when set.
- **R4.** Model weights (Wan2.1 1.3B, ~4 GB) persist across container restarts via a named volume — no re-download on every boot.
- **R5.** Health check on `/system_stats` responds within 1s of container start.

## Implementation Units

- [ ] **Unit 1: `deploy/comfyui/` sidecar — Dockerfile + requirements + workflow pre-load**

**Goal:** Container image that boots ComfyUI on port 8188 with Wan2.1 1.3B pre-downloaded to a persistent cache dir.

**Files:**
- Create: `deploy/comfyui/Dockerfile` (base: `pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime`, same base as chatterbox)
- Create: `deploy/comfyui/requirements.txt`
- Create: `deploy/comfyui/entrypoint.sh` (preflight: ensure model weights present before exec'ing comfyui)
- Create: `deploy/comfyui/models.txt` (manifest of Hugging Face / civitai URLs for Wan2.1 1.3B + any VAE/encoders)

**Approach:**
- Install ComfyUI from source (`git clone https://github.com/comfyanonymous/ComfyUI`).
- Pre-download Wan2.1 1.3B weights at image-build time into `/models/checkpoints/` so container startup is fast.
- Expose `8188` only on the compose network (no host publish — same pattern as chatterbox and remotion).
- Entrypoint verifies model file sizes match expected before starting server — fail fast if download corrupted.

**Verification:**
- `docker run --gpus all commoncreed/comfyui:0.1.0` starts in <30s and answers `GET /system_stats` with GPU info.
- Image size acceptable (target <10GB — pytorch base ~5GB + ComfyUI ~1GB + model weights ~4GB).

---

- [ ] **Unit 2: Wire `commoncreed_comfyui` into `deploy/portainer/docker-compose.yml`**

**Goal:** New service in the Portainer stack with GPU reservation matched to chatterbox.

**Files:**
- Modify: `deploy/portainer/docker-compose.yml`

**Approach:**
- Append new `commoncreed_comfyui` service after `commoncreed_chatterbox`.
- Same GPU reservation shape (`deploy.resources.reservations.devices: [{driver: nvidia, count: 1, capabilities: [gpu]}]`) — both containers share GPU 0.
- New named volume `commoncreed_comfyui_cache` for model weights so restarts don't re-download.
- Shared `commoncreed_output` mount so generated MP4s land where the Python sidecar expects.
- Memory limits: 8 GB hard limit (Wan2.1 1.3B alone is small; allow headroom for video frames on host RAM).

**Patterns to follow:** `commoncreed_chatterbox` block in the same file — nvidia reservation, compose-network-only expose, model-cache volume.

**Verification:**
- `regen_prod_compose` regex in `.claude/skills/cc-deploy-portainer/cc_update_stack.py` correctly strips the new service's `build:` block.
- Stack update via cc_update_stack.py lands cleanly with both GPU services.

---

- [ ] **Unit 3: GPU coexistence test — chatterbox + ComfyUI concurrent**

**Goal:** Prove both services can run a request at the same time without OOM on the 3090.

**Files:**
- Create: `deploy/comfyui/tests/test_coexistence.sh` (docker exec-based smoke)

**Execution note:** characterization-first — capture current VRAM usage with chatterbox alone, then with both warm, then with both mid-generation.

**Approach:**
- Step 1: Warm chatterbox (POST `/tts` once to trigger model load, observe `nvidia-smi` used memory).
- Step 2: Warm ComfyUI (queue a Wan2.1 1.3B render, observe memory).
- Step 3: Fire both in parallel (chatterbox `/tts` + ComfyUI `/prompt`). Both should complete; GPU util should spike to 100%; VRAM should stay under 20 GB.
- Step 4: Document observed peak VRAM in `docs/solutions/integration-issues/3090-gpu-coexistence.md`.

**Verification:**
- Parallel test completes with both outputs valid.
- Peak VRAM ≤ 22 GB (leaves 2 GB safety margin under 24 GB total).
- Neither container restarts/OOMs during the test.

---

- [ ] **Unit 4: Flip `COMFYUI_URL` in `.env` + remove RunPod startup-gate requirement**

**Goal:** Pipeline points at local ComfyUI, boots fine without `RUNPOD_API_KEY`.

**Files:**
- Modify: `/opt/commoncreed/.env` (server-side only — `COMFYUI_URL=http://commoncreed_comfyui:8188`)
- Modify: `scripts/commoncreed_pipeline.py` line ~802–810 (the `use_runpod` startup gate) — make `COMFYUI_URL` presence sufficient without any RunPod fallback requirement
- Modify: `.env.example` — document that `COMFYUI_URL` is now the default path and `RUNPOD_API_KEY` is optional

**Approach:**
- Flip .env in place (preserve inode — lesson from today's chatterbox flip where `mv` rotated the inode and bind-mount saw stale content).
- Update pipeline startup check: accept either `COMFYUI_URL` or `RUNPOD_API_KEY`; current code actually already does this correctly (`use_runpod = not COMFYUI_URL and bool(RUNPOD_API_KEY)`) — verify this holds.
- cc_update_stack.py to propagate env change.

**Verification:**
- Pipeline subprocess inside sidecar can `curl commoncreed_comfyui:8188/system_stats` and get a 200.
- A canary topic that forces the selector to pick `ai_video` (abstract/speculative prompt) completes the full pipeline with the local ComfyUI instead of RunPod.
- RunPod dashboard shows zero new pod starts after the flip.

---

- [ ] **Unit 5: Verify no regressions + update docs**

**Goal:** Sanity — the pipeline still runs the same way for concrete topics, and the docs reflect the new default.

**Files:**
- Modify: `CLAUDE.md` — update "External Dependencies & APIs" table (RunPod moves from line to a footnote; add local ComfyUI).
- Create: `docs/solutions/integration-issues/ai-video-local-on-3090-<date>.md` — solution doc with peak VRAM observations + lessons.

**Verification:**
- One canary run with a concrete topic (selector picks phone_highlight or stats_card) — no change from today's behavior.
- One canary run with an abstract topic (selector picks ai_video) — routes to local ComfyUI successfully.

## Sources & References

- `scripts/broll_gen/registry.py` — `ai_video` metadata
- `scripts/broll_gen/ai_video.py` — current generator
- `scripts/gpu/pod_manager.py` — RunPod lifecycle (stays as dormant rollback)
- `scripts/commoncreed_pipeline.py:802-815` — the startup gate
- `deploy/chatterbox/` — pattern for the new GPU sidecar
- `docs/solutions/workflow-issues/intelligent-broll-type-selection-gpu-phase-gating-2026-03-29.md` — original GPU phase-gating design

## Deferred to Implementation

- **Exact Wan2.1 1.3B weights URL + checksum.** Confirm during Unit 1 against the current ComfyUI workflow JSON at `comfyui_workflows/short_video_wan21.json`.
- **Whether to run Wan2.1 in FP16 or INT8.** INT8 would cut VRAM to ~2GB but may degrade output; measure in Unit 3.
- **GPU device assignment syntax** — `count: 1` with two services both requesting it lets Docker schedule them on the same GPU; verify this works on the host driver (tested with `nvidia-smi -L` showing both containers on GPU 0 during Unit 3).

## Explicit Non-Goals

- Replacing Wan2.1 with a newer model (Wan2.2 S2V, EchoMimic, etc.) — separate plan.
- Hot-swapping chatterbox and ComfyUI for GPU time slices — Linux handles concurrent CUDA contexts fine for this workload size.
- Removing `scripts/gpu/pod_manager.py` — keep as a disabled rollback in case we ever need RunPod back.
- Changing any b-roll type other than `ai_video`.
