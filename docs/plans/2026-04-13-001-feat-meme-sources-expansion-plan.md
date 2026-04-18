---
title: "feat: Expand meme sources — on-brand Reddit subs + Mastodon"
type: feat
status: active
date: 2026-04-13
origin: docs/brainstorms/2026-04-13-meme-sources-expansion-requirements.md
---

# feat: Expand meme sources — on-brand Reddit subs + Mastodon

## Overview

Replace 3 off-brand general subreddits with 5 on-brand tech humor subs, and add Mastodon as a new source for original developer memes.

## Requirements Trace

- R1. Add 5 Reddit subs (linuxmemes, SoftwareGore, iiiiiiitttttttttttt, ProgrammingHorror, RecruitingHell)
- R2. Drop 3 off-brand subs (Unexpected, BetterEveryLoop, nextfuckinglevel)
- R3. New MastodonMemeSource class
- R4. Same candidate dict shape across all sources

## Implementation Units

- [ ] **Unit 1: Update Reddit sub config**

**Files:** `sidecar/config.py`, `sidecar/meme_sources/reddit_memes.py`, `sidecar/meme_sources/__init__.py`

**Approach:** Update `MEME_SOURCES`, `MEME_SUBREDDIT_MAP`, `_DEFAULT_SUBREDDITS`, and `_REGISTRY` — config-only changes, no new code.

- [ ] **Unit 2: Add MastodonMemeSource**

**Files:**
- Create: `sidecar/meme_sources/mastodon_memes.py`
- Modify: `sidecar/meme_sources/__init__.py` (register)
- Modify: `sidecar/config.py` (add `MASTODON_MEME_INSTANCES`, `MASTODON_MEME_HASHTAGS`, `MASTODON_MEME_MIN_ENGAGEMENT`)

**Approach:**
- GET `https://{instance}/api/v1/timelines/tag/{hashtag}?limit=40` — no auth needed
- Filter: must have media_attachments, engagement >= threshold
- Map `status.content` (HTML) → strip to plain text title
- Map `status.media_attachments[0].type` → image/video
- Engagement = favourites_count + reblogs_count

**Patterns:** Follow `RedditMemeSource` structure exactly.

- [ ] **Unit 3: Deploy + verify**

Rsync, rebuild, redeploy, run trigger, check Telegram previews.
