---
date: 2026-04-06
topic: thumbnail-engine
---

# Eye-Catching Thumbnail Engine

## Problem Frame

CommonCreed videos currently rely on whatever frame IG/YT/TikTok auto-pick as the cover — usually a mid-talk avatar frame with no topic context. Thumbnails are the single biggest CTR lever for shorts and YouTube; without an intentional, on-topic, branded cover, the pipeline is leaving most of its reach on the table. We need a generated thumbnail per video that (a) gets picked up as the cover on every platform we post to and (b) looks crazy good — punchy headline, avatar presence, on-topic visual.

## Requirements

- R1. **Per-video generated thumbnail.** Every video produces a 1080x1920 (9:16) thumbnail PNG saved alongside the final MP4, derived from the topic and script of that specific video.
- R2. **Picked up as cover on IG, YouTube, TikTok.** The thumbnail must become the actual cover/poster on every platform CommonCreed posts to. Delivery path is platform-aware:
  - **YouTube Shorts**: explicit thumbnail upload via YT Data API (through Postiz).
  - **Instagram Reels**: cover image upload via IG Graph API (through Postiz).
  - **TikTok**: TikTok's official API does NOT accept arbitrary cover images — only `video_cover_timestamp_ms`. Therefore the thumbnail must also be **baked into the video as a held first frame** (~0.5s), and Postiz is told to set the cover timestamp to 0.
- R3. **MrBeast-style tech-news look.** Bold 3-5 word headline, avatar portrait cutout, bright accent color, on-topic background image, strong contrast, readable at thumbnail size (test at 200px wide).
- R4. **Platform-safe composition.** Headline text and avatar face must live inside a center-safe zone: top 15% and bottom 20% of the 9:16 canvas are reserved for platform UI overlays, and the design must survive a 1:1 center crop (for IG grid view) without losing the headline or face.
- R5. **LLM-generated punchy headline.** Headline text is generated from the script (not the raw script hook line) — aim for 3-5 words, curiosity gap or bold claim, ALL CAPS friendly.
- R6. **On-topic background image.** Source from Pexels/article image already pulled by the b-roll pipeline. Apply darken/gradient overlay so headline text is always readable. Fallback to branded gradient if no usable image found.
- R7. **Avatar portrait cutout.** Use the existing `owner-portrait-9x16.jpg` with background removed, positioned to one side. Background removal cached (one-time per portrait) so it doesn't run per video.
- R8. **Seamless pipeline integration.** Thumbnail generation runs as a step in the existing video pipeline without disturbing avatar generation, b-roll, captions, or assembly. Failure to generate a thumbnail must not break the pipeline — fall back to a minimal text-only thumbnail.
- R9. **Cheap and fast.** Total added cost per video < $0.02. Total added time < 10 seconds. No GPU dependency.

## Success Criteria

- Every video in `output/` has a `*_thumbnail.png` (1080x1920) saved next to the final MP4
- Posted videos on IG Reels, YT Shorts, and TikTok all show the generated thumbnail as the cover (verified manually on first 3 posts)
- Thumbnails are visually compelling at 200px wide and survive 1:1 center crop — headline readable, avatar recognizable, topic obvious
- Pipeline run time grows by < 10s; cost grows by < $0.02
- No regression in avatar sync, captions, b-roll, or any existing video quality

## Scope Boundaries

- NOT generating multiple thumbnail variants for A/B testing (future work)
- NOT swapping the avatar portrait per video — same portrait every time, just with topic context around it
- NOT animated thumbnails or motion posters
- NOT building a thumbnail editor UI — fully automated
- NOT keeping Ayrshare as a posting dependency — replaced with self-hosted Postiz on Synology/Portainer

## Key Decisions

- **Posting layer = Postiz, self-hosted on Synology via Portainer**: Replaces Ayrshare. Postiz is the only well-maintained OSS multi-platform poster with a real REST API in the free tier, supports all required platforms (IG/YT/TT/X), uses official platform OAuth (no fragile browser automation), and runs in Docker on Synology comfortably (Postiz + Postgres + Redis, ~1-2GB RAM). License: AGPL-3.0, fine for self-hosted internal use.
- **Hybrid cover delivery, but driven by platform reality (R2)**: YT and IG accept explicit cover uploads via Postiz → use them. TikTok refuses arbitrary covers → bake the thumbnail as a held ~0.5s first frame in the video and pass `video_cover_timestamp_ms=0`. The "hold for 0.5s" duration is chosen so the encoder produces a clean keyframe and TikTok reliably grabs it; the 0.5s intro beat is an acceptable retention cost given that TikTok is otherwise un-coverable.
- **Bold text + avatar cutout style (R3)**: Tech-news shorts that win on IG/YT consistently use this formula. Minimal editorial looks premium but loses CTR; pure screenshot looks lazy. Going with the proven high-CTR format.
- **LLM-generated headline (R5)**: Use Claude Haiku (already in pipeline for b-roll planning) — adds < $0.001/video. Punchy 3-5 word headline beats reusing the script's first line, which is often a full sentence.
- **Pexels/article background (R6)**: Reuses existing b-roll image pipeline — zero new dependencies, free, already on-topic. AI-generated backgrounds (SDXL/Flux) are higher quality but reintroduce GPU dependency we just eliminated, and add cost + latency we don't need.
- **Avatar cutout cached (R7)**: Background removal is a one-time operation per portrait — cache the cutout PNG so we don't pay for it every video.
- **Pipeline-safe with fallback (R8)**: Thumbnail step is isolated and any failure degrades to a text-only fallback rather than breaking the pipeline. The avatar/b-roll/caption flow is working perfectly and must not regress.

## Dependencies / Assumptions

- **Postiz** deployed on Synology NAS via Portainer using official `docker-compose.yml`, reachable from the pipeline host over LAN, with API key configured
- Postiz REST API (`POST /public/v1/posts`) still exposes per-platform thumbnail fields for YT and IG (verify at integration time)
- Each social account (IG business, YT channel, TikTok creator, X) connected once via Postiz UI through official OAuth — TikTok and IG developer app approval may take days
- Pillow is available for compositing; `rembg` (or similar local CPU ONNX model) is acceptable for one-time portrait background removal
- Claude Haiku is already wired into the pipeline for headline generation
- Synology hardware is mid-range or better (DS920+/DS1522+ class) — low-end ARM units may not run Postiz comfortably

## Outstanding Questions

### Deferred to Planning

- [Affects R2][Needs research] Verify current Postiz API field names for per-platform cover/thumbnail upload (YT and IG) at integration time — the API has evolved across versions
- [Affects R2][Technical] How does the held 0.5s first frame interact with the existing avatar/b-roll assembly in `video_editor.py`? Is it prepended cleanly, or does it shift downstream timestamps that the avatar sync logic depends on?
- [Affects R7][Technical] `rembg` (local, free, ~2s) vs hosted bg-removal API — pick at planning time. Either way, cache the result.
- [Affects R3][Needs research] What font ships with the system that matches the bold tech-news look? (Inter Black, Anton, Bebas Neue are common — check what's available before planning.)
- [Affects R8][Technical] Where exactly does the thumbnail step slot into `pipeline.py` / `smoke_e2e.py` — after script generation (so headline can use script) and before final video assembly (so the held frame can be prepended)?
- [Affects Dependencies][Operational] Is the existing Synology hardware mid-range enough to run Postiz + Postgres + Redis, or does this need a different host?

## Next Steps

→ `/ce:plan` for structured implementation planning
