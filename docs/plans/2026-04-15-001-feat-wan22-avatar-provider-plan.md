---
title: "feat: Add Wan2.2-S2V-14B avatar provider with quality comparison"
type: feat
status: blocked-upstream
date: 2026-04-15
origin: docs/brainstorms/2026-04-15-local-avatar-generation-requirements.md
---

# feat: Add Wan2.2-S2V-14B avatar provider with quality comparison

## Overview

Add Wan2.2-S2V-14B as a configurable avatar generation provider on the RTX 3090, alongside the existing EchoMimic V3, VEED, Kling, and HeyGen options. Deploy ComfyUI on the server, create a Wan2.2-S2V workflow, integrate it into the factory pattern, and run a side-by-side quality comparison before choosing a default.

## BLOCKED STATUS — 2026-04-16

**Infrastructure ready, tooling ecosystem not yet mature for plug-and-play self-hosting.**

What's done:
- ComfyUI installed + running on server (port 8188)
- ComfyUI-GGUF, ComfyUI-WanVideoWrapper, ComfyUI-VideoHelperSuite custom nodes installed
- Models downloaded (~27 GB total): Wan2.2-S2V-14B Q5_K_M GGUF, T5 text encoder, VAE, Lightx2v LoRA, wav2vec audio encoder
- `Wan22S2VClient` integrated in factory pattern (`scripts/avatar_gen/factory.py`)
- Skeleton workflow at `comfyui_workflows/wan22_s2v_avatar.json`

What's blocked:
- The workflow uses ComfyUI's native `WanSoundImageToVideo` node with GGUF loader, but these fail with a tensor shape mismatch against the Q5_K_M quant
- kijai's WanVideoWrapper (which has working S2V nodes) requires a specific `Wan2_2-S2V-14B_fp8_e4m3fn_scaled_KJ.safetensors` file that isn't in kijai's public HuggingFace repo
- The two ecosystems (ComfyUI native + kijai) don't interop for Wan2.2-S2V as of April 2026

When to unblock:
- Option A: kijai uploads the scaled safetensors to public HF repo
- Option B: ComfyUI core adds native Wan2.2-S2V support compatible with GGUF loader
- Option C: Someone publishes a working GGUF-based Wan2.2-S2V workflow

Interim plan: stay on EchoMimic V3 (already working locally) for the generative avatar pipeline when `SIDECAR_DAILY_TRIGGER_ENABLED` is re-enabled.

## Problem Frame

The current avatar pipeline uses EchoMimic V3 (local, fast, moderate quality) or VEED Fabric (cloud, expensive at $0.15/sec). With the RTX 3090's 24 GB VRAM, the Wan2.2-S2V-14B model can run locally at 768x768 with cinematic quality — eliminating cloud API costs while significantly improving output. The user wants this configurable, not a replacement — all providers remain available. (see origin: `docs/brainstorms/2026-04-15-local-avatar-generation-requirements.md`)

## Requirements Trace

- R1. Wan2.2-S2V-14B as configurable provider via `AVATAR_PROVIDER=wan22_s2v` (origin R1, R9)
- R2. Runs at 768x768 on RTX 3090 with quantization (origin R2)
- R3. Integrated via existing factory pattern in `scripts/avatar_gen/factory.py` (origin R3)
- R4. ComfyUI workflow for Wan2.2-S2V audio-driven mode (origin R4)
- R5. All providers remain available: echomimic_v3, wan22_s2v, veed, kling, heygen (origin R5, R9)
- R6. Quality comparison: generate same clip with EchoMimic V3 + Wan2.2, present side-by-side (origin R8)

## Scope Boundaries

- Not replacing any existing provider — additive only
- Not training/fine-tuning — using pre-trained weights
- MuseTalk refinement deferred (origin R7)
- ComfyUI setup is a prerequisite, not a separate plan — included here as Unit 1

## Context & Research

### Relevant Code and Patterns

- `scripts/avatar_gen/factory.py` — provider factory, `make_avatar_client(config)`, dispatches by `avatar_provider` key
- `scripts/avatar_gen/base.py` — `AvatarClient` ABC with `generate()`, `needs_portrait_crop`, `max_duration_s`
- `scripts/avatar_gen/echomimic_client.py` — ComfyUI-based provider, loads workflow JSON, calls `comfyui_client.run_workflow()`
- `scripts/video_gen/comfyui_client.py` — `ComfyUIClient` class with WebSocket-based workflow execution
- `comfyui_workflows/echomimic_v3_avatar.json` — existing ComfyUI workflow template
- `deploy/portainer/docker-compose.yml` — Docker stack (ComfyUI not yet deployed)

## Key Technical Decisions

- **ComfyUI as native install, not Docker**: ComfyUI needs direct GPU access and the model weights (~28 GB) are large. Native install avoids Docker GPU passthrough complexity and volume mount overhead. Runs as a systemd service on port 8188, same as Ollama pattern.
- **Wan2.2-S2V client follows EchoMimic pattern**: Same approach — load a ComfyUI workflow JSON, substitute params, call `comfyui_client.run_workflow()`. No new integration pattern needed.
- **768x768 target resolution with Q5_K_M quantization**: Fits 24 GB VRAM while maintaining near-full quality. Higher resolution would require cloud GPU.
- **Quality comparison before setting default**: Generate same 30s clip with both EchoMimic V3 and Wan2.2, save side-by-side, present to owner. Default stays as-is until owner decides.

## Open Questions

### Resolved During Planning

- **ComfyUI Docker vs native?** → Native. Same reasoning as Ollama — direct GPU access, simpler setup, systemd for persistence. ComfyUI is a long-running server process, not a one-shot container.
- **How does sidecar reach ComfyUI?** → Direct HTTP to `http://localhost:8188` from the pipeline subprocess (which runs on host, not in Docker). The sidecar's `pipeline_runner.py` already spawns subprocesses on the host.

### Deferred to Implementation

- Exact ComfyUI custom nodes needed for Wan2.2-S2V — community workflows exist but node names may vary
- Whether Wan2.2 and Ollama can coexist in VRAM or need sequential scheduling — Ollama auto-evicts, but Wan2.2 through ComfyUI may not release VRAM gracefully
- Optimal `num_inference_steps` and CFG for Wan2.2 at 768x768 — tune during quality comparison

## Implementation Units

### Phase 1: Infrastructure

- [ ] **Unit 1: Install ComfyUI + Wan2.2 model on server**

**Goal:** ComfyUI running on the Ubuntu server with Wan2.2-S2V-14B model weights loaded and accessible via API.

**Requirements:** R2, R4

**Dependencies:** None (RTX 3090 confirmed installed)

**Files:**
- Server setup (SSH, not repo files)
- Create: systemd service file for ComfyUI

**Approach:**
- Clone ComfyUI to `/opt/comfyui/`
- Install ComfyUI custom nodes for Wan2.2-S2V (e.g., ComfyUI-WanVideoWrapper or equivalent)
- Download Wan2.2-S2V-14B weights from HuggingFace to ComfyUI models directory
- Create systemd service `comfyui.service` for auto-start
- Verify API at `http://localhost:8188/system_stats`

**Verification:**
- ComfyUI accessible at `http://localhost:8188`
- Wan2.2-S2V model appears in model list
- `nvidia-smi` shows GPU usage during a test workflow

---

- [ ] **Unit 2: Create Wan2.2-S2V ComfyUI workflow**

**Goal:** A ComfyUI workflow JSON that takes reference image + audio → produces lip-synced talking head video.

**Requirements:** R4

**Dependencies:** Unit 1

**Files:**
- Create: `comfyui_workflows/wan22_s2v_avatar.json`

**Approach:**
- Build workflow in ComfyUI UI using the Wan2.2-S2V audio-driven mode
- Configure: 768x768 resolution, 24fps, audio conditioning
- Export as JSON with placeholder params (reference_image, audio_path, output_path, seed)
- Test manually via ComfyUI API before integrating

**Patterns to follow:**
- `comfyui_workflows/echomimic_v3_avatar.json` — same param substitution pattern

**Verification:**
- Workflow produces a lip-synced video from reference image + audio via ComfyUI API
- Output is 768x768, has correct lip sync, shows upper body

---

### Phase 2: Pipeline Integration

- [ ] **Unit 3: Create Wan2.2 avatar client**

**Goal:** New `Wan22S2VClient` class following the `AvatarClient` interface.

**Requirements:** R1, R3

**Dependencies:** Unit 2

**Files:**
- Create: `scripts/avatar_gen/wan22_s2v_client.py`

**Approach:**
- Follow `echomimic_client.py` pattern exactly: load workflow JSON, substitute params, call `comfyui_client.run_workflow()`
- `needs_portrait_crop = False` (native 9:16 at 768x768)
- `max_duration_s = 60.0` (Wan2.2 handles longer clips natively)
- Include face presence check from EchoMimic (reuse `_check_face_presence`)

**Patterns to follow:**
- `scripts/avatar_gen/echomimic_client.py`
- `scripts/avatar_gen/base.py` — `AvatarClient` ABC

**Verification:**
- `Wan22S2VClient.generate(audio, output)` produces a valid MP4

---

- [ ] **Unit 4: Register in factory + add config**

**Goal:** `AVATAR_PROVIDER=wan22_s2v` works via the factory pattern with configurable env vars.

**Requirements:** R1, R5, R9

**Dependencies:** Unit 3

**Files:**
- Modify: `scripts/avatar_gen/factory.py`
- Modify: `scripts/avatar_gen/__init__.py` (export)

**Approach:**
- Add `wan22_s2v` case in `make_avatar_client()` alongside existing providers
- Config keys: `comfyui_url` (default `http://localhost:8188`), `wan22_reference_image` (reference image path)
- Update `_DEFAULT_PROVIDER` comment but keep current default unchanged

**Patterns to follow:**
- Existing factory cases for veed, kling, heygen, echomimic

**Verification:**
- `make_avatar_client({"avatar_provider": "wan22_s2v", ...})` returns a `Wan22S2VClient` instance
- `make_avatar_client({"avatar_provider": "veed", ...})` still works (regression)

---

### Phase 3: Quality Comparison

- [ ] **Unit 5: Side-by-side quality comparison**

**Goal:** Generate the same 30s clip with both EchoMimic V3 and Wan2.2-S2V, present to owner for visual comparison.

**Requirements:** R6, R8

**Dependencies:** Units 1-4

**Files:**
- Create: `scripts/benchmark_wan22.py` (comparison script)

**Approach:**
- Use the existing CommonCreed reference image + a sample 30s ElevenLabs audio clip
- Generate with EchoMimic V3 → `output/benchmark/echomimic_v3.mp4`
- Generate with Wan2.2-S2V → `output/benchmark/wan22_s2v.mp4`
- Optionally: create a side-by-side split-screen video using ffmpeg `hstack`
- Pull the results to dev Mac for owner review

**Verification:**
- Both videos generated successfully
- Owner can visually compare lip sync, naturalness, identity consistency
- Owner decides which to set as default `AVATAR_PROVIDER`

## System-Wide Impact

- **GPU sharing:** Wan2.2 (24 GB) and Ollama (5.5 GB) cannot coexist in VRAM simultaneously. ComfyUI holds the model in VRAM during workflow execution. Ollama auto-evicts when GPU memory is needed, but ComfyUI may not. The pipeline lock (`nas_heavy_work_lock`) already serializes heavy work, which prevents simultaneous usage.
- **Pipeline subprocess:** Avatar generation runs as a subprocess via `pipeline_runner.py`, not inside the sidecar Docker container. ComfyUI on the host is directly accessible.
- **No sidecar changes needed:** The factory and avatar clients live in `scripts/`, not `sidecar/`. The sidecar just spawns the pipeline subprocess.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Wan2.2 weights don't fit 24 GB with the workflow overhead | Use Q5_K_M quantization; fall back to 480p if needed |
| ComfyUI custom nodes for Wan2.2 are unstable | Test thoroughly in Unit 2 before integrating |
| Generation too slow for daily production (>15 min per 30s) | Keep EchoMimic V3 as fast fallback; Wan2.2 for quality-priority content |
| GPU contention with Ollama | Pipeline lock serializes; Ollama auto-evicts |

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-15-local-avatar-generation-requirements.md](docs/brainstorms/2026-04-15-local-avatar-generation-requirements.md)
- Factory pattern: `scripts/avatar_gen/factory.py`
- EchoMimic client: `scripts/avatar_gen/echomimic_client.py`
- ComfyUI client: `scripts/video_gen/comfyui_client.py`
- Existing workflows: `comfyui_workflows/`
- Wan2.2-S2V on HuggingFace: `Wan-AI/Wan2.2-S2V-14B`
