# Idea: Parallel Content Scraper & Curation Pipeline

## 1. Problem & opportunity

The existing CommonCreed pipeline (`daily_trigger` → `topic_sources/*` → script → voice → b-roll → avatar → assembly → Postiz) is **generative**: it reads a topic and produces a brand-new video around it. That model is slow (~6–8 minutes of compute per clip), expensive (Claude + ElevenLabs + fal.ai + Whisper per run), and opinionated (every clip looks like a CommonCreed clip).

The channel's best-performing content historically was **curated**, not generated:

- @commoncreed Instagram Reels that reshared tech memes, short-form founder content, viral lab demos, and "wait, really?" tech news clips
- Each curated post credited the original source and rode the momentum of content already validated by someone else's audience

We should run a **parallel curation track** alongside the generative one, feeding the same approval → Postiz → peak-hour schedule machinery we already built. Two tracks, same rails — the owner reviews both in Telegram and decides.

**The goal is not to replace the generative pipeline.** It is to supply a second stream of lower-cost, higher-signal content that can fill the gaps between long-form generated clips and keep the account active every day.

## 2. Scope boundaries

**In scope for v1:**

- Scrape 5–8 trending-content sources on a cron (separate from `daily_trigger`)
- Classify + rank candidate items against a content policy (see §5)
- Surface the top N candidates in Telegram for human approval, same way generated clips do today
- On approval, download the media, normalize it to IG Reels / YouTube Shorts specs, overlay CommonCreed branding per the credit policy (§7), and push to Postiz with peak-hour scheduling
- Attribute every post to the original creator in-caption and via IG Collab tag when the platform allows

**Not in scope for v1:**

- Fully autonomous posting (everything still goes through the Telegram approval flow — no "YOLO" mode)
- Copyright adjudication or DMCA response workflow (we operate under fair-use / credit-based rules, nothing more)
- Paid API integrations for any source where a free/public tier exists
- Cross-posting curated content to platforms other than IG and YT (X/TikTok come in a later phase)
- Any form of re-uploading full copyrighted videos — only short clips (< 30s) with transformation/credit

**Explicit non-goals:**

- We do **not** want to become a meme aggregator that reposts everything. Curation means saying *no* to most of what we see.
- We do **not** want to automate the final "post or don't post" decision. The owner reviews every single curated item the same way they review generated ones.
- We do **not** want curated content to compete with generated content in the same slot. The scheduler should balance the two streams across the week (§9).

## 3. Success criteria

| Metric | Target for v1 |
|---|---|
| Sources wired | ≥ 5 (Reddit, HN, YouTube trending, Instagram hashtag/creator list, X trending tech) |
| Candidates surfaced per day | 10–20, filtered down to top 3–5 for Telegram review |
| Owner time to review all candidates | < 5 minutes (one Telegram message per candidate, swipe to approve/reject) |
| Credit accuracy | 100% of posted items carry a working link + @handle to the original creator |
| Platform account strikes | 0 — if any strike is received, pause the specific source and review the policy |
| Engagement lift vs generated baseline | To be measured after 2 weeks — no hard target yet, but we want to see whether curated clips outperform generated on the same account |

## 4. Sources (v1)

Each source is a module under `sidecar/content_sources/` implementing a new `ContentSource` protocol (sibling to the existing `TopicSource` protocol in `sidecar/topic_sources/`). We keep topic sources and content sources separate because they return fundamentally different things:

- **`topic_sources`** return `{title, url, summary}` → drive the generative pipeline
- **`content_sources`** return `{media_url, caption, author_handle, author_name, source_url, media_type, engagement_signals}` → drive the curation pipeline

### 4a. Reddit

- Target subreddits: `r/programming`, `r/MachineLearning`, `r/LocalLLaMA`, `r/artificial`, `r/singularity`, `r/coding`, `r/webdev`, `r/technews`, `r/ProgrammerHumor` (for meme content)
- API: Reddit JSON endpoints (no auth required for public listings). Example: `https://www.reddit.com/r/LocalLLaMA/top.json?t=day&limit=25`
- Extract: post title, permalink, score, over_18 flag, media (preview.images[0].source.url for static, secure_media.reddit_video.fallback_url for native video)
- Filter: skip NSFW, skip text-only posts (no media), skip posts below a per-subreddit min score threshold
- Credit: username + subreddit + permalink

### 4b. Hacker News (beyond the existing topic source)

- The existing `HackerNewsTopicSource` in `sidecar/topic_sources/hackernews_source.py` already queries the Firebase API for title+url. Here we extend: if the HN post is a discussion of a Twitter thread, GitHub demo, YouTube video, or blog post with good media, treat it as a candidate for curation instead of script generation.
- Add a second classifier pass: "does this HN story link to something visually interesting that we could reshare?" If yes, pull it into the content track. If no, leave it in the topic track for generative scripting.

### 4c. Y Combinator / Startup showcases

- YC Demo Day is seasonal; the rest of the year this feed is mostly empty. Still worth having:
  - `https://www.ycombinator.com/companies?batch=...` launch posts
  - `https://www.producthunt.com/feed.atom` — trending product launches as RSS
- Extract: launch name, tagline, founder handles, launch video (if the launch page embeds one), product screenshot
- Filter: tech/AI/dev-tool products only — no consumer, no lifestyle

### 4d. Instagram — hashtag & creator list

- Meta Graph API via Postiz's existing integration: query hashtag recent media, or query a specific creator's recent posts
- Target creators: build a seed list in `sidecar/content_sources/instagram_creators.json` — 20–50 tech/AI creators whose content fits the channel
- Target hashtags: `#techmemes`, `#aitools`, `#coding`, `#developer`, `#llm`, `#artificialintelligence` (hashtag targeting has been deprecated by Meta in recent API versions — if that's true for our access tier, fall back to creator-only)
- Extract: media_url, permalink, caption, username, engagement count (likes + comments + shares)
- **Fair use constraint**: never download and re-upload the full media. Instead, our pipeline records the metadata and surfaces it to the owner. On approval, we either:
  - **Option A** (preferred when available): use the native IG Reshare feature via Postiz (if supported) — this keeps the original post's attribution intact
  - **Option B**: download a trimmed 5–15s segment, add a visible credit overlay, and post as a new Reel with `Credit: @handle` in the caption
  - Option A is always preferred because it preserves the creator's engagement and respects Meta's terms. Option B is a fallback for creators who opt out of Reshare.
- Credit: @username + IG Collab tag + link to original post in bio

### 4e. X (formerly Twitter)

- Target lists: one or more X Lists of tech/AI accounts (list IDs stored in env or settings). A List is a curated feed and doesn't require scraping the whole platform.
- API: X API v2 with bearer token (read-only tier is sufficient for list timelines and media)
- Extract: tweet text, media URLs, author handle, like/retweet counts, tweet permalink
- Filter: text-only tweets skipped unless they're a short, punchy, quote-worthy statement from a known tech figure (then treat the tweet-as-image as the media)
- Credit: @handle + link to original tweet in caption; no IG Collab equivalent so captions have to carry the attribution clearly

### 4f. YouTube trending + channel subscriptions

- YouTube Data API v3 (already authed for our upload flow)
- Two queries per run:
  1. `videos.list?chart=mostPopular&videoCategoryId=28` (Category 28 = Science & Technology)
  2. `playlistItems.list` over a seed list of tech YouTube channels (Fireship, ThePrimeagen, Marques Brownlee, Linus Tech Tips, etc.)
- Extract: title, thumbnail, channel, duration, view count, published_at
- **Critical**: we never re-upload YouTube videos. We either (a) surface a "watch this" post that links to the video and uses only the thumbnail + a few seconds of b-roll-style preview, or (b) build a CommonCreed reaction/reshare script around the topic (which then feeds the generative track instead of the curation track)
- Credit: channel name + full video URL in description

### 4g. Tech newsletter digests (Gmail — reuses the topic source layer)

- The existing `GmailTopicSource` pulls TLDR for the generative track. Here we add a second classifier over the same data: which TLDR items have a visual element worth resharing (linked GIF, embedded video, screenshot-heavy GitHub README)?
- Feed those into the curation track instead of the generative track.

## 5. Engagement criteria for "post-worthy"

Every candidate runs through a scoring pass before reaching the top-N cut. Score is the weighted sum of:

| Signal | Weight | Measured via |
|---|---|---|
| **Topical fit** — does it belong on an AI/tech channel? | 0.30 | Claude classifier over title + source metadata; rejects off-topic immediately |
| **Novelty** — not something we've already posted in the last 30 days | 0.20 | `duplicate_guard` URL + title similarity check (same one we already use for generated runs) |
| **Engagement proxy** — normalized score on the source platform | 0.20 | Reddit score / HN points / IG likes-per-hour / X likes — normalized per source so a viral HN post doesn't dominate a quiet Reddit day |
| **Creator quality** — is the source a known/trusted creator or a throwaway? | 0.15 | Allowlist / blocklist maintained in `sidecar/content_sources/creators.json`; unknown creators get neutral weight |
| **Media fit** — is the media usable for Reels/Shorts (aspect ratio, length, no watermark conflicts)? | 0.10 | FFmpeg probe + heuristics |
| **Safety** — no NSFW, no gore, no politically inflammatory content, no personal attacks | 0.05 | Hard filter (if it fails, score is zero and the item is dropped) |

The scoring function lives in `sidecar/content_curation/scorer.py` and is deliberately hand-tunable — we do NOT want this to be a black-box ML model for v1. The owner should be able to read the scoring function, tweak a weight, and see the effect on tomorrow's candidates.

A "post-worthy" candidate is one that clears a minimum total score (tunable, starts at 0.60) AND passes the safety filter. Anything else is dropped silently (not surfaced in Telegram at all).

## 6. Architecture

```
sidecar/
├── content_sources/                 NEW — sibling to topic_sources/
│   ├── __init__.py                  Registry: reddit, hn, yc, ig, x, yt, gmail
│   ├── base.py                      ContentSource protocol
│   ├── reddit_source.py
│   ├── hackernews_source.py
│   ├── ycombinator_source.py
│   ├── instagram_source.py
│   ├── x_source.py
│   ├── youtube_source.py
│   └── gmail_source.py              Reuses GmailTopicSource; classifier split
│
├── content_curation/                NEW
│   ├── __init__.py
│   ├── scorer.py                    Hand-tunable scoring function (see §5)
│   ├── classifier.py                Claude-backed topical fit + safety check
│   ├── media_probe.py               FFmpeg probe: aspect ratio, duration, codec
│   ├── credit.py                    Caption templating with creator credits (§7)
│   └── media_normalizer.py          FFmpeg pipeline: crop to 9:16, trim to 15s, overlay credit
│
├── jobs/
│   └── curation_trigger.py          NEW — sibling to daily_trigger.py
│       Runs on its own cron (e.g. 06:00 and 18:00 IST), iterates enabled
│       content sources, scores all candidates, inserts top N into a new
│       `curation_candidates` table, triggers Telegram preview
│
└── db.py                            NEW table: curation_candidates
                                     Columns: id, source, source_url, media_url,
                                     author_handle, caption, score, created_at,
                                     status (pending/approved/rejected/published)
```

The Telegram preview reuses the existing `send_approval_preview` machinery from the generative track — same thumbnail + clip + caption + Approve/Reject buttons, just a different `runs`-like row type behind it. We add a new approval type (`curation`) alongside the existing `generation` type.

On approval:
1. `media_normalizer` downloads the source media and normalizes it
2. `credit.overlay_text()` adds a visible credit burn-in ("Credit: @handle" in the bottom-left, small, permanent)
3. `caption.build()` produces the Postiz caption with: our own intro line + `Credit: @handle on <source>` + source URL + hashtags
4. The `PostizClient.publish_post` call we already have is used unchanged — curation posts flow through the same peak-hour scheduling, same IG/YT integration IDs, same compute_next_slot logic

## 7. Credit & community-guidelines policy

This is a hard policy, not a guideline. Every curated post must:

1. **Name the original creator** in the first line of the caption (e.g. `via @username on Instagram`)
2. **Link to the original post** in the caption or comment (platform-dependent — IG caption URLs are non-clickable but still visible; on YT Shorts we put the link in the description)
3. **Tag the creator as a Collaborator** on Instagram when technically possible (the `InstagramDto.collaborators` field we already use for @vishalan.ai cross-tagging)
4. **Burn a visible credit overlay** into the video (bottom-left, 16px, white text with black shadow, positioned so it can't be cropped out easily)
5. **Never claim authorship** — our own caption copy must be framed as commentary/reshare, not as original creation
6. **Transform meaningfully** — we either trim a clip to the single most interesting moment, add our own framing/commentary text overlay, or pair it with our CommonCreed branding. A raw repost with no transformation is not allowed even with credit.
7. **Honor opt-outs immediately** — if a creator DMs or comments asking us to remove a post, we remove it within 24 hours. Maintain a denylist in `sidecar/content_sources/creators.json` so the same creator is never scraped again.
8. **Never pretend a creator endorsed CommonCreed** — the credit line is pure attribution, not endorsement language.

Caption template (stored in `sidecar/content_curation/credit.py`):

```
{our_intro_line}

🎥 via @{author_handle} on {source_platform}
🔗 {source_url}

{hashtags}
```

Example:

```
Wait — this Cursor demo is actually wild 👀

🎥 via @ericzakariasson on X
🔗 https://x.com/ericzakariasson/status/...

#commoncreed #cursor #aitools #coding #devtools
```

## 8. Safety filter (hard rejection)

Before a candidate reaches the scorer, it runs through a hard filter. Failing any of these means the candidate is dropped silently and never reaches Telegram:

- NSFW flag on source platform (Reddit `over_18`, IG flagged, X sensitive)
- Gore / self-harm / violence keywords in title or caption (Claude classifier)
- Political content — defined narrowly as: partisan attacks, election-related claims, content about specific living politicians. General policy commentary (e.g. "EU AI Act passed today") is allowed under the topic track, not the curation track.
- Personal attacks on named individuals
- Medical or financial advice framed as fact
- Copyright-claimed content (if the source platform's API tells us the item has a copyright claim on it, skip)
- Creator is on the denylist

The filter is implemented in `sidecar/content_curation/classifier.py` using a short Claude Haiku call per candidate. Cost is negligible (~$0.0001 per item at current Haiku pricing), latency is ~1-2s which is fine for a non-realtime batch job.

## 9. Scheduling across the two tracks

The generative track produces ~1 video per day. The curation track can realistically produce 2–4 candidates per day. We do NOT want to flood the feed.

Proposed rhythm:

- Generative: **1 post per day** at the evening slot (19:00 IST) — long-form commentary clips
- Curation: **1–2 posts per day** at morning (09:00 IST) and optionally lunch (13:00 IST) — short reshares
- When both tracks produce a candidate for the same slot, the scheduler prefers curation for morning and generative for evening. The owner can override in Telegram.

Slot assignment lives in the existing `compute_next_slot` in `sidecar/jobs/publish.py`. We extend it to take a `track` parameter (`"generation"` or `"curation"`) and return the track-appropriate next slot.

Weekly cap: no more than 10 posts per week per platform. If we'd exceed that, drop the lowest-scoring candidate of the week. This cap protects against accidental spam and keeps the account within IG's "safe" posting frequency.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| IG flags the account for copyright/repost behavior | Strict credit policy (§7), transformation requirement, IG Collab tag preferred over download-and-reupload, creator denylist honored on first complaint |
| Reddit / X API rate limits or tier changes | Each source is its own module; we can disable an individual source via env flag without touching the rest. Build in exponential backoff + daily fetch cap per source. |
| Claude classifier misses a safety-violating item | Hard filter is a pre-scorer, not the only line of defense — the owner still reviews every single candidate in Telegram before anything gets posted. |
| Curated content drowns out generated content | §9 explicit caps; weekly cap enforced by the scheduler; track-split slot assignment |
| Creator asks for removal and we don't notice | Opt-out inbox: a dedicated email (`optout@commoncreed.in` or similar) + a weekly job that scans IG DMs for the keyword "remove" and alerts the owner via Telegram |
| Scoring weights drift from what actually works | Log every posted curation item with its score + 7-day post-hoc engagement. Review monthly. Adjust weights in `scorer.py`. |

## 11. Implementation plan (rough sequencing)

This is just a sketch — an actual `/ce:plan` pass should refine it.

1. **New `ContentSource` protocol + registry** (sibling to `TopicSource`)
2. **Reddit source first** — free API, no auth, fastest to prove the end-to-end flow
3. **`curation_candidates` table + db helpers** — mirror `pipeline_runs` but for curation items
4. **`curation_trigger` job + APScheduler wire-up** — gated behind `SIDECAR_CURATION_TRIGGER_ENABLED` the same way `daily_trigger` is (§task 51)
5. **Scorer + classifier** — implement §5 and §8 against real Reddit output
6. **Telegram preview extension** — new approval type `curation` alongside `generation`
7. **Media normalizer + credit overlay** — FFmpeg pipeline, unit tested against a few known clips
8. **Postiz publish path for curation posts** — reuse `PostizClient.publish_post`, only the caption builder changes
9. **Second source: Hacker News extension** — fork the existing `HackerNewsTopicSource` logic
10. **Third source: YouTube (read-only reshare)** — reuse existing YT OAuth
11. **Fourth source: X list** — get a bearer token, target one tech list
12. **Fifth source: Instagram hashtag/creator** — requires Meta Graph permissions for content_publish on the scraping side, which we already have for posting
13. **Dashboard view** — extend the sidecar dashboard with a "Curation" tab showing pending/approved/rejected/published candidates per source
14. **Post-hoc engagement logger** — 7 days after each curation post, fetch engagement counts via Postiz analytics and log back to `curation_candidates` for scoring review
15. **Monthly scoring review** — cron job that produces a summary report (via Telegram) of which sources / which scoring weights correlated with the highest engagement

## 12. Open questions (resolve during `/ce:plan` or first implementation unit)

- **Which X List(s)** should the X source target? Needs the owner to curate 1–3 list IDs.
- **Which Instagram creators** go on the seed list? Needs an initial 20-creator list from the owner.
- **Do we want a unified "candidate" table** holding both generation runs and curation candidates, or keep them in separate tables? (Separate is cleaner for v1; merging later is easy if the flow converges.)
- **Should curation posts also hit the Telegram preview** with a 10s clip like generated ones? For static media (Reddit images, tweet screenshots) the clip idea doesn't apply — we'd just send the image. Need to extend `send_approval_preview` to handle static-image candidates.
- **Credit overlay rendering**: do we use moviepy (already in the pipeline venv) or raw ffmpeg? moviepy is slower but we already have it; raw ffmpeg is lighter but adds complexity.
- **Weekly engagement logger** needs Postiz analytics support — verify whether `/api/public/v1/posts/:id/analytics` exists in the current Postiz build.
- **Opt-out inbox**: email vs IG DM polling vs a public Google Form — pick one, wire it up, document it in the channel bio.

## 13. References

- Existing generative pipeline: `docs/plans/2026-04-06-002-feat-end-to-end-pipeline-plan.md`
- Existing topic source abstraction: `sidecar/topic_sources/` (for the architectural pattern to mirror)
- Existing Postiz publish path: `sidecar/jobs/publish.py` + `sidecar/postiz_client.py`
- Past performance reference: @commoncreed Instagram Reels (<https://www.instagram.com/commoncreed/reels/>) and main feed (<https://www.instagram.com/commoncreed/>)
- IG terms relevant to reposting: <https://help.instagram.com/581066165581870> (sharing other people's content)
- Reddit API docs: <https://www.reddit.com/dev/api>
- X API v2 docs: <https://developer.x.com/en/docs/x-api>
- YouTube Data API docs: <https://developers.google.com/youtube/v3>
- HN Firebase API: <https://github.com/HackerNews/API>
- Product Hunt RSS: <https://www.producthunt.com/feed>

## 14. Next step

When ready to move this from idea to plan:

```
/ce:brainstorm  # if any of the open questions in §12 need to be resolved first
/ce:plan        # otherwise go straight to a structured implementation plan
```
