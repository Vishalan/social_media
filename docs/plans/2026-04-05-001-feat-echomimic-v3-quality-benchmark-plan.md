---
title: "feat: EchoMimic V3 quality benchmark via hosted API"
type: feat
status: active
date: 2026-04-05
origin: docs/brainstorms/2026-04-05-echomimic-v3-avatar-provider-requirements.md
---

# feat: EchoMimic V3 quality benchmark via hosted API

## Overview

Test EchoMimic V3 avatar quality against VEED Fabric using a hosted API (Replicate or HuggingFace) before investing in RunPod Serverless infrastructure. If quality passes the user's visual review, proceed to full provider integration (R3-R5 in origin doc). This plan covers only R1 and R2 — the quality benchmark.

## Problem Frame

VEED Fabric costs $1.53/video for avatar generation (~$137/month at 3 videos/day). EchoMimic V3 could reduce this to <$5/month, but quality is unverified. The user wants to see the output before committing to infrastructure work. (see origin: docs/brainstorms/2026-04-05-echomimic-v3-avatar-provider-requirements.md)

## Requirements Trace

- R1. Generate 3-5 avatar clips from the same audio segments used in recent VEED runs. Compare side-by-side.
- R2. Use Replicate or HuggingFace hosted EchoMimic V3 — zero infrastructure setup.

## Scope Boundaries

- NOT building RunPod Serverless infrastructure (gated by quality review)
- NOT integrating into the pipeline (R3-R5 deferred)
- NOT benchmarking other models (MuseTalk, SadTalker)
- This is a manual quality evaluation — no automated scoring

## Context & Research

### Relevant Code and Patterns

- `scripts/avatar_gen/veed_client.py` — existing provider pattern: `AvatarClient` ABC with `generate(audio_url, output_path)`, async polling, httpx downloads
- `scripts/avatar_gen/factory.py` — provider registration via `make_avatar_client(config)`
- `scripts/smoke_e2e.py` — `_extract_avatar_segments()` produces separate audio files per segment; `_compute_avatar_windows()` computes timestamps
- `output/debug_avatar/` — existing debug assets from VEED runs (audio segments + merged clips for comparison)
- Portrait image: `assets/logos/owner-portrait-9x16.jpg` (765x1360, 9:16 cropped)

### Institutional Learnings

- `docs/solutions/integration-issues/avatar-lip-sync-desync-across-segments-2026-04-05.md` — separate VEED calls per segment for perfect lip sync. Same approach applies to EchoMimic V3.

## Key Technical Decisions

- **Replicate first, HuggingFace fallback**: Replicate has a cleaner API for one-off tests (`replicate.run()`). If EchoMimic V3 isn't on Replicate, try HuggingFace Inference API.
- **Reuse existing audio segments**: Use the `*_sent_to_veed.mp3` files from `output/debug_avatar/` as input — same audio that produced the VEED clips, enabling direct comparison.
- **Standalone benchmark script**: Not integrated into the pipeline. A self-contained script that generates clips, merges with audio, and saves side-by-side comparison files.

## Open Questions

### Resolved During Planning

- **Which audio to use?** Reuse the existing `output/debug_avatar/*_sent_to_veed.mp3` files from the latest VEED run. Same audio = fair comparison.

### Deferred to Implementation

- Is EchoMimic V3 available on Replicate? Search `replicate.com` for the model.
- If not on Replicate, does HuggingFace have a hosted Space with API?
- What input format does EchoMimic V3 expect? (audio file + portrait image, or different?)
- Does EchoMimic V3 support 9:16 output natively or does it need post-processing?

## Implementation Units

- [ ] **Unit 1: Discover hosted EchoMimic V3 API**

**Goal:** Find a hosted EchoMimic V3 endpoint (Replicate or HuggingFace) and verify its API contract.

**Requirements:** R2

**Dependencies:** None

**Files:**
- None (web research only)

**Approach:**
- Search Replicate for `echomimic` models
- If found: note the model ID, input schema (audio, image, parameters), output format, and pricing
- If not on Replicate: search HuggingFace Spaces for EchoMimic V3 with API access
- If neither: report back — may need to fall back to RunPod GPU Pod for a quick test

**Verification:**
- A working API endpoint URL and input/output schema documented

---

- [ ] **Unit 2: Generate benchmark clips**

**Goal:** Generate 4 avatar clips (hook, pip1, pip2, cta) from EchoMimic V3 using the same audio segments that produced the VEED clips.

**Requirements:** R1, R2

**Dependencies:** Unit 1

**Files:**
- Create: `scripts/benchmark_echomimic.py`
- Input: `output/debug_avatar/*_sent_to_veed.mp3`, `assets/logos/owner-portrait-9x16.jpg`
- Output: `output/benchmark_echomimic/` (generated clips)

**Approach:**
- Read the 4 audio segment files from `output/debug_avatar/`
- For each, call the hosted EchoMimic V3 API with the audio + portrait image
- Download the generated video clips
- Merge each with its original audio segment (same as debug asset pattern)
- Save as `output/benchmark_echomimic/{hook,pip1,pip2,cta}_echomimic.mp4`

**Patterns to follow:**
- `scripts/smoke_e2e.py` debug asset generation pattern (merge avatar clip with original audio)
- `scripts/avatar_gen/veed_client.py` async polling pattern (if Replicate uses async jobs)

**Test scenarios:**
- All 4 clips generate without error
- Output is valid MP4 with video+audio tracks
- Resolution is at least 480px wide

**Verification:**
- 4 MP4 files in `output/benchmark_echomimic/` that can be played and visually compared against `output/debug_avatar/*_avatar_with_original_audio.mp4`

---

- [ ] **Unit 3: Side-by-side comparison**

**Goal:** Create a visual comparison layout so the user can evaluate EchoMimic V3 quality against VEED.

**Requirements:** R1

**Dependencies:** Unit 2

**Files:**
- Output: `output/benchmark_echomimic/comparison_{hook,pip1,pip2,cta}.mp4`

**Approach:**
- For each segment, create a side-by-side video: VEED on left, EchoMimic on right
- Use FFmpeg `hstack` filter to combine
- Both at same resolution, same audio
- Label each side ("VEED Fabric" / "EchoMimic V3")
- Open the comparison folder for user review

**Verification:**
- User can play 4 comparison videos and make a quality decision
- Clear visual comparison of lip sync, gesture naturalness, face quality

## Risks & Dependencies

- **EchoMimic V3 not on any hosted platform**: If neither Replicate nor HuggingFace hosts it, we fall back to a RunPod GPU Pod (~$0.50/hour for 1 hour of testing). The benchmark script would need modification to use a direct GPU inference path.
- **Different input requirements**: EchoMimic V3 may require a reference video instead of a static portrait image. Verify in Unit 1 before proceeding.
- **Output resolution/format**: EchoMimic V3 may output in a different resolution or aspect ratio than VEED. May need FFmpeg scaling for fair comparison.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-05-echomimic-v3-avatar-provider-requirements.md](../brainstorms/2026-04-05-echomimic-v3-avatar-provider-requirements.md)
- Related code: `scripts/avatar_gen/veed_client.py`, `scripts/smoke_e2e.py`
- Related learning: `docs/solutions/integration-issues/avatar-lip-sync-desync-across-segments-2026-04-05.md`
