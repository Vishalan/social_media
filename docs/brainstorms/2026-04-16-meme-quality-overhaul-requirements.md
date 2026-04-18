---
date: 2026-04-16
topic: meme-quality-overhaul
---

# Meme Quality Overhaul — Only Top-Tier Funny Content

## Problem Frame

The meme pipeline surfaces too much mediocre and duplicate content to Telegram. The owner is seeing: (1) unfunny memes that waste review time, (2) off-brand content from non-tech subs, (3) repeated/similar suggestions across trigger runs, (4) too many previews to review. The current humor threshold (>= 3/10) is far too permissive, and the Qwen 3 8B local model produces binary scores (10 or 5) that make thresholds ineffective.

## Requirements

- R1. Raise humor + relevance thresholds to >= 7/10 — only genuinely funny, on-brand content reaches Telegram
- R2. Switch meme scoring back to Anthropic Haiku API — Haiku produces nuanced 0-10 scores while Qwen gives binary 10/5 ratings. The cost ($0.001/batch) is negligible vs the quality loss from bad scoring
- R3. Reduce Telegram surface limits to 2 images + 2 videos per trigger run (max 8/day across 2 runs)
- R4. Cross-run dedup: before surfacing to Telegram, check against candidates surfaced in the last 48 hours — skip anything with Jaccard title similarity >= 0.7 to a recently surfaced candidate
- R5. Keep Ollama/Qwen for topic ranking (where binary scoring is acceptable) — only meme scoring reverts to Haiku
- R6. Add more Reddit sources to increase the top-of-funnel — more candidates in means more survivors after strict filtering
- R7. Autopilot targets unchanged: 1 image + 2 videos per day auto-published

## Success Criteria

- Owner sees 3-4 previews per trigger run, all genuinely funny and on-brand
- Zero duplicate/similar suggestions within a 48-hour window
- Humor scores show clear gradient (not just 10 or 5) so thresholds actually filter
- Autopilot picks are content the owner would have approved manually

## Scope Boundaries

- Not changing the scoring prompt — the issue is model quality, not prompt quality
- Not adding new non-Reddit sources (Mastodon is already there)
- Not changing the publish/Postiz flow — only the scoring + surfacing layer

## Key Decisions

- **Revert meme scoring to Haiku API**: Qwen 3 8B's binary scoring defeats the purpose of quality filtering. Haiku costs ~$0.001 per batch of 30 items — negligible. Keep Qwen for topic ranking where nuance matters less.
- **Threshold 7/10 not 8/10**: 8 would be too strict and leave too few candidates. 7 means "this is actually funny" — the bottom drops off sharply below 7 in Haiku's scoring.
- **Cross-run dedup at 0.7 Jaccard (not 0.8)**: Looser than insert-time dedup because we want to catch thematic similarity ("same joke, different template") across runs, not just reposts.

## Outstanding Questions

### Deferred to Planning

- [Affects R6][Needs research] Which additional Reddit subreddits to add — need video-heavy tech subs with decent engagement
- [Affects R4][Technical] Whether cross-run dedup should compare against all recent candidates or only those that were surfaced to Telegram

## Next Steps

→ `/ce:plan` for structured implementation planning
