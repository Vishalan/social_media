---
date: 2026-08-15
topic: vishalan-ai-channel-research-spike
---

# Vishalan AI Channel — Avatar Shorts Pipeline v3 Research Spike

## Problem Frame

Owner wants a **new personal channel under his own name and face**: vertical 9:16 shorts/reels ≤ 60 s about AI & tech, presented by a photoreal avatar of himself (full-screen, split-screen, or round PIP), narrated in his cloned voice, with aesthetic quick cuts, b-roll, and statistics cards.

A previous avatar pipeline (EchoMimic V3 / VEED via fal.ai, Apr 2026) was wired end-to-end but **paused on 2026-04-21 because visual quality was below the owner's bar** — the failure was in the *design of the short* (avatar realism + editing quality together), not in tooling availability. Four to five months have passed; the model landscape and short-form editing standards have moved.

This document scopes a **time-boxed research spike**, not the build. Its job is to find out — with produced clips, not on paper — whether a publishable v3 pipeline can run on the home server, and if so, with which stack.

## Requirements

### Research scope
- R1. Survey and shortlist **avatar generation** approaches that can produce a photoreal talking version of the owner from supplied reference material (photos and/or recorded footage), targeting the RTX 3090 (24 GB). Include image-driven talking-head models, video/identity-driven models, and lip-sync-over-real-footage approaches.
- R2. Survey and shortlist **cloned-voice TTS** options that reproduce the owner's voice with natural prosody, local-first.
- R3. Survey current (last 3–4 weeks) **short-form editing grammar**: hook structures, cut cadence, caption styling, on-screen text, and transitions that drive retention for talking-head tech content.
- R4. Survey and shortlist **b-roll, a-roll, and statistics-card generation** approaches (stock, generative image/video, motion-graphics templates) suitable for a fully local pipeline.
- R5. Survey **caption/subtitle generation** (word-level timing, styling, burn-in) with accuracy fit for publish without manual correction.
- R6. Research recency: prioritise sources, model releases, and community results from the **last 3–4 weeks before the spike starts**; older material only as background.
- R7. Reuse prior repo learnings (avatar_gen factory, ComfyUI workflows, Remotion compositions, Chatterbox, topic sources) as *inputs*, but do not let them bias the shortlist. Every prior choice is re-evaluated against current options.

### Deliverables
- R8. A **reference-capture spec**: exactly what photos/footage/audio the owner must record (framing, lighting, duration, phrases), so the shortlisted approaches have optimal input. Owner will supply whatever is specified.
- R9. **Track A — avatar realism gate**: side-by-side avatar-only tests of the shortlisted approaches, in all three layouts (full-screen, split-screen, round PIP), with an explicit go/no-go verdict.
- R10. **Track B — reference short**: one 45–60 s short built with the candidate editing/voice/caption/b-roll/stat-card stack, using a stand-in for the avatar if needed, that demonstrates the target hook grammar and cut rhythm.
- R11. **3–5 finished sample shorts** (30–60 s, 9:16) that combine the winning avatar approach with the reference-short pipeline, on real recent AI/tech topics.
- R12. A **stack recommendation report**: what was tried, what won and why, quality observations, render time and VRAM per clip, any cloud step recommended (with per-video cost), and known limitations.
- R13. An **evaluation rubric** applied consistently across candidates: identity likeness, lip-sync accuracy, motion/body naturalness, layout fit, voice naturalness, caption accuracy, hook strength, overall "would I publish this" score.

### Constraints
- R14. **Local-first**: every recommended step must have a local path on the RTX 3090 / 62 GB RAM server. A paid cloud step may be *recommended* only where the quality gap is large, and must be reported with cost per video.
- R15. **Spend consent gate**: no paid API usage (including Anthropic API, fal.ai, RunPod, ElevenLabs) without the owner's explicit consent per instance/budget. Free tiers and local inference need no consent.
- R16. **Intelligence layer** (script drafting, research synthesis, planning) runs inside the Claude Code harness during the spike, not via metered API calls.
- R17. **Render budget** for the eventual pipeline: ≤ 8 h per finished 60 s short (overnight batch acceptable). Candidates exceeding this are out.
- R18. The spike must not disturb the running production stack (Postiz, sidecar meme pipeline) — GPU time-sharing is fine, outages are not.

## Success Criteria

- Owner watches the 3–5 sample shorts and marks at least one stack as **"I would publish this under my name"**.
- Track A produces an unambiguous go/no-go on local photoreal avatar generation, with evidence clips.
- Recommended stack has documented render time and VRAM within budget on the actual server.
- Reference-capture spec is concrete enough that the owner can record it in one sitting.
- Report is sufficient for `/ce:plan` to plan the v3 build without re-doing model research.

## Scope Boundaries

- **Not building the production pipeline** — no scheduler, Postiz integration, or approval flow work in this spike.
- **Not choosing channel branding** (name, palette, thumbnails) — separate track.
- **Not training/fine-tuning base models** beyond lightweight identity/voice adaptation (LoRA/voice clone) if a candidate requires it.
- **Not committing to a cloud provider** — cloud appears only as an evaluated, priced alternative.
- **Not producing content for @commoncreed** — this is a new personal channel.

## Key Decisions

- **Research spike before build**: v2 failed on quality, not plumbing; produce clips and judge by eye before writing pipeline code.
- **Two parallel tracks (avatar gate + reference short)**: isolates the two independent risks so one doesn't mask the other; the reference short directly attacks the editing-quality failure of v2.
- **Personal photoreal channel**: highest realism bar; stylised avatars are out.
- **Cloned voice**: consistent with a personal-face channel; owner-recorded audio per video rejected as too manual.
- **Reference material is unconstrained**: owner supplies whatever the research specifies (R8), which unlocks footage-driven and lip-sync-over-footage approaches.
- **Overnight render budget**: quality first; enables heavier models than v2 allowed.
- **Consent gate on spend**: local by default; owner approves any metered usage explicitly.

## Dependencies / Assumptions

- Server: RTX 3090 24 GB, 62 GB RAM, Ubuntu 24.04, Docker stack running; ComfyUI container exists but is usually stopped and may need model re-downloads.
- Assumed **~3-week time box** (Track A/B in parallel week 1–2, convergence + samples week 2–3). Adjustable.
- Sample topics come from the existing topic sources (HN, GitHub trending, arXiv, etc.) so samples exercise a realistic path.
- Owner available to record reference material within the first few days once R8 is delivered.
- Prior artifacts consulted as input: `docs/brainstorms/2026-04-05-echomimic-v3-*`, `2026-04-15-local-avatar-generation-*`, `2026-04-18-engagement-layer-v2-*`, `scripts/avatar_gen/`, `comfyui_workflows/`, `deploy/remotion/`.

## Outstanding Questions

### Resolve Before Planning
- (none)

### Deferred to Planning
- [Affects R1][Needs research] Which local avatar approaches are viable in Aug 2026 (image-driven vs. video-driven vs. lip-sync-over-footage) and their VRAM/time envelopes on a 3090.
- [Affects R2][Needs research] Best local voice-clone quality vs. ElevenLabs baseline; how much reference audio is needed.
- [Affects R3][Needs research] Current retention-tested hook/caption patterns for talking-head tech shorts; which are automatable.
- [Affects R4][Needs research] Local generative b-roll/stat-card options that fit the render budget alongside the avatar step.
- [Affects R9][Technical] How to run candidate models side-by-side on the shared GPU without disturbing production (R18).
- [Affects R11][Technical] Whether existing Remotion compositions can host the three layouts or need a fresh template.
- [Affects R12][User decision, later] If no local avatar passes the gate, whether a priced cloud avatar step is acceptable for the build.

## Next Steps

→ `/ce:plan` for structured implementation planning of the research spike (track setup, candidate list, evaluation harness, capture spec).
