---
date: 2026-04-13
topic: meme-sources-expansion
---

# Expand Meme Sources — On-Brand Tech Humor + Mastodon

## Problem Frame

The meme pipeline currently scrapes 5 Reddit subreddits, but 3 of them (r/Unexpected, r/BetterEveryLoop, r/nextfuckinglevel) are general viral content — 80%+ gets filtered by the relevance scorer, wasting Ollama/API scoring calls and diluting the candidate pool. Meanwhile, high-quality on-brand tech humor subreddits and the Mastodon fediverse (free public API, original content) are untapped.

## Requirements

- R1. Add 5 on-brand tech humor subreddits: r/linuxmemes, r/SoftwareGore, r/iiiiiiitttttttttttt, r/ProgrammingHorror, r/RecruitingHell
- R2. Remove 3 off-brand subreddits: r/Unexpected, r/BetterEveryLoop, r/nextfuckinglevel
- R3. Add Mastodon as a new meme source — scrape `#programmerhumor`, `#devhumor`, `#techmemes` hashtags from fosstodon.org and hachyderm.io via public API (no auth needed)
- R4. Mastodon source returns the same candidate dict shape as Reddit sources (source, source_url, author_handle, title, media_url, media_type, engagement, published_at)

## Success Criteria

- Meme trigger surfaces more on-brand tech content (higher average relevance scores)
- Fewer wasted scoring calls on off-brand content
- Mastodon provides original content not duplicated from Reddit

## Scope Boundaries

- No Lemmy source (too low volume, significant Reddit overlap)
- No Imgur/9GAG/Twitter (require paid API or fragile scraping)
- No changes to scoring, publishing, or Telegram preview logic

## Key Decisions

- **Drop off-brand subs rather than keep them**: They consume scoring capacity but 80%+ gets filtered. The humor scorer runs on every candidate — fewer low-relevance candidates means faster scoring and less GPU/API usage.
- **Mastodon instances: fosstodon.org + hachyderm.io**: Largest tech-focused Mastodon instances with active developer communities. Public API, no auth, generous rate limits (300 req/5min).
- **Mastodon engagement = favourites_count + reblogs_count**: Equivalent to Reddit score for ranking/filtering purposes.

## Outstanding Questions

### Deferred to Planning

- [Affects R3][Technical] Mastodon posts use `content` (HTML) not `title` — need to strip HTML to extract a title for the Telegram preview and dedup
- [Affects R3][Technical] Mastodon media attachments may be images or video — map `type` field to our `media_type` enum
- [Affects R3][Needs research] Minimum engagement threshold for Mastodon (equivalent of REDDIT_MEME_MIN_SCORE=500) — Mastodon engagement numbers are much lower than Reddit

## Next Steps

→ `/ce:plan` for structured implementation planning
