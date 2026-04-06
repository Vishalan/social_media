---
date: 2026-04-05
topic: echomimic-v3-avatar-provider
---

# EchoMimic V3 as Cost-Optimized Avatar Provider

## Problem Frame

VEED Fabric produces excellent lip-synced avatars but costs $1.53/video (~$137/month at 3 videos/day). EchoMimic V3 is the only open-source model with half-body + hand gestures + lip sync from audio, at ~99% lower cost. Before investing in infrastructure (RunPod Serverless Docker image, deployment scripts), validate quality by testing through a hosted API (Replicate or HuggingFace Spaces).

## Requirements

- R1. **Quality benchmark**: Generate 3-5 avatar clips from the same audio segments used in recent VEED runs. Compare side-by-side: lip sync accuracy, hand gesture naturalness, face quality, 9:16 aspect ratio support.
- R2. **Hosted API test**: Use Replicate or HuggingFace hosted EchoMimic V3 — zero infrastructure setup. Only proceed to RunPod Serverless integration if quality passes the user's visual review.
- R3. **Provider integration** (conditional on R2 passing): Add `echomimic-v3` as a new avatar provider in `avatar_gen/`, implementing the existing `AvatarClient` interface (`generate(audio_url, output_path)`).
- R4. **Parameterised selection**: Avatar provider selectable via `AVATAR_PROVIDER` env var or `--avatar-provider` CLI flag. Default remains VEED; EchoMimic is opt-in.
- R5. **Fallback chain**: If EchoMimic fails or times out (10 min), auto-fallback to VEED. Chain configurable.

## Success Criteria

- User visually confirms EchoMimic V3 lip sync and gestures are acceptable quality (compared to VEED side-by-side)
- If quality passes: full RunPod Serverless integration reduces avatar cost from $137/month to <$5/month
- Pipeline runs identically with either provider — no code changes needed to switch

## Scope Boundaries

- NOT building RunPod Serverless infrastructure until quality is validated (R2 gates R3)
- NOT replacing VEED as default — EchoMimic is opt-in
- NOT benchmarking other open-source models (MuseTalk, SadTalker) — EchoMimic V3 is the only one with hand gestures
- NOT changing the per-segment avatar architecture — EchoMimic V3 receives the same 4 separate audio segments

## Key Decisions

- **Test on hosted API first**: Replicate/HuggingFace before any RunPod infra work. Proves quality at near-zero cost ($0.10-0.50 for 5 test clips).
- **Quality decision is manual**: The user visually reviews the benchmark clips and decides whether to proceed. No automated quality scoring.
- **Per-segment architecture preserved**: EchoMimic V3 receives 4 separate audio segments (hook, pip1, pip2, cta), same as VEED. No concatenated audio.

## Dependencies / Assumptions

- EchoMimic V3 is available on Replicate or HuggingFace Spaces with an API
- EchoMimic V3 supports audio-only input (no video reference needed beyond the portrait image)
- Output is MP4 at sufficient resolution for 480p+ final video

## Outstanding Questions

### Deferred to Planning

- [Affects R2][Needs research] Is EchoMimic V3 available on Replicate? Check `replicate.com/models` for `echomimic` or `echo-mimic`
- [Affects R2][Needs research] If not on Replicate, is there a HuggingFace Space with API access?
- [Affects R3][Technical] RunPod Serverless Docker image — what base image, which model weights to bake in, FlashBoot compatibility
- [Affects R3][Technical] EchoMimic V3 inference time per second of output on A5000 vs 4090
- [Affects R5][Technical] How to implement fallback chain in `avatar_gen/factory.py` — sequential try/except or configurable priority list

## Next Steps

→ `/ce:plan` for structured implementation planning (start with R1/R2 quality benchmark)
