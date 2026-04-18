---
title: "feat: YouTube Shorts as video meme source"
type: feat
status: active
date: 2026-04-16
origin: docs/brainstorms/2026-04-16-youtube-shorts-meme-source-requirements.md
---

# feat: YouTube Shorts as video meme source

## Overview

Add YouTube Shorts from curated tech comedy channels as a video meme source, replacing the ineffective general Reddit video subs. Uses existing YouTube API OAuth.

## Implementation Units

- [ ] **Unit 1: Create YouTubeShortsMemeSource**

**Files:**
- Create: `sidecar/meme_sources/youtube_shorts.py`
- Modify: `sidecar/meme_sources/__init__.py`
- Modify: `sidecar/config.py`

**Approach:**
- New class following MastodonMemeSource/RedditMemeSource pattern
- For each channel ID in config, get uploads playlist (UC→UU prefix swap), call `playlistItems.list`
- For each item, call `videos.list` to get duration + statistics
- Filter: duration <= 60s, viewCount >= threshold
- Return standard candidate dict (source, source_url, author_handle, title, media_url, media_type=video, engagement)
- `media_url` = YouTube video URL (yt-dlp downloads on publish)
- Config: `YOUTUBE_SHORTS_CHANNEL_IDS`, `YOUTUBE_SHORTS_MIN_VIEWS`, `YOUTUBE_SHORTS_MAX_AGE_DAYS`

- [ ] **Unit 2: Drop general video Reddit subs**

**Files:** `sidecar/config.py`, `sidecar/meme_sources/reddit_memes.py`, `sidecar/meme_sources/__init__.py`

**Approach:** Remove r/funny, r/TikTokCringe, r/maybemaybemaybe from defaults and registry.

- [ ] **Unit 3: Add yt-dlp download support in meme publish flow**

**Files:** `sidecar/jobs/meme_flow.py`, `sidecar/meme_pipeline.py`

**Approach:**
- In `_publish_blocking`: if `media_url` is a YouTube URL, use yt-dlp to download instead of `safe_fetch`
- yt-dlp is already in the pipeline_venv (`/opt/pipeline_venv/bin/yt-dlp`)
- Download to `run_dir/raw.mp4`, then normalize + overlay as usual

- [ ] **Unit 4: Deploy + test**

Rsync, rebuild, redeploy, trigger, verify YouTube shorts surface to Telegram.
