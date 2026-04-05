---
date: 2026-04-02
topic: video-quality-fullscreen-layout
---

# Video Quality: Full-Screen Layout & Engagement Parity

## Problem Frame

Analysis of a high-performing reference video ("Axios Just Got Attacked — 100 Million JavaScript Apps at Risk") revealed that the current pipeline produces a noticeably inferior viewer experience. The reference video uses full-screen b-roll during the body, cinematic stock footage, flat bold typography cards, and avatar only at hook + CTA — while the current pipeline overlays a talking-head avatar over compressed b-roll for the entire duration and uses dark-gradient headline cards that feel dated. The gap between the two is large enough to hurt retention and watch time at the current stage of the channel.

Five concrete gaps were identified:

1. Avatar fills the frame during body segments where b-roll should be full-screen
2. Avatar is generated for the full audio duration even though it appears for only ~6s total
3. `headline_burst` cards use dark gradients instead of flat bold typography matching the "did you know" card aesthetic
4. No stock/cinematic video b-roll type exists — all visual variety comes from screenshot Ken Burns and animated stat/headline cards
5. Browser screenshot capture grabs the full viewport instead of zooming to the densest content region

## Requirements

- R1. **Full-screen body layout**: During body segments (everything between hook and CTA), b-roll fills the entire 9:16 output frame. No avatar overlay. Avatar is composited only during the hook (~3s) and CTA (~3s).
- R2. **Short avatar generation**: The avatar clip requested from the generation service (VEED or fal) covers only hook + CTA seconds (≈6-8s total). The WIP placeholder continues to be generated for the full duration but the real-avatar path clips the request to the short window. This reduces generation cost by ~85-90% compared to full-duration requests.
- R3. **Flat-design `headline_burst` redesign**: Cards use a flat solid background color (no gradient), massive sans-serif typography (≥180px), high contrast (black on yellow, white on deep blue, black on white), and a subtle accent element such as a colored rule or block. The current gradient design is retired.
- R4. **`stock_video` b-roll type**: A new generator type that queries the Pexels video API for short cinematic clips (data center, code on screen, phone use, abstract tech) matching the segment topic. Clips are trimmed to the target duration and encoded to the pipeline's output spec. Added to the Claude Haiku timeline planner as an available type alongside `browser`, `stats_card`, and `headline_burst`.
- R5. **Content-crop browser screenshots**: After capturing each viewport screenshot, detect the bounding box of the article's main content column (excluding sidebars, headers, footers) and crop + zoom to that region before passing it to the Ken Burns renderer. Result should feel like a close-up on the text and images, not a shrunken full-page view.

## Success Criteria

- A smoke run produces a video where the full frame is filled by b-roll for every non-hook, non-CTA second
- Avatar generation cost for a 60s video drops from ~$6 to ≤$0.60 (real-avatar path)
- `headline_burst` cards visually match the flat bold card aesthetic of the reference video with no gradient visible
- At least one `stock_video` segment appears in a smoke run when the topic has matching Pexels results
- Browser b-roll clips feel zoomed-in and content-focused rather than showing the full browser viewport

## Scope Boundaries

- No changes to the audio/voiceover pipeline
- No changes to the short-form clip extraction logic
- The fal.ai avatar integration is not being built yet — this work targets the VEED path and the WIP placeholder path
- Stock video selection uses Pexels only (not Pixabay, Getty, etc.)
- No new AI video generation (Wan2.1 / ComfyUI) is introduced in this phase — stock video fills that role
- YouTube upload and social posting are out of scope

## Key Decisions

- **Full-screen body**: Avatar composite is dropped for body segments entirely rather than making it smaller/transparent, matching the reference video's approach where face time is earned (hook, CTA) and body is pure visual storytelling.
- **Short avatar**: Hook ≈ first 3s + CTA ≈ last 3s = 6s requested from avatar service. The pipeline passes timestamps to `step_avatar()` so it knows exactly which seconds need face coverage.
- **Flat cards over gradient**: The dark gradient aesthetic reads as 2022-era. Flat high-contrast color blocks are what dominates current TikTok/Reels top-performing edutainment.
- **Pexels video over AI generation**: Pexels free tier gives 200 requests/month; clips are real cinematic footage; no GPU cost or generation latency. AI video is a Phase 3 upgrade.
- **Content crop via DOM bounding box**: The article container's bounding box (already detected by `_FIND_POSITIONS_JS`) is reused to crop the screenshot — no additional DOM query needed.

## Dependencies / Assumptions

- Pexels API key available in `.env` (same key currently used by `ImageMontageGenerator` for photos — the video endpoint is on the same key)
- `ffmpeg` supports the `crop` and `scale` filters needed for content-region zoom (it does)
- Avatar service (VEED / fal) accepts a `duration` or `trim` parameter so short clips can be requested (needs verification for fal path; VEED supports it)

## Outstanding Questions

### Resolve Before Planning

_(none — all blocking product decisions resolved above)_

### Deferred to Planning

- [Affects R2][Technical] Confirm whether the fal.ai avatar endpoint supports requesting a specific duration or whether the clip must be trimmed client-side after generation
- [Affects R4][Needs research] Pexels video API response shape and rate limits — confirm the free tier allows enough requests for 3 videos/day
- [Affects R4][Technical] Decide the default fallback when Pexels returns zero results for a segment topic (fall back to `headline_burst`, skip the segment, or use a generic b-roll query)
- [Affects R5][Technical] Determine whether `_FIND_POSITIONS_JS` already returns a pixel bounding box suitable for crop, or whether a separate DOM measurement pass is needed

## Next Steps

→ `/ce:plan` for structured implementation planning
