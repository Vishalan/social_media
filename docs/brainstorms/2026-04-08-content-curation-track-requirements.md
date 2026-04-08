---
date: 2026-04-08
topic: content-curation-track
---

# CommonCreed Content Curation Track

## Problem Frame

The existing CommonCreed pipeline is purely **generative**: every post is a brand-new Claude-scripted, ElevenLabs-voiced, avatar-driven video built from scratch around a topic. That model is slow (~6-8 min compute per clip), expensive (per-run Anthropic + ElevenLabs + fal.ai + Whisper cost), and produces one long-form-style clip per day.

The channel's historical best-performing content was **curated**, not generated — Reels that reshared tech memes, viral demos, founder content, and "wait, really?" tech news clips, credited back to the original creator. Those posts rode momentum that was already validated by someone else's audience, and they were cheap to produce.

We want a **parallel curation track** running alongside the existing generative track. Both feed the same Telegram approval → Postiz → peak-hour publishing rails we built for the generative track this week. The goal is not to replace the generative pipeline; it is to supply a second, cheaper, higher-signal stream of content that keeps the account active multiple times per day and reintroduces the curated-content formula that drove earlier traction.

## Requirements

- **R1.** A scheduled curation trigger runs daily and fetches candidate content from every enabled content source. The trigger is gated behind an env flag (off by default) the same way `daily_trigger` is.
- **R2.** Eleven content sources are supported in v1, grouped into three waves: **Wave 1** (Reddit, Hacker News extended, GitHub Trending, Hugging Face trending), **Wave 2** (Substack RSS pool, arXiv cs.AI / cs.CL, Lobste.rs, Product Hunt), **Wave 3** (Instagram creator list, X list, YouTube trending tech). Waves 4–5 (Bluesky, Mastodon, Telegram channels, TikTok) are explicit future-scope.
- **R3.** Every candidate passes a hard safety filter (NSFW, gore, political partisan content, personal attacks, copyright claims, denylisted creators) before reaching the scorer. Failures are dropped silently and never surface anywhere.
- **R4.** Every surviving candidate is scored by a hand-tunable function combining topical fit, novelty (vs the last 30 days of posted items), source engagement, creator quality, media fit, and safety. The scoring function is plain Python, not ML — readable, editable, no black box.
- **R5.** The top candidates per day are surfaced in Telegram to the owner: one message per candidate, thumbnail or preview clip, caption draft, Approve/Reject/Edit buttons. Same machinery as the existing generative approval flow.
- **R6.** Target daily Telegram review volume is **10 candidates surfaced**, threshold around 0.60, with an expected ~30% owner approval rate yielding **3 posts/day**.
- **R7.** Target posting volume is **1 generative + 3 curated posts per day**, 7 days per week, capped at **20 posts/week per platform**. Weekly cap is enforced by the scheduler; the lowest-scoring candidate of the week is dropped if we'd exceed it.
- **R8.** Slot allocation: generative posts fire at the evening peak slot (19:00 local); curated posts fire at the three remaining daily peak slots (morning ~09:00, lunch ~13:00, evening slot 2 ~21:00). Exact slot times come from existing sidecar settings.
- **R9.** If the owner does not review a candidate before T-2 hours from its scheduled slot, the sidecar sends a **Telegram warning alert** listing the number of unreviewed candidates and the time until the slot fires.
- **R10.** If the owner still has not reviewed by T-30 minutes, the sidecar **auto-approves the highest-scored unreviewed candidate** that also satisfies both: (a) score ≥ 0.70, and (b) source is on the trusted-source allowlist (see R11). Candidates that fail either rule are never auto-posted; the slot is skipped instead.
- **R11.** A **trusted-source allowlist** is maintained in config and starts with: Hacker News, Hugging Face trending, arXiv, Product Hunt, Lobste.rs, and Ben's Bites Substack. Everything else (Reddit, Instagram, X, YouTube, random Substacks, random subreddits) requires human review and never auto-posts.
- **R12.** Every posted curated item carries: (a) a visible burned-in credit overlay naming the original creator, (b) a caption that leads with `via @handle on <platform>`, (c) a link to the original source in the caption or description, and (d) an Instagram Collab tag on the original creator when Instagram technically allows it.
- **R13.** No curated item is posted as a raw repost. Every post must transform the source in at least one meaningful way: trimming to the most interesting moment, adding CommonCreed commentary text, or pairing with CommonCreed branding. Pure copy-paste reshares are not allowed even with credit.
- **R14.** An **opt-out system** with **three inbound channels** is operational before the first curated post goes live:
  - **R14a.** A dedicated email alias (e.g. `optout@commoncreed.<domain>`) that the sidecar polls on a schedule and alerts the owner via Telegram on any inbound mail.
  - **R14b.** Instagram DM polling that scans `@commoncreed`'s DMs for opt-out keywords and flags matches for owner review.
  - **R14c.** A public Google Form linked from the IG bio and YouTube About page, submissions polled hourly.
  All three channels feed one unified denylist. When a creator is added to the denylist, any already-published posts from that creator are removed within 24 hours, and the creator is never scraped again.
- **R15.** Curation runs, candidates, scores, approval decisions, and post-publish engagement metrics are all persisted so the scorer can be tuned over time against real outcomes.
- **R16.** The sidecar dashboard gains a **Curation** view showing per-source candidate counts, pending reviews, recently-approved items, and denylisted creators.

## Success Criteria

- Curation track ships with all 11 Wave 1-3 sources wired and at least one candidate surfaced per source per week.
- Owner reviews 10 candidates/day in Telegram and taps Approve on ~3 of them; ≤ 5 minutes/day of review time.
- 100% of posted curated items carry a working credit link + creator handle + burned-in overlay. Zero posts go live without a named creator.
- Zero platform strikes in the first 90 days (IG, YT). Any strike pauses the corresponding source and triggers a policy review.
- On days the owner is completely offline, the autopilot posts at least 1 curated item from a trusted source, never auto-posts from Reddit/IG/X/YT/random Substack, and never skips more than 1 slot in a row.
- After 2 weeks of operation, per-post engagement on curated items can be compared to generated items side-by-side from the same account to validate whether curation actually performs better (as the pre-automation data suggested it did).

## Scope Boundaries

- **In scope for v1:** 11 content sources (Waves 1-3), scorer + classifier, media normalizer + credit overlay, Telegram approval reuse, Postiz publish reuse, T-2h warning + T-30min autopilot, trusted-source allowlist, 3-channel opt-out, dashboard curation view, engagement logger.
- **Future-scope (Wave 4):** Bluesky, Mastodon, Telegram channel scraping.
- **Future-scope (Wave 5):** TikTok. Revisit only if Waves 1-4 don't produce enough candidates.
- **Explicitly NOT in scope:** Full autonomous posting without a human-in-the-loop default. Copyright adjudication or DMCA response workflow. Cross-posting curated content to X or TikTok in v1 (IG + YouTube only). Re-uploading full copyrighted videos untrimmed and untransformed. ML-based scoring (hand-tuned only for v1).
- **Explicit non-goals:** Becoming a meme aggregator that reposts everything. Replacing the generative track. Competing with curated content in the same slot as generated content.

## Key Decisions

- **Full parallel pipeline over surface-only assistant** — the owner chose the full scraper → scorer → normalizer → overlay → Postiz publish flow instead of a lighter "surface candidates in Telegram, manually repost" assistant. Rationale: manual reposting doesn't scale past a couple posts per day, and the aggressive growth target (20/week) demands automation.
- **Build all 11 sources in v1, not a phased 1-source MVP** — the owner explicitly overrode the "start with 1 source" recommendation and asked for Waves 1-3 as must-have. Implementation will still ship Wave 1 first and stabilize before Wave 2, but all three waves are part of v1 success criteria.
- **Aggressive growth mode (20 posts/week)** — owner chose this over conservative (10/week) or weekday-only. Implies stricter opt-out infra (three channels, not one) and the T-2h/T-30min autopilot behavior.
- **All three opt-out channels from day 1** — email alias + IG DM polling + public Google Form, feeding one denylist. Rationale: aggressive posting + 11 sources = creator complaints are a when-not-if, and single-channel misses them.
- **Balanced funnel (10 candidates/day → 3 posts)** — scoring threshold starts at 0.60, with the sidecar tracking approval rate for future tuning.
- **Auto-approve with safety floor, not blind** — autopilot kicks in only at T-30min, only on candidates with score ≥ 0.70, only from trusted sources. A T-2h warning fires first to give the owner a chance to intervene. Low-signal days may legitimately skip a slot.
- **Credit policy is a hard rule, not a guideline** — 8 non-negotiable rules from the original idea doc §7 (name creator, link, IG Collab tag, burn-in overlay, no authorship claim, meaningful transformation, 24h opt-out honor, no fake endorsement) carry forward verbatim.

## Dependencies / Assumptions

- **Credential prerequisites blocking Wave 3:**
  - Instagram requires Meta Graph API read permissions for hashtag / creator media queries. We already have posting perms but not scraping perms; an App Review extension may be needed.
  - X requires a bearer token from the X Developer platform (free tier is sufficient for read-only list timelines).
  - YouTube read-access is already wired via the existing Postiz OAuth client.
- **Opt-out email domain:** A domain needs to own the `optout@...` alias. If `commoncreed.in` (or similar) is not yet owned, a forwarding rule via Cloudflare Email Routing or Gmail alias is acceptable.
- **Existing infrastructure reused unchanged:** `PostizClient.publish_post`, `send_approval_preview`, `compute_next_slot`, the `PIPELINE_SLOT_*` env vars, and the APScheduler persistent jobstore. Curation track is additive, not a refactor.
- **All curated content is in English** for v1. Non-English sources (arxiv cs.AI can include translations but that's edge case) are not filtered specifically, but the scorer assumes English-shaped captions.
- **Sidecar has sufficient capacity** on the NAS: the curation track adds roughly one ffmpeg normalization + credit overlay render per approved post. Each render is ~5-15 seconds of CPU. Three renders/day is negligible compared to the generative pipeline's ~8-minute per-run cost.

## Outstanding Questions

### Resolve Before Planning

*(None — all blocking product decisions are resolved.)*

### Deferred to Planning

- **[Affects R2][User decision + needs ongoing maintenance]** Which specific X Lists should the X source target? Owner will supply 1-3 list IDs during or after Wave 3 implementation.
- **[Affects R2][User decision + needs ongoing maintenance]** Which specific Instagram creators go on the seed list? Owner will supply an initial list of ~20 creators; the denylist from the opt-out system evolves it over time.
- **[Affects R2][Research]** Which specific Substack RSS feeds go in the Wave 2 pool? Candidates: Platformer, Stratechery, Ben's Bites, Import AI, Last Week in AI, Interconnects. Owner can prune/extend during planning.
- **[Affects R11][Config]** Final trusted-source allowlist needs to be committed to code or config. Draft starts with HN, HF trending, arXiv, Product Hunt, Lobste.rs, Ben's Bites.
- **[Affects R14a][Infrastructure]** Which domain hosts the `optout@` alias, and which forwarding mechanism (Cloudflare Email Routing, Gmail alias, etc.)?
- **[Affects R15][Technical]** Should the curation candidate table be unified with the existing `pipeline_runs` table or kept separate? Split is cleaner for v1; merging later is mechanically easy if the flow converges. Planner decides.
- **[Affects R12][Technical]** Credit overlay rendering: reuse moviepy (already in the pipeline venv) or shell out to raw ffmpeg? moviepy is slower but less new code; ffmpeg is tighter but adds complexity. Planner decides based on render time budget.
- **[Affects R5][Technical]** Telegram preview shape for **static-image** candidates (Reddit images, tweet screenshots, arxiv paper previews) vs **video** candidates. Existing `send_approval_preview` assumes video clips. Planner extends it to handle images.
- **[Affects R15][Needs research]** Post-hoc engagement logging: does the current Postiz build expose a per-post analytics endpoint via `/api/public/v1/posts/:id/analytics` or similar? If not, we need to query IG Graph API and YouTube Data API directly for the metrics.
- **[Affects R11][Needs research]** Instagram Reshare API: does Postiz expose a native reshare option (preserving original attribution) or do we always have to use download+overlay+repost for IG content? This changes the credit-compliance story for the IG source.

## Next Steps

→ `/ce:plan` for structured implementation planning
