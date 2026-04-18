---
date: 2026-04-16
topic: youtube-shorts-meme-source
---

# YouTube Shorts as Video Meme Source

## Problem Frame

The meme pipeline has no reliable source of funny tech videos. Reddit tech subs are 95% images. General video subs get filtered by relevance. YouTube Shorts from channels like Fireship, KRAZAM, Joma Tech, and ThePrimeagen are the primary home of genuinely funny tech video content — and we already have YouTube API OAuth.

## Requirements

- R1. New `YouTubeShortsMemeSource` class that fetches recent shorts from a curated list of funny tech channels
- R2. Uses YouTube Data API v3 (existing OAuth credentials) via `playlistItems.list` (1 unit/call, cheap)
- R3. Filters to videos under 60 seconds with vertical aspect ratio
- R4. Returns same candidate dict shape as Reddit/Mastodon sources
- R5. Channel list configurable via `.env` (`YOUTUBE_SHORTS_CHANNEL_IDS`)
- R6. Drop general video Reddit subs (r/funny, r/TikTokCringe, r/maybemaybemaybe) — they waste scoring calls on non-tech content
- R7. Engagement = view count for scoring/ranking (YouTube doesn't expose likes via basic API)

## Success Criteria

- Trigger surfaces 1-2 genuinely funny tech video shorts per run
- Videos are original content from known tech comedy creators
- No API quota issues (channel-based fetching uses 1 unit/call vs 100 for search)

## Scope Boundaries

- Channel-based fetching only — no hashtag search (saves quota)
- No TikTok source (deferred — YouTube covers video needs first)
- Not downloading/hosting the videos — just surfacing them for approval, pipeline downloads on publish

## Key Decisions

- **Channel-based over hashtag search**: `playlistItems.list` costs 1 quota unit vs `search.list` at 100. With 15-20 channels, each daily fetch costs ~20 units vs 2000+.
- **Curated channel list**: Quality over volume. Hand-picked channels that consistently produce funny tech content.
- **Drop general video Reddit subs**: r/funny, r/TikTokCringe, r/maybemaybemaybe waste Haiku scoring calls — 100% of their content gets relevance-filtered. YouTube Shorts replaces their role.

## Seed Channel List

| Channel | Why | Content type |
|---------|-----|-------------|
| Fireship | Dry humor tech explainers, meme-format takes | High volume shorts |
| KRAZAM | Sketch comedy: microservices, Kubernetes, standups | Medium, high quality |
| Joma Tech | Developer life comedy, startup satire | Medium |
| ThePrimeagen/ThePrimeTime | Reaction clips to bad code, hot takes | High volume |
| cassidoo | Quick coding jokes, relatable dev skits | Cross-platform |

## Outstanding Questions

### Deferred to Planning

- [Affects R1][Technical] How to get the "uploads" playlist ID from a channel ID (YouTube convention: replace "UC" prefix with "UU")
- [Affects R3][Technical] How to detect vertical aspect ratio from API response (player embed dimensions or contentDetails)
- [Affects R7][Technical] Whether to use `statistics.viewCount` or `statistics.likeCount` for engagement scoring — likeCount may require additional API scope

## Next Steps

→ `/ce:plan` then `/ce:work`
