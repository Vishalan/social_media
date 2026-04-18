---
date: 2026-04-15
topic: local-avatar-generation
---

# Local Avatar Generation — Replace VEED/Fabric with Wan2.2-S2V on RTX 3090

## Problem Frame

The CommonCreed avatar pipeline currently uses EchoMimic V3 (local) + VEED Fabric via fal.ai (cloud fallback at $0.15/sec). With the RTX 3090 (24 GB VRAM) upgrade, a higher-quality open-source model can replace both — eliminating cloud API costs while improving output quality to near-commercial levels.

## Requirements

- R1. Add Wan2.2-S2V-14B as a configurable avatar provider on the RTX 3090 — selectable via `.env`, not a replacement for EchoMimic V3
- R2. Model runs at 768x768 resolution with quantization (Q5/Q6) to fit 24 GB VRAM
- R3. Existing avatar_gen factory pattern (`scripts/avatar_gen/factory.py`) supports Wan2.2 as a new provider alongside EchoMimic V3 (kept as fast fallback)
- R4. ComfyUI workflow for Wan2.2-S2V integrated into the pipeline (same pattern as `echomimic_v3_avatar.json`)
- R5. VEED/Fabric cloud API remains available as a provider option
- R6. Output: lip-synced upper-body talking head video from reference image + audio, 30-60s clips
- R7. Optional: MuseTalk as a fast post-processing lip-sync refinement step on Wan2.2 output
- R8. Quality comparison step: generate the same clip with both EchoMimic V3 and Wan2.2, present side-by-side to the owner for visual comparison before choosing a default
- R9. Provider selection via `AVATAR_PROVIDER` env var (echomimic_v3 | wan22_s2v | veed) — all 3 remain available

## Success Criteria

- Avatar quality visibly better than EchoMimic V3 (lip sync accuracy, naturalness, body language)
- Generation completes in <15 min per 30s clip on RTX 3090
- No cloud API cost for standard daily avatar generation (2-3 shorts/day)
- Identity consistency maintained across multiple clips using same reference image

## Scope Boundaries

- Not replacing the entire video pipeline — only the avatar generation step
- Not training or fine-tuning models — using pre-trained weights as-is
- MuseTalk refinement is optional/deferred — nice-to-have, not blocking
- HunyuanVideo-Avatar / daVinci-MagiHuman are cloud-only — out of scope for local deployment

## Key Decisions

- **Wan2.2-S2V-14B over Hallo3**: Wan2.2 has Apache 2.0 license (vs uncertain for Hallo3), mature ComfyUI integration, and official support for audio-driven generation. Hallo3 is portrait-focused and has less community tooling.
- **Keep EchoMimic V3 as fast fallback**: For time-sensitive generation or when GPU is busy with other tasks (Ollama inference, ffmpeg), EchoMimic V3 at 1.3B params is much faster.
- **768x768 target resolution**: Fits 24 GB with the 14B model quantized. Higher resolution would require cloud GPU.
- **Quality over speed**: 10 min per 30s clip is acceptable for 2-3 shorts/day production volume.

## Dependencies / Assumptions

- RTX 3090 with 24 GB VRAM installed and NVIDIA Container Toolkit working (confirmed)
- ComfyUI running on the server (needs setup — currently not deployed)
- Wan2.2-S2V-14B weights available on HuggingFace (~28 GB download for full model, less with quantization)
- Ollama and Wan2.2 can time-share the GPU — Ollama auto-evicts when VRAM is needed

## Outstanding Questions

### Deferred to Planning

- [Affects R1][Needs research] Exact ComfyUI workflow configuration for Wan2.2-S2V audio-driven mode — community workflows exist but need validation
- [Affects R2][Technical] Which quantization format works best for Wan2.2 on 3090 — Q5_K_M vs Q6_K vs native FP16 with aggressive context limits
- [Affects R4][Technical] ComfyUI deployment — Docker container vs native install, GPU sharing with Ollama
- [Affects R7][Needs research] MuseTalk integration as post-processing — whether it materially improves Wan2.2 output or is redundant

## Next Steps

→ `/ce:plan` for structured implementation planning
