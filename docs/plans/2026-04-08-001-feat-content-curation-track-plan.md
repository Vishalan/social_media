---
title: "feat: Content curation track (parallel pipeline, Waves 1-3)"
type: feat
status: reframed
date: 2026-04-08
deepened: 2026-04-09
reframed: 2026-04-09
origin: docs/brainstorms/2026-04-08-content-curation-track-requirements.md
---

## 🔁 REFRAME NOTE (2026-04-09)

**Phase 0 TOS review invalidated the core "download media + overlay credit + reupload" architecture.**

Findings in `docs/research/content-curation-tos-review.md`:
- Reddit, Product Hunt, Substack, Instagram creators, X Lists, YouTube trending all **prohibit** our original use case outright
- HN, Lobste.rs, GitHub Trending, HF Trending, arXiv are **conditional** — each is TOS-safe as a topic-signal source (title + url + summary) but NOT as a media-reshare source
- Zero sources survived for the original media-reshare pattern

**Accepted reframe (option 2 from owner decision):** The curation track becomes **topic-signal extension of the existing generative pipeline.** Instead of building a parallel reshare pipeline with its own scorer, safety classifier, media normalizer, credit overlay, opt-out system, and denylist, we simply add 4 new `TopicSource` implementations to the existing `sidecar/topic_sources/` package. Every new source feeds candidate topics (title + url + summary) into the existing `daily_trigger.py` → `process_pending_runs` → generative video pipeline. The generative pipeline's `browser_visit` b-roll generator already screenshots and scrolls the source URL — so the visual "this article" freshness is preserved without ever downloading or re-encoding third-party video.

**What gets built (new scope — ~4-6 units, ~1 week):**

1. `sidecar/topic_sources/github_trending_source.py` — scrape GitHub Trending HTML for the daily "cool AI/dev project launched" signal
2. `sidecar/topic_sources/huggingface_trending_source.py` — query HF trending API for model/space releases
3. `sidecar/topic_sources/arxiv_source.py` — RSS of cs.AI and cs.CL, filtering for CC-BY-tagged papers only
4. `sidecar/topic_sources/lobsters_source.py` — Lobste.rs RSS feed
5. Registry + config updates to `sidecar/topic_sources/__init__.py` and `sidecar/config.py`
6. `PIPELINE_TOPIC_SOURCES` default includes the new sources; per-source knobs added

**What gets DELETED from the original plan entirely (not just deferred):**

- `sidecar/content_sources/` package — use existing `topic_sources/` instead
- `sidecar/content_curation/` package — no scorer/classifier/normalizer/credit.py/trusted_sources needed
- `curation_candidates`, `curation_slot_log`, `creator_denylist`, `credit_enforcement_log`, `opt_out_events` tables — topics flow through existing `pipeline_runs`
- `approvals.kind` discriminator — single track, no discriminator
- All 3 opt-out channels — no reshare = no opt-out system
- Credit overlay (burned-in + post-overlay probe + integration test + audit log) — no reshare
- Media normalizer, safe-fetch helper, ffmpeg ulimit sandbox — no third-party media download
- T-2h warning / T-30min autopilot for curation — existing generative autopilot handles the single track
- Track-aware slot allocation — single track, existing `compute_next_slot` unchanged
- `nas_heavy_work_lock` refactor — no parallel heavy work, single generative lock stays local
- Curation dashboard view, engagement logger, weekly scoring review — defer; the existing generative dashboard already covers the (now unified) single track

**What stays viable:**

- HN source is ALREADY implemented (`sidecar/topic_sources/hackernews_source.py`) — no work
- Gmail TLDR source is ALREADY implemented (`sidecar/topic_sources/gmail_source.py`) — no work
- Existing `daily_trigger.py` already iterates enabled sources with per-source failure isolation — no new job code needed
- Existing `topic_selector.score_topics` already scores merged candidates across sources — no new scorer needed
- `sidecar/duplicate_guard.py` already handles novelty check — no new logic
- The generative pipeline (script → voice → thumbnail → b-roll → whisper → assembly) is the same pipeline shipped and validated this week

**Original plan (everything below this section) is preserved as a historical artifact** documenting the full 21-unit reshare-based design, its review, and why it was reframed. Do not execute any unit below — the execution scope is the 6 bullets above.

---

# Content Curation Track (Waves 1-3)

## Overview

Build a second content pipeline that runs alongside the existing generative track. Instead of scripting and animating original videos, this track scrapes trending tech content from 11 external sources, scores and safety-filters the candidates, surfaces the best ones in Telegram for the owner to review, and — on approval — downloads + trims + credit-overlays + schedules them via Postiz on the same peak-hour rails the generative track already uses.

The goal is NOT to replace the generative track. It is to add a second, cheaper, higher-signal stream of content that brings CommonCreed's proven "curated tech reshare" formula back, now automated up to the point where human taste still matters (the approval tap) and autopiloted beyond that point (the daily target).

## Problem Frame

See origin: `docs/brainstorms/2026-04-08-content-curation-track-requirements.md`.

Generative-only posting cannot sustain the daily cadence the channel needs (1-2 posts/day ceiling, ~$0.02 + 8 min compute per run, one long-form-ish clip per day). Historically @commoncreed's best traction came from curated reshares of viral tech content — a content model we have no automation for today. This plan delivers that missing track, feeding the same Telegram → Postiz → peak-hour rails we landed this week, with strict credit/opt-out guardrails to keep the account in good standing under aggressive-growth posting (20 posts/week).

## Requirements Trace

- **R1** — Scheduled curation trigger, env-flag gated (`SIDECAR_CURATION_TRIGGER_ENABLED`)
- **R2a** — Every enabled source has passed the Pre-Phase 1 TOS review gate. The initial candidate source list (before TOS review) was Reddit, HN extended, GitHub Trending, HF trending, arXiv, Lobste.rs, Product Hunt, Substack RSS pool, Instagram creators, X list, YouTube trending — the **actual v1 source list is whatever the TOS review blesses**. Sources that survive the review ship in v1. Sources that don't are deleted from scope; the plan never assumes a fixed count.
- **R2b** — Instagram creator scraping is out of v1 scope per the Scope Boundaries section; revisit only if an owner-owned-account reshare path proves viable.
- **R3** — Hard safety filter before scoring (NSFW, gore, political, personal attacks, denylisted creators). Safety filter is NOT a copyright adjudicator — copyright compliance is handled by the TOS review gate (R2a) and the credit policy (R12).
- **R4** — Hand-tunable scorer (topical fit + novelty + engagement + creator quality + media fit + safety). Scorer is a placeholder ranker whose hypothesis is invalidated or confirmed by Unit 20 engagement data within 2 weeks of first curated post.
- **R5** — Telegram approval flow, reuses existing `send_approval_preview` machinery with backwards-compatible signature (see Unit 9).
- **R6** — 10 candidates/day surfaced, threshold 0.60, ~30% approval rate target → ~3 posts/day target. Actual volume follows the autopilot's narrowed gate (R10/R11) and the dry-run funnel check (Pre-Phase 1).
- **R7** — 1 generative + up to 3 curated posts/day, 20/week cap at maximum velocity, ramped from an initial 7-10/week. Owner ramps after N clean weeks of IG reach metrics; cap is a variable, not a constant.
- **R8** — Track-aware slot allocation. Curation owns morning (09:00), lunch (13:00), and evening-2 (21:00). Generative owns evening-1 (19:00) exclusively. **Generative loses its morning slot** (see Unit 11 migration note).
- **R9** — T-2h warning in Telegram if unreviewed candidates remain for an upcoming slot.
- **R10** — T-30min autopilot auto-approves highest-scored unreviewed candidate, subject to R11. If no eligible candidate exists, the slot is **skipped without rescheduling** (weekly cap is a soft target, not a floor).
- **R11** — Autopilot eligibility: score ≥ 0.70 AND source is on the trusted-source set AND the source platform is the original publisher of the content (not an aggregator link to third-party media). Trusted-source set starts empty in config and is populated per-source only after the owner has approved content from that source manually for at least 1 week.
- **R12** — Every curated post carries credit enforced through four independent layers:
  - **R12a** — DB constraint on `curation_candidates.final_caption` (NOT NULL + CHECK containing `author_handle`)
  - **R12b** — Post-overlay verification probe confirming the ffmpeg drawtext filter produced a visible burn-in (sentinel/hash check)
  - **R12c** — Integration test `test_publish_rejects_missing_credit` in the v1 test suite, not deferred
  - **R12d** — Audit log row per blocked publish in a new `credit_enforcement_log` table
  - Plus the caption prefix + source link + IG Collab tag when possible (same as the original R12).
- **R13** — No raw reposts; every post must transform the source (trim + credit overlay AT MINIMUM, commentary text overlay or branding pairing preferred).
- **R14** — Two automated opt-out channels (email alias + public Google Form) each with human confirmation, feeding one reversible denylist with audit trail, 24h removal. IG DM is a manual channel — owner forwards to the Google Form.
  - **R14a** — Every inbound opt-out triggers a Telegram confirmation to the owner before the denylist entry is created
  - **R14b** — Denylist additions are reversible via a dashboard admin action with confirmation
  - **R14c** — Rate-limiting per submitter (email domain or IP) to prevent adversarial spam
  - **R14d** — Creator acknowledgement: every submitter receives a receipt (auto-reply for email, success page for form)
- **R15** — Persist runs, candidates, scores, decisions, credit enforcement events, and post-hoc engagement metrics. Unit 20 engagement logger ships alongside or before Unit 6 scorer so day-1 scoring has a real feedback loop.
- **R16** — Dashboard curation view (per-source counts, pending reviews, denylist, **slot skip log**, threat-model event counters).
- **R17 (new)** — **Security baseline.** Every external URL fetch uses a safe-fetch helper that blocks RFC1918/loopback/link-local destinations, enforces `Content-Length` and timeout limits, validates `Content-Type` against an allowlist, and sandboxes the ffmpeg subprocess with CPU/memory ulimits.
- **R18 (new)** — **Revenue attribution.** Unit 21's weekly report includes at least one revenue-side metric (long-form subscriber delta attributable to curation track, OR direct YT Shorts AdSense delta, OR explicit "no revenue impact measured yet"). The curation track is auto-paused after 4 weeks if zero revenue impact is measured.

## Scope Boundaries

- **In scope for v1 ship:** Sources whose terms of service have been verified to permit our use case (see § Pre-Phase 1 Prerequisites — the actual v1 source list is determined by that review and may be narrower than originally planned), scorer/classifier, media normalizer + credit overlay, Telegram approval reuse, Postiz publish reuse, autopilot with narrowed eligibility (see Unit 12), opt-out with human confirmation on every inbound channel, dashboard curation view, engagement logger, explicit threat model with SSRF + cache poisoning mitigations.
- **Future scope (Wave 4):** Bluesky, Mastodon, Telegram channels.
- **Future scope (Wave 5):** TikTok — revisit if earlier waves don't produce enough candidates.
- **Explicitly moved OUT of scope by this plan (following the document review):**
  - **Instagram creator scraping via Meta Graph API.** Review found no API surface exists for "fetch recent media from creators the caller does not own" in the 2026 Instagram Graph API. The Basic Display API was deprecated Dec 2024; `instagram_business_content_publish` / `hashtag_search` scopes are too narrow for a reshare use case. Reverse this only if a later spike proves an owner-owned-account reshare flow (saved-collection of creators the owner follows) is viable.
  - **IG DM polling as an opt-out channel.** Requires `instagram_manage_messages`, which only applies to messages sent by the business's own followers — not a routable surface for opt-outs from creators we've reshared. IG DM stays in the plan as a **manual channel**: the owner reads DMs in the app and forwards any opt-outs to the Google Form themselves.
- **Explicitly NOT in scope:** Autonomous posting without a human-in-the-loop default. Copyright adjudication. Cross-posting to X or TikTok in v1 (IG + YouTube only). Raw untransformed reposts. ML-based scoring. Re-uploading full copyrighted videos untrimmed. **Use of any source whose TOS has not been explicitly cleared in the Pre-Phase 1 review.**

## Pre-Phase 1 Prerequisites (owner + research spikes before Unit 1 starts)

This plan cannot start safely until the following gates are cleared. Every gate has a concrete output artifact.

### TOS Review Gate (blocking; must complete before Unit 4)

Produce `docs/research/content-curation-tos-review.md` containing a one-page-per-source review. For each of the 11 originally-listed sources (Reddit, HN, GitHub Trending, Hugging Face trending, arXiv, Lobste.rs, Product Hunt, Substack RSS pool, Instagram creators, X list, YouTube trending), record:

- Direct quote of the relevant TOS clause for "download content and republish it on a monetized account"
- Yes / No / Conditional verdict
- Conditions if conditional (e.g. "only CC-BY-tagged papers" for arXiv, "only model cards under Apache/MIT license" for HF)
- Fallback path if No (e.g. "use official embed primitive instead", or "drop from scope")

Adversarial review identified likely blockers at: Reddit Data API commercial-use ban, X API v2 §II redistribution ban, YouTube Data API §III.E.4.c download-and-redistribute ban, IG Platform Terms §3.a.i replicate-the-platform ban, arXiv perpetual license (only CC-BY subset is reshareable), Product Hunt API commercial-republish ban, GitHub TOS §D.5/§D.7 scrape-and-redistribute restriction. The review must address each of these explicitly.

**Expected outcome:** some sources will survive (arXiv CC-BY subset, HF permissive-licensed model cards, GitHub repos with permissive READMEs, Lobste.rs has a reshare-friendly license for titles+links), others will be deleted from v1 scope. **The plan's v1 source list is whatever this review blesses — do not assume 11.** Unit 4 and Unit 13 reduce accordingly.

### Postiz `delete_post` Research Spike (blocking; must complete before Unit 17)

Does the current Postiz build expose `DELETE /api/public/v1/posts/:id` or equivalent? Reverse-engineer by:

1. Check the running `commoncreed_postiz` container at `/app/apps/backend/dist/apps/backend/src/public-api/routes/v1/` for a delete route on the public integrations controller
2. Check the swagger spec at `/api/docs-json` for a DELETE route under `/public/v1/posts`
3. If either path exists, specify the exact method name on `PostizClient` to add
4. If neither exists, specify the per-platform fallback: Meta Graph `DELETE /{ig-media-id}?access_token=...` via the existing posting OAuth scope + YouTube Data API `videos.delete` via the existing Postiz YT OAuth

Output: add the chosen mechanism to Unit 17's approach section with a concrete signature.

### Revenue Attribution Plan (non-blocking but strongly recommended before Unit 21)

The project-level goal is $5k/month via YouTube AdSense on long-form clips. This curation plan ships Shorts to IG + YT Shorts, which have RPM ~$0.05-0.10 vs long-form's $12-30. Write a half-page `docs/research/curation-revenue-attribution.md` answering: **If curation engagement doubles with zero direct AdSense impact, is the track still worth running?** The answer guides whether the success criterion should be engagement, long-form subscriber conversions, or direct AdSense delta — and informs Unit 21's weekly-report content.

### Credential Prerequisites (user-action, non-blocking for plan start)

- **X bearer token** — owner obtains from developer.x.com; blocks Unit 15 only
- **X List IDs** — owner supplies 1-3 curated List IDs; blocks Unit 15 only
- **Substack feed URLs** — owner confirms or revises the draft pool (Platformer, Stratechery, Ben's Bites, Import AI, Last Week in AI, Interconnects); blocks Unit 13 only
- **Opt-out email domain + forwarding setup** — owner provisions `optout@<domain>` with a dedicated mailbox (not aliased to the primary inbox); blocks Unit 18 email channel only. Credentials land in `/secrets` via the Docker-secret path, not `.env`
- **Trusted-source allowlist** — starts empty in config. Sources are added one at a time after the owner has seen their approval rate over at least 1 week of manual review. Default allowlist is no longer hardcoded.

## Context & Research

### Relevant Code and Patterns

- **`sidecar/topic_sources/`** — exact template to mirror for `sidecar/content_sources/`. Has:
  - `base.py` (TopicSource Protocol) → mirror as `ContentSource` Protocol
  - `__init__.py` (registry + `load_enabled_sources(settings)` driven by env var)
  - `gmail_source.py`, `hackernews_source.py` as concrete examples
- **`sidecar/jobs/daily_trigger.py`** — reference shape for `curation_trigger.py`: loads enabled sources, iterates with per-source failure isolation, merges, scores via Claude, inserts DB rows.
- **`sidecar/jobs/publish.py`** — existing `publish_action`, `schedule_publish`, `compute_next_slot` all reused unchanged. Only the caller bindings change.
- **`sidecar/postiz_client.py`** — `publish_post` accepts video + thumbnail + captions + integration IDs. Already handles `type="schedule"` vs `type="now"`. Curation publish reuses this 1:1.
- **`sidecar/telegram_bot.py`** — `send_approval_preview(app, pipeline_run_id)` needs to become generic over approval kind (generation vs curation) and media type (video vs static image).
- **`sidecar/db.py`** — existing `pipeline_runs` + `approvals` tables; add parallel `curation_candidates` + reuse `approvals` with a `kind` column discriminator.
- **`sidecar/runtime.py`** — module-level registry for `scheduler` and `telegram_app`; new curation job handlers read from it the same way existing jobs do.
- **`sidecar/app.py`** — APScheduler wire-up for new `curation_trigger` + `curation_autopilot` jobs, gated behind `SIDECAR_CURATION_TRIGGER_ENABLED`.
- **`sidecar/config.py`** — add curation-specific settings alongside `PIPELINE_TOPIC_SOURCES`.
- **`sidecar/routes/approvals_api.py`** — extend with curation-aware approve/reject handlers.
- **`sidecar/routes/dashboard.py`** — add curation view.
- **`sidecar/duplicate_guard.py`** — reused for novelty check in R4's scorer.

### Institutional Learnings

Applied verbatim from today's `docs/solutions/integration-issues/nas-pipeline-bringup-gotchas-2026-04-07.md`:

1. **Never `rm -rf` a bind-mounted dir** — media downloads go into a writable named volume, not a bind mount.
2. **Pass whole .env through subprocess env** — any curation ffmpeg subprocess inherits the same env-passthrough contract as the generative pipeline (don't hand-pick env vars).
3. **APScheduler `misfire_grace_time`** — new curation jobs must explicitly set this (5 min for warning/autopilot; 1 hour for the daily scrape trigger).
4. **Runtime singletons over `app.state`** — new job handlers read `sidecar.runtime.scheduler` and `sidecar.runtime.telegram_app`, never import `sidecar.app` from a job module.
5. **httpx logger noise** — any new source that uses httpx inherits the existing WARN-level mute for url-in-log-line leaks.
6. **Postiz robots.txt cache** — already fixed in nginx.conf bind mount; curation publish inherits this automatically.
7. **duplicate_guard self-match** — curation novelty check must pass `exclude_run_id=candidate_id` the same way `publish_action` does today.
8. **Postiz publish_post contract** — already rewritten correctly in this week's work; curation reuses unchanged.

### External References

None needed — every technology layer in this plan has a strong local precedent. Per-source API docs (Reddit JSON, HN Firebase, GitHub REST, HF API, arXiv RSS, Product Hunt GraphQL, Meta Graph, X API v2, YouTube Data API v3) will be consulted per-unit during implementation, not in planning.

## Key Technical Decisions

- **Split `curation_candidates` table from `pipeline_runs`.** Rationale: the two flows track different attributes (a candidate has a `source`, `author_handle`, `engagement_signals`; a pipeline run has `cost_sonnet`, `cost_elevenlabs`, `video_path`). Merging later is mechanically easy if the flows converge. Splitting now keeps each schema clean and lets curation iterate without risking generative track data integrity.
- **Reuse `approvals` table with a `kind` discriminator column** (`generation` / `curation`). Rationale: Telegram approval handling is the same machinery — one message with Approve/Reject/Edit buttons. Adding a `kind` column is simpler than cloning the entire approval state machine.
- **Raw ffmpeg for media normalization and credit overlay**, not moviepy. Rationale: moviepy's `TextClip` + `CompositeVideoClip` for a single-line overlay is ~5-10 sec per render vs ffmpeg's `drawtext` filter at ~0.5-1 sec. For 3+ renders/day this adds up, and ffmpeg is already baked into the sidecar image via the pipeline venv. moviepy stays reserved for the generative assembly path where its higher-level API matters.
- **ContentSource protocol lives next to TopicSource, not underneath it.** Rationale: they return fundamentally different shapes (topics have `{title,url,summary}` → feed Claude extraction; content has `{media_url,caption,author_handle,source_url,media_type,engagement_signals}` → feed the scorer + normalizer directly). Trying to unify the two protocols produces a weaker abstraction for both.
- **Safety filter runs before the scorer, not alongside it.** Rationale: safety is a hard reject, not a weighted signal. Running it first short-circuits the expensive Claude scorer call on obviously-rejected candidates and saves ~50% of classifier cost on high-volume sources like Reddit.
- **Autopilot fires at T-30min, warning fires at T-2h.** Rationale: T-2h gives the owner a real chance to intervene during a busy day. T-30min is the last safe moment before the Postiz scheduled slot and gives the normalizer + overlay + upload chain enough time (~2-3 min of compute) before the slot fires.
- **Per-source failure isolation** at the daily trigger level. Rationale: 11 sources with varied APIs = at least one will be rate-limited or 5xx'ing on any given day. One broken source must never take down the whole run — this is the same pattern already shipped in `daily_trigger.py`.
- **Opt-out system uses a single unified denylist** backed by two automated pollers (email + Google Form) plus one manual channel (owner forwards IG DMs). Rationale: creators reach out via whichever channel is convenient; the owner should only see one denylist. Three-automated-channels (with IG DM as the third) was the original design but IG DM polling requires a Meta scope (`instagram_manage_messages`) that does not apply to our use case — see Scope Boundaries.
- **Every opt-out requires human confirmation before denylist entry.** Rationale: adversarial review identified opt-out spam / competitor takedown as the most-likely attack vector. Auto-processing inbound opt-outs — especially from email where `From:` is trivially spoofable — gives any adversary a one-click content-deletion pipeline against us. Human confirmation adds ~10 seconds to each legitimate opt-out and is the only defensible path.
- **Scorer is hand-tunable + a candidate for logistic regression later.** Rationale: hand-tuned Python is readable and editable by the owner, which matters for trust during cold-start. After Unit 20 produces 2-4 weeks of post-hoc engagement data, the same six signals become inputs to a tiny linear model whose coefficients remain interpretable. The plan is NOT "hand-tuned forever" — it's "hand-tuned first, regression second," and Unit 20 ships alongside Unit 6 (not 15 units later) so the feedback loop is live from day 1.
- **Credit enforcement is multi-layered, not a single if-check.** Rationale: "publish contract" enforcement via one Python exception can be bypassed by any refactor, retry path, or fallback branch. R12 now requires DB constraint on `final_caption` NOT NULL + CHECK containing `author_handle`, a post-overlay verification probe, an integration test in the v1 test suite, and an audit log of every blocked publish. Four independent layers, any one of which catches a missing credit.
- **Safe-fetch helper wraps every external URL retrieval.** Rationale: media URLs from scraped HTML (GitHub READMEs, Product Hunt) and user-editable content (Reddit self-posts) are attacker-controllable. Without RFC1918/loopback/link-local blocking, a malicious `media_url` can probe the NAS internal network from inside the sidecar container. The safe-fetch helper is a mandatory layer between every `ContentSource.fetch_candidates` network call and the actual HTTP stack.
- **Cache keys for the safety classifier include last-edited timestamps, not just source URL.** Rationale: Reddit/Substack/Medium posts are editable. Caching by `source_url` alone lets an adversary flip a pass verdict into an auto-publish of inflammatory content within the 24h cache window. Cache key must be invalidated when the source's content changes.
- **Autopilot eligibility narrowed: source must be the original publisher.** Rationale: "trusted source" ≠ "content is safe to repost." HN front page links to third-party media with unclear rights; arXiv PDFs by listed authors do not. The narrowed gate is: score ≥ 0.70 AND source in trusted set AND `source_is_original_publisher == True` (a new field set by each `ContentSource` implementation).
- **Trusted-source set starts empty and is populated per-source by the owner manually.** Rationale: the original plan shipped a 6-source default allowlist. Review surfaced that "trusted" was being decided a priori based on editorial reputation of the aggregator, not observed behavior of the content. Starting empty forces the owner to explicitly approve each source for autopilot eligibility only after seeing at least 1 week of manual approvals from it.
- **Single shared NAS heavy-work mutex across both tracks.** Rationale: the Synology DS1520+ is a 4-core Celeron J4125 with 8 GB RAM. The generative pipeline subprocess (avatar + moviepy + whisper) peaks at ~2 GB RSS and fully saturates 3-4 cores for 6-8 minutes. Curation's ffmpeg normalize+overlay peaks around 500 MB and 1-2 cores for ~30-60 seconds. Running them concurrently would push the NAS into swap and starve everything else (Postiz, Temporal, Postgres, Redis, the sidecar itself). The existing `_pipeline_lock` in `sidecar/jobs/run_pipeline.py` already enforces "only one generative subprocess at a time" via an `asyncio.Lock`. We **generalize this lock** into a shared module-level singleton `nas_heavy_work_lock` living in `sidecar/runtime.py`, and both `run_pipeline_for_run` (generative) and `curation_publish_action` (curation — Unit 10) acquire it around their heavy work. Curation's scraping + scoring + Telegram preview path does NOT need the lock (those are lightweight I/O); only the media normalize + overlay + Postiz upload needs it. This ensures at most one NAS-heavy job is in flight at a time across both tracks, while leaving the rest of the sidecar responsive.

## Open Questions

### Resolved During Planning

- **Unified vs split candidate table** → Split. See decision above.
- **Credit overlay renderer: moviepy vs ffmpeg** → Raw ffmpeg `drawtext` filter. See decision above.
- **Telegram preview shape for static vs video candidates** → Extend `send_approval_preview` to dispatch on `candidate.media_type` (`image` → `send_photo`; `video` → `send_video`).
- **Approval state machine for curation** → Reuse `approvals` table with a new `kind` column discriminator. See decision above.
- **Where `curation_trigger` lives in the scheduler** → Sibling to `process_pending_runs` and `daily_trigger`; runs twice daily (before morning + before lunch slots) so candidates are fresh when Telegram review opens.
- **Track-aware slot allocation** → `compute_next_slot(track=...)` gains a `track` parameter; generative always returns the evening slot 1, curation rotates through morning / lunch / evening slot 2 depending on how many curated slots have fired today.
- **Gate flag** → New env `SIDECAR_CURATION_TRIGGER_ENABLED`, parallel to `SIDECAR_DAILY_TRIGGER_ENABLED`. Off by default until the user flips it.

### Deferred to Implementation

- **[Affects U15][Needs research]** Does Postiz expose a native IG Reshare primitive, or does the Instagram source always have to download + overlay + repost? Check during U15 against the running Postiz container source (`/app/apps/backend/dist/.../instagram.provider.ts` and `ConnectIntegrationDto`).
- **[Affects U21][Needs research]** Does the Postiz public API expose per-post engagement metrics at `/api/public/v1/posts/:id/analytics` or similar? If not, U21 falls back to direct Meta Graph + YT Data API queries for post-hoc metrics.
- **[Affects U16][User decision]** Owner supplies 1-3 X List IDs before U16 ships. Without IDs, U16 source is still built but stays in "configured=False" state until list IDs are set.
- **[Affects U15][User decision]** Owner supplies an initial seed list of ~20 Instagram creators before U15 ships. Same pattern — source is built but stays unconfigured without seed data.
- **[Affects U14][User decision]** Owner picks the final Substack RSS pool (draft: Platformer, Stratechery, Ben's Bites, Import AI, Last Week in AI, Interconnects). Configurable via env at ship time.
- **[Affects U18][Infrastructure]** Owner provides the domain + forwarding mechanism for the opt-out email alias (Cloudflare Email Routing vs Gmail alias). Without this, U18's email channel stays disabled.
- **[Affects U14][Needs research]** Generic RSS parser lib choice — `feedparser` is already pinned in `scripts/requirements.txt` but not in the sidecar pipeline venv. U14 either adds it to `sidecar/pipeline_requirements.txt` or uses `xml.etree.ElementTree` directly for the small number of fields we actually need.
- **[Affects U8][Needs research]** Exact ffmpeg `drawtext` syntax for burned-in overlay including font selection. Use the bundled Inter-Black we uploaded to NAS assets (`/app/assets/fonts/Inter-Black.ttf`) — already available in the container.
- **[Affects U20][Convention]** Dashboard curation view UX shape — follow the existing Runs/Approvals tab layout. Exact Jinja template structure deferred to implementation.
- **[Affects U15/U18][Prerequisite]** Meta Graph API scrape permissions (separate from our existing posting perms). May require an App Review extension. Blocks U15 and U18's IG DM channel until granted.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

### Component shape

```
sidecar/
├── content_sources/                         NEW — sibling to topic_sources/
│   ├── __init__.py                          Registry + load_enabled_sources()
│   ├── base.py                              ContentSource Protocol
│   ├── reddit_source.py                     Wave 1
│   ├── hackernews_source.py                 Wave 1 — extended from topic_sources version
│   ├── github_trending_source.py            Wave 1
│   ├── huggingface_trending_source.py       Wave 1
│   ├── rss_source.py                        Wave 2 — generic RSS template
│   ├── substack_pool.py                     Wave 2 — wraps rss_source over a feed list
│   ├── arxiv_source.py                      Wave 2
│   ├── lobsters_source.py                   Wave 2
│   ├── producthunt_source.py                Wave 2
│   ├── instagram_source.py                  Wave 3 — requires Meta Graph scrape perms
│   ├── x_source.py                          Wave 3 — requires bearer token
│   └── youtube_trending_source.py           Wave 3 — reuses Postiz YT OAuth
│
├── content_curation/                        NEW
│   ├── __init__.py
│   ├── scorer.py                            Hand-tunable scoring function
│   ├── classifier.py                        Claude-backed safety filter
│   ├── media_probe.py                       ffmpeg probe: aspect, duration, codec, watermark heuristic
│   ├── media_normalizer.py                  ffmpeg pipeline: crop 9:16 + trim + sanitize
│   ├── credit.py                            ffmpeg drawtext overlay + caption template
│   └── trusted_sources.py                   Allowlist for autopilot
│
├── jobs/
│   ├── curation_trigger.py                  NEW — sibling to daily_trigger
│   ├── curation_autopilot.py                NEW — T-2h warning + T-30min auto-approve
│   ├── opt_out_poller.py                    NEW — unified opt-out channel poller
│   └── curation_engagement_logger.py        NEW — 7-day post-hoc metrics
│
├── routes/
│   ├── approvals_api.py                     MODIFY — add kind discriminator handling
│   ├── curation_api.py                      NEW — denylist CRUD + source status
│   └── dashboard.py                         MODIFY — add curation tab
│
├── db.py                                    MODIFY — new tables; approvals gains `kind` column
├── telegram_bot.py                          MODIFY — send_approval_preview handles image+video
└── config.py                                MODIFY — new settings group
```

### Per-run data flow

```
┌─────────────────┐     ┌──────────────┐     ┌──────────────┐
│ curation_trigger│ ──> │ all enabled  │ ──> │ safety       │
│ (twice/day cron)│     │ content      │     │ classifier   │
└─────────────────┘     │ sources      │     │ (hard reject)│
                        └──────────────┘     └──────────────┘
                                                     │
                        ┌──────────────┐     ┌───────▼──────┐
                        │ curation_    │ <── │ scorer       │
                        │ candidates   │     │ (6 signals,  │
                        │ (top 10/day) │     │  threshold   │
                        └──────────────┘     │  0.60)       │
                               │             └──────────────┘
                               ▼
                        ┌──────────────┐
                        │ Telegram     │  each candidate = one message
                        │ preview      │  thumbnail OR video clip
                        │ (per candidate)     Approve/Reject/Edit buttons
                        └──────────────┘
                               │
                        ┌──────┴──────┐
                        ▼             ▼
                ┌────────────┐  ┌──────────────┐
                │ Owner taps │  │ T-2h warning │
                │ Approve    │  │ then T-30min │
                │            │  │ autopilot    │
                │            │  │ (trusted +   │
                │            │  │  score≥0.70) │
                └────────────┘  └──────────────┘
                        │             │
                        └──────┬──────┘
                               ▼
                ┌──────────────────────────┐
                │ media_normalizer +       │  ffmpeg: download,
                │ credit.overlay           │  crop 9:16, trim 15s,
                │                          │  drawtext burn-in
                └──────────────────────────┘
                               │
                               ▼
                ┌──────────────────────────┐
                │ PostizClient.publish_post│  type="schedule",
                │ (existing, unchanged)    │  date=next track slot
                └──────────────────────────┘
                               │
                               ▼
                        ┌──────────────┐     ┌──────────────────┐
                        │ Postiz queue │ ──> │ IG + YouTube     │
                        └──────────────┘     │ (peak hour fire) │
                                             └──────────────────┘
                               ┌───────────────┴────┐
                               ▼                    ▼
                        ┌────────────┐      ┌──────────────┐
                        │ 7-day      │      │ opt-out      │
                        │ engagement │      │ poller       │
                        │ logger     │      │ (3 channels) │
                        └────────────┘      └──────────────┘
```

### ContentSource protocol shape

> Directional pseudocode; implementer can deviate where it sharpens the contract.

```python
class ContentSource(Protocol):
    name: str              # "reddit", "github_trending", ...
    wave: int              # 1, 2, or 3 — used by phased rollout gate

    def is_configured(self, settings) -> bool: ...

    def fetch_candidates(self, settings) -> list[CandidateDict]:
        # Returns list of dicts with at least:
        #   source           str  (== self.name)
        #   source_url       str  (permalink on the origin platform)
        #   author_handle    str
        #   author_name      str | None
        #   title            str
        #   caption_seed     str  (original caption/description, may be trimmed)
        #   media_type       "image" | "video" | "none"
        #   media_url        str | None
        #   engagement       dict (score/likes/upvotes/etc. — normalized per source)
        #   published_at     str  (ISO)
        ...
```

### `curation_candidates` table shape

> Directional; exact migration logic belongs in implementation.

| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | |
| `created_at` | TEXT | ISO |
| `source` | TEXT | e.g. `reddit`, `hackernews` |
| `source_url` | TEXT | permalink |
| `author_handle` | TEXT | |
| `author_name` | TEXT | nullable |
| `title` | TEXT | |
| `caption_seed` | TEXT | original source caption, may be rewritten |
| `media_type` | TEXT | `image` / `video` |
| `media_url` | TEXT | |
| `engagement_json` | TEXT | per-source raw signals |
| `score` | REAL | final scorer output 0.0-1.0 |
| `score_breakdown_json` | TEXT | per-signal contributions for future tuning |
| `safety_verdict` | TEXT | `pass` / `reject:<reason>` |
| `status` | TEXT | `pending` / `approved` / `rejected` / `published` / `failed_publish` / `removed_opt_out` |
| `approval_id` | INTEGER FK → approvals.id | nullable until Telegram surfaces it |
| `normalized_media_path` | TEXT | set after Unit 8 normalization |
| `final_caption` | TEXT | set after Unit 9 credit builder |
| `postiz_post_ids_json` | TEXT | set after publish |
| `published_at` | TEXT | set after publish |
| `engagement_tracked_json` | TEXT | set by 7-day post-hoc logger |

## Implementation Units

Delivered in 9 phases. Ship Wave 1 end-to-end first, then Wave 2 RSS sources, then Wave 3 auth sources, then hardening (opt-out, dashboard, engagement logger).

### Phase 1: Foundation

- [ ] **Unit 1: ContentSource protocol, registry, curation tables, and credit enforcement scaffolding**

**Goal:** Establish the new `sidecar/content_sources/` package and ALL new database tables the curation track needs:

1. `curation_candidates` — candidate lifecycle, one row per surfaced item
2. `curation_slot_log` — record of every slot decision (fired / skipped / auto-approved / manual) with reason, for dashboard surface and auditing
3. `creator_denylist` — opt-out denylist (R14) with retention metadata
4. `credit_enforcement_log` — audit row per blocked publish when R12's credit check rejects a candidate (R12d)
5. `opt_out_events` — audit trail of every inbound opt-out with source, submitter, confirmation timestamp, and reversal state (R14b)

Plus the `approvals.kind` discriminator column migration.

**Requirements:** R1, R12a, R12d, R14b, R15, R16 (slot_log powers dashboard slot-performance view)

**Dependencies:** None

**Files:**
- Create: `sidecar/content_sources/__init__.py`
- Create: `sidecar/content_sources/base.py`
- Modify: `sidecar/db.py` (add the five tables above via `_apply_column_migrations`, plus helpers: `insert_curation_candidate`, `update_curation_candidate`, `get_curation_candidate`, `get_pending_curation_candidates`, `insert_slot_log`, `add_denylist_entry`, `is_denied`, `log_credit_enforcement_block`, `insert_opt_out_event`). Also: `approvals.kind TEXT DEFAULT 'generation'` column.
- Modify: `sidecar/config.py` — add curation settings: `PIPELINE_CONTENT_SOURCES`, `CURATION_SCORE_THRESHOLD`, `CURATION_DAILY_SURFACE_LIMIT`, `CURATION_AUTOPILOT_SCORE_FLOOR`, `CURATION_WEEKLY_CAP_PER_PLATFORM`, `TRUSTED_SOURCES_SET` (starts empty per R11), `DENYLIST_RETENTION_DAYS=730`, `SAFE_FETCH_MAX_BYTES=52428800`, `SAFE_FETCH_ALLOWED_MIME` comma-separated list.
- Test: `sidecar/tests/test_content_sources_registry.py`
- Test: `sidecar/tests/test_curation_db.py`

**Approach:**
- Mirror `sidecar/topic_sources/__init__.py` exactly for the registry + loader. Different class name (`ContentSource`) but same shape: `_REGISTRY` dict + `load_enabled_sources(settings)` + `is_configured()` skip.
- All new tables use the same `_apply_column_migrations` pattern `pipeline_runs` uses — no Alembic, raw SQL.
- `curation_candidates.final_caption` is **NOT NULL** with a `CHECK (final_caption IS NULL OR final_caption != '')` constraint at the schema level (R12a). The column is nullable until the candidate reaches the `approved` state; enforcement happens at `update_curation_candidate(status='approved')` where the helper also asserts `final_caption IS NOT NULL AND author_handle IS NOT NULL`.
- **Terminology cleanup (P1-E5):** rename all "allowlist" references to distinct names — `trusted_sources_set` (R11 autopilot gate), `creator_quality_allowlist` (Unit 6 scorer signal), `instagram_creator_seed_list` (Unit 14 — now out of scope). This plan uses the new names going forward; `allowlist` as a bare term is ambiguous and avoided.
- `approvals.kind` column migration must be backwards-compatible (default `'generation'` for existing rows), and the `routes/approvals_api.py` discriminator in Unit 10 must treat `None` as `'generation'` defensively.

**Patterns to follow:**
- `sidecar/topic_sources/__init__.py` — registry loader
- `sidecar/topic_sources/base.py` — Protocol shape
- `sidecar/db.py::insert_pipeline_run`, `get_pending_pipeline_runs`, and the `_apply_column_migrations` helper — column migration pattern

**Test scenarios:**
- Registry loads empty list when env is empty
- Unknown source name is logged and skipped, not raised
- `is_configured=False` source is filtered out of `load_enabled_sources`
- `insert_curation_candidate` returns new row id and the row is retrievable via `get_pending_curation_candidates`
- Column migration on existing `approvals` table sets `kind='generation'` on prior rows
- Pre-existing pending-approval row (from before Unit 1) is still routed to `publish_action` (not `curation_publish_action`) after migration — prevents cross-restart null-kind collisions
- Duplicate run of `_apply_column_migrations` is a no-op
- `update_curation_candidate(status='approved', final_caption=None)` raises — enforces R12a at the helper level
- `add_denylist_entry` with a duplicate (handle, source) key is idempotent, does not create duplicates

**Verification:**
- Running `python -c "from sidecar.content_sources import load_enabled_sources"` inside the sidecar container succeeds.
- All five new tables exist after container start; existing `approvals` rows have `kind='generation'` backfilled.
- Attempting to approve a curation_candidate with no `final_caption` raises the expected error.

---

- [ ] **Unit 2: curation_trigger job scaffold + APScheduler wire-up**

**Goal:** Add `curation_trigger.py` that iterates enabled `ContentSource` instances, merges candidates, invokes the scorer (stubbed for now), inserts top N into `curation_candidates`. Wire into APScheduler gated behind `SIDECAR_CURATION_TRIGGER_ENABLED`.

**Requirements:** R1, R15

**Dependencies:** Unit 1

**Files:**
- Create: `sidecar/jobs/curation_trigger.py`
- Modify: `sidecar/app.py` (register new scheduled job alongside `daily_trigger`, cron twice daily ~06:00 and ~10:00 to beat the morning + lunch slots, gated by new env flag, same `misfire_grace_time=3600` pattern)
- Modify: `sidecar/config.py` (add `CURATION_DAILY_SURFACE_LIMIT`, `CURATION_FETCH_SCHEDULE` optional)
- Test: `sidecar/tests/test_curation_trigger.py`

**Approach:**
- Mirror `sidecar/jobs/daily_trigger.py` layout verbatim: outer try, `load_enabled_sources`, per-source `try/except` with `per_source_counts` accounting, merged candidate list, failure isolation.
- For Unit 2 the scorer is a stub that accepts all candidates (just lets the pipeline pass through). Real scorer arrives in Unit 7.
- Gate flag mirrors the exact pattern shipped today for `SIDECAR_DAILY_TRIGGER_ENABLED`.

**Patterns to follow:**
- `sidecar/jobs/daily_trigger.py` — whole-file layout
- `sidecar/app.py` `daily_trigger` wire-up block for the env-flag gate

**Test scenarios:**
- Empty source list → returns `{ok: True, skipped: True, reason: "no sources enabled"}`
- Source raises → isolated, per_source_counts records 0, other sources still process
- All sources return 0 items → `{ok: True, skipped: True, reason: "no items"}`
- Items present → inserted into `curation_candidates` with status=`pending`
- Env flag off → scheduler does NOT register the job

**Verification:**
- Container logs show `curation_trigger wired at HH:MM` when flag=on and nothing when off.
- Manual exec of `curation_trigger.run_curation_trigger()` with a fake in-memory source returns expected dict.

---

- [ ] **Unit 3: Trusted-source allowlist + curation settings block**

**Goal:** Centralize the autopilot allowlist and all new curation settings behind one config module.

**Requirements:** R11, R7

**Dependencies:** Unit 1

**Files:**
- Create: `sidecar/content_curation/__init__.py`
- Create: `sidecar/content_curation/trusted_sources.py` (exposes `is_trusted(source_name) -> bool`, reads from `settings.CURATION_TRUSTED_SOURCES`)
- Modify: `sidecar/config.py` (add `CURATION_TRUSTED_SOURCES` default string `"hackernews,huggingface_trending,arxiv,producthunt,lobsters,bens_bites"`, plus `CURATION_AUTOPILOT_SCORE_FLOOR=0.70`, `CURATION_TELEGRAM_SURFACE_THRESHOLD=0.60`, `CURATION_WEEKLY_CAP_PER_PLATFORM=20`)
- Test: `sidecar/tests/test_trusted_sources.py`

**Approach:**
- Comma-separated env var parsed the same way `PIPELINE_TOPIC_SOURCES` is.
- `is_trusted` is a single-line set membership check; kept in its own module because Unit 13's autopilot and Unit 7's scorer both use it.

**Patterns to follow:**
- `sidecar/topic_sources/__init__.py::_parse_enabled` — same comma-split logic

**Test scenarios:**
- Empty allowlist → no source is trusted
- Default list → `hackernews` trusted, `reddit` untrusted
- Unknown name in list → no-op (never raises)

**Verification:**
- `is_trusted("reddit")` returns False with default settings; `is_trusted("hackernews")` returns True.

### Phase 2: Wave 1 content sources

- [ ] **Unit 4: Wave 1 content sources (Reddit, HN, GitHub Trending, HF trending)**

**Goal:** Ship the four Wave 1 sources behind the `ContentSource` protocol. All four share the same "fetch → filter by engagement → map to candidate dict" shape with source-specific quirks.

**Requirements:** R2 (Wave 1), R3 (safety filter runs later; sources just surface raw candidates)

**Dependencies:** Unit 1

**Files:**
- Create: `sidecar/content_sources/reddit_source.py`
- Create: `sidecar/content_sources/hackernews_source.py` (different from the existing topic_source — this one returns `ContentSource`-shaped dicts, not `TopicSource`-shaped ones)
- Create: `sidecar/content_sources/github_trending_source.py`
- Create: `sidecar/content_sources/huggingface_trending_source.py`
- Modify: `sidecar/content_sources/__init__.py` (register the four classes)
- Modify: `sidecar/config.py` (per-source knobs: `REDDIT_SUBREDDITS`, `REDDIT_MIN_SCORE`, `GITHUB_TRENDING_LANGUAGES`, etc.)
- Test: `sidecar/tests/test_reddit_source.py` (with canned Reddit JSON fixture)
- Test: `sidecar/tests/test_hackernews_content_source.py`
- Test: `sidecar/tests/test_github_trending_source.py`
- Test: `sidecar/tests/test_huggingface_trending_source.py`

**Approach:**
- **Reddit:** Fetch `/r/{subreddit}/top.json?t=day&limit=25` for each subreddit in `REDDIT_SUBREDDITS`. Skip NSFW, skip text-only (no media URL), enforce `REDDIT_MIN_SCORE`. Extract username + permalink + media URL + score.
- **HN:** Extend the existing topic_source logic but map each top-story item into the `ContentSource` dict shape. Attach a placeholder thumbnail (HN has no native thumbnails; fetch the linked URL's OG image or skip). Filter out Ask HN / text posts.
- **GitHub Trending:** No public JSON API; scrape `github.com/trending` HTML (permissive terms for the trending page specifically) via BeautifulSoup. Extract repo name, URL, star count, description, and the first README image URL as the media candidate. Alternative: use the unofficial `github-trending-api` package if it's available as a library — decide during implementation.
- **HF trending:** Fetch `https://huggingface.co/api/trending?type=model&limit=20` and `?type=space&limit=20`. Each entry includes a thumbnail via the HF CDN for Spaces with demo gifs. Filter for entries with a thumbnail.
- All four: per-source failure isolation (return `[]` on any error, never raise).
- All four: stamp `source` field on every candidate dict so the registry loader doesn't have to.

**Patterns to follow:**
- `sidecar/topic_sources/hackernews_source.py` — httpx client pattern, per-source timeout, logger warnings

**Test scenarios (per source):**
- Normal response → returns expected candidate list
- HTTP 5xx → returns `[]`, logged at WARN
- Empty response → returns `[]`, not an error
- Malformed JSON / HTML → returns `[]`
- NSFW item (Reddit) → filtered out
- Below min score (Reddit/HN) → filtered out
- Missing media URL → filtered out
- `is_configured` returns True without auth (all four are public APIs)

**Verification:**
- Running each source's `fetch_candidates` against live APIs returns a non-empty list on a normal day.
- `curation_trigger` with all four Wave 1 sources enabled collects candidates from each.

### Phase 3: Scoring & safety

- [ ] **Unit 5: Safety classifier (hard reject filter)**

**Goal:** Claude Haiku–backed classifier that rejects NSFW, gore, political partisan content, personal attacks, medical/financial advice framed as fact. Runs before the scorer.

**Requirements:** R3

**Dependencies:** Unit 1

**Files:**
- Create: `sidecar/content_curation/classifier.py` (exposes `classify_safety(candidate_dict) -> {"verdict": "pass" | "reject", "reason": str}`)
- Test: `sidecar/tests/test_safety_classifier.py`

**Approach:**
- Single Haiku call per candidate with a short structured prompt listing the 5 hard-reject categories (NSFW, gore, political partisan, personal attacks, medical/financial advice framed as fact). **Copyright is explicitly NOT in the classifier's job** — that's handled by the TOS review gate (R2a) and credit policy (R12).
- Return JSON `{verdict, reason}` from Claude; parse with retry-on-bad-JSON (same pattern as `topic_selector._parse_json_array`).
- Per-call cost ~$0.0001; per-day cost at the TOS-reviewed source list × ~30 raw candidates each = roughly $0.01-0.03/day depending on how many sources survive the gate.
- **Cache key is a composite hash, NOT `source_url` alone** (threat model T3, adversarial review). Key = `sha256(caption_seed || media_url || source_last_edited_timestamp || source_url)`. Sources that don't expose a last-edited timestamp (HN, GitHub READMEs) fall back to content-hash invalidation: any change in `caption_seed` or `media_url` invalidates the cache entry. Cache TTL 24h; eviction is lazy (first query after expiry triggers re-classification).
- **Graceful degradation on Claude API outage:** the plan's original "fail-closed = reject everything" behavior has a known pathological case (Claude 2-hour outage → entire day's candidates rejected → autopilot skips all slots → zero posts). New behavior: on classifier error, mark candidates with `safety_verdict = "classifier_unavailable"` and surface them to Telegram with a conspicuous `⚠ CLASSIFIER DOWN — manual review required` banner instead of dropping them. Autopilot must NOT auto-approve any candidate with `safety_verdict != "pass"` — this preserves the safety gate while keeping the manual review path open during API outages.
- **Autopilot re-classification:** Unit 12's autopilot call-site re-runs `classify_safety` on the chosen candidate at T-30min regardless of cache, because the 24h window is large enough for source content to have changed (T3 poisoning mitigation). Re-classification cost is negligible.

**Patterns to follow:**
- `sidecar/topic_selector.py` — Claude call + JSON parsing + retry shape
- `sidecar/duplicate_guard.py` — lookback pattern for the cache TTL logic

**Test scenarios:**
- Benign tech item → `verdict=pass`
- NSFW caption keyword → `verdict=reject, reason=nsfw`
- Partisan political content → `verdict=reject, reason=political`
- Personal attack → `verdict=reject, reason=personal_attack`
- Ambiguous case → Claude's judgment is final; test with a known-borderline example to lock the behavior
- Claude API error → `verdict=reject, reason="classifier_unavailable"` (fail-closed)

**Verification:**
- Classifier runs against a fixture list of 10 curated examples (5 pass, 5 reject) and matches expected verdicts.
- Full-day dry run against Wave 1 sources shows the classifier filtering ~5-15% of candidates.

---

- [ ] **Unit 6: Hand-tunable scorer**

**Goal:** Implement the 6-signal scoring function from R4 with a tunable weight config. Integrate novelty via the existing `duplicate_guard`.

**Requirements:** R4, R6, R15

**Dependencies:** Unit 1, Unit 5

**Files:**
- Create: `sidecar/content_curation/scorer.py` (exposes `score_candidate(candidate, settings, db_conn) -> {"score": float, "breakdown": dict}`)
- Modify: `sidecar/content_curation/__init__.py` (re-export)
- Modify: `sidecar/duplicate_guard.py` (generalize `check()` to work against `curation_candidates` as well as `pipeline_runs` — either via a `table` param or a second helper `check_curation_duplicate`)
- Test: `sidecar/tests/test_curation_scorer.py`

**Approach:**
- Weight constants at module top so they're trivially tunable.
- Per-signal contribution is clamped to [0, 1] before weighting.
- Normalize engagement per-source (Reddit score/max_daily vs HN points/top_of_day) so one viral HN post doesn't dominate.
- Creator quality pulls from a `creators.json` allowlist/denylist file (new, empty for v1 — populated iteratively).
- Novelty check reuses `duplicate_guard` with a 30-day lookback.
- Return a full breakdown dict so Unit 20's dashboard can display "why did this score X?".

**Patterns to follow:**
- `sidecar/topic_selector.py::score_topics` — Claude-based scoring is a different model but the function shape is similar

**Test scenarios:**
- All signals at max → score ≈ 1.0
- All signals at zero → score ≈ 0.0
- Novel item scores higher than a near-duplicate
- Unknown creator gets neutral weight
- Denylisted creator gets score = 0.0 (short-circuit)
- Breakdown sums to the final score (sanity check)

**Verification:**
- Running the scorer on 20 known good/bad fixture candidates produces the expected ranking.
- Full pipeline (Unit 2 + this unit) inserts candidates into `curation_candidates` with score + breakdown populated.

### Phase 4: Media pipeline

- [ ] **Unit 7: Media probe + normalizer**

**Goal:** Download a candidate's source media and normalize it for IG Reels / YouTube Shorts (9:16, ≤30s, H.264, AAC).

**Requirements:** R12, R13, R17

**Dependencies:** Unit 1

**Files:**
- Create: `sidecar/content_curation/safe_fetch.py` (exposes `fetch(url, max_bytes, allowed_mime) -> (bytes, resolved_mime)` with RFC1918/loopback/link-local blocking) — **this module is the only sanctioned path for external URL fetches anywhere in the curation track**
- Create: `sidecar/content_curation/media_probe.py` (exposes `probe(local_path) -> {duration, width, height, has_watermark_hint, codec}` using `ffprobe` — note: probes a LOCAL file, not a URL, because all downloads go through safe_fetch first)
- Create: `sidecar/content_curation/media_normalizer.py` (exposes `normalize(candidate, out_dir) -> normalized_path`; calls `safe_fetch.fetch` then `probe` then ffmpeg to crop/trim/transcode)
- Test: `sidecar/tests/test_safe_fetch.py`
- Test: `sidecar/tests/test_media_probe.py` (against known tiny mp4 fixtures)
- Test: `sidecar/tests/test_media_normalizer.py`

**Approach:**
- **safe_fetch (R17 — SSRF mitigation, threat model T2):** Before any HTTP request, resolve the hostname via `socket.getaddrinfo` and reject if any resolved IP is in an RFC1918 range (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), loopback (`127.0.0.0/8`, `::1`), link-local (`169.254.0.0/16`, `fe80::/10`), or multicast. Use an `httpx.Client` with custom `transport` that validates resolved addresses before connecting (httpx `transport=httpx.HTTPTransport(local_address=...)` and a pre-connect hook). Enforce `Content-Length` ≤ `SAFE_FETCH_MAX_BYTES` (default 50 MB) — reject if missing or larger. Validate `Content-Type` against the allowlist (`video/mp4`, `video/quicktime`, `image/jpeg`, `image/png`, `image/webp`). Timeout 30 seconds. This is a **hard gate** — any bypass is a security bug.
- Shell out to ffmpeg/ffprobe via `subprocess.run`, pipeline venv already has imageio-ffmpeg.
- Downloads land in `/app/output/curation/` (volume-backed, writable) — same writable-volume pattern as the generative pipeline.
- **ffmpeg subprocess sandbox:** wrap the ffmpeg invocation with a small shell helper `ulimit -t 120 -v 2000000 &&` (120 sec CPU, ~2 GB virtual memory) or use Python's `resource.setrlimit` in a preexec_fn. This bounds damage from malicious inputs triggering ffmpeg CVEs.
- Crop rule: if source aspect is landscape, center-crop to 9:16 with optional top-and-bottom blur pad. If already 9:16, pass-through. If portrait but wrong ratio, pad.
- Trim: if source > 30s, clip to the first 30s (or first 15s for Reels). Loudness normalize to -14 LUFS.
- Codec: always re-encode to H.264 high + AAC 128k for safety even if the source already is (avoids Postiz/IG rejecting weird containers).
- **Canonical output resolution: 1080×1920** (locked in response to P1-E6 — Unit 8 overlay sizing depends on this being fixed). Any landscape source is scaled to fit in the 1080×1920 canvas with padding as needed.
- Watermark hint: static-pixel detection on the first/last frame corners; if detected, flag the candidate (`has_watermark_hint=True` on the curation_candidates row) so Unit 9's Telegram preview surfaces it to the reviewer. Do not auto-reject.

**Patterns to follow:**
- `scripts/video_edit/` — existing ffmpeg shell-out patterns (read-only mounted at `/app/scripts` inside the container)
- `sidecar/pipeline_runner.py::_run_subprocess` — timeout + process group kill pattern
- `ipaddress.ip_address().is_private / is_loopback / is_link_local` — stdlib SSRF check primitive

**Test scenarios:**
- safe_fetch: `http://192.168.29.211:9000/` → rejected with `SafeFetchError("rfc1918 address blocked")`
- safe_fetch: `http://169.254.169.254/` → rejected (link-local)
- safe_fetch: `http://localhost/` → rejected (loopback)
- safe_fetch: public URL with `Content-Length: 999999999` → rejected (too large)
- safe_fetch: public URL with `Content-Type: text/html` → rejected (not in allowlist)
- safe_fetch: public URL with redirect to `http://192.168.29.211/` → rejected (chain-check)
- safe_fetch: valid public video URL → returns bytes + resolved mime
- Landscape 16:9 mp4 → center-cropped to 9:16, duration preserved if ≤ 30s, output 1080×1920
- Vertical 9:16 mp4 → pass-through (re-encoded to canonical settings only)
- Landscape > 30s → trimmed to 30s
- Corrupt input → raises `MediaNormalizationError` with a descriptive message
- ffmpeg timeout → subprocess killed cleanly via `start_new_session=True` + ulimit
- Watermark detected → candidate row updated with `has_watermark_hint=True`, does not block normalization
- No ffmpeg in PATH → raises early with a clear error (sanity check for local dev)

**Verification:**
- Normalizing 5 fixture clips from different sources all produce ≤10 MB, 9:16, 1080×1920, ≤30s H.264 mp4s that play in VLC.
- Running the normalizer on a live public video URL completes in < 30s.
- Running the normalizer on a URL pointing at `http://192.168.29.211/` fails with `SafeFetchError` before any byte is downloaded.

---

- [ ] **Unit 8: Credit overlay + caption builder**

**Goal:** Add a visible credit overlay via ffmpeg `drawtext` and produce the final Postiz caption.

**Requirements:** R12, R13

**Dependencies:** Unit 7

**Files:**
- Create: `sidecar/content_curation/credit.py` (exposes `overlay_credit(video_path, author_handle, source_platform) -> overlaid_path` and `build_caption(candidate, our_intro_line) -> str`)
- Test: `sidecar/tests/test_credit_overlay.py`
- Test: `sidecar/tests/test_credit_caption.py`

**Approach:**
- `drawtext` filter with Inter-Black font already mounted at `/app/assets/fonts/Inter-Black.ttf` on the sidecar container.
- **Canvas:** 1080×1920 (locked in Unit 7). Overlay sizes are percentages of canvas height so the same code works for future resolution changes.
- **Overlay position: TOP-LEFT, not bottom-left.** Reason (P1-E6, design-lens review): IG Reels reserves the bottom ~180px for username + caption chrome + action buttons. A bottom-left overlay is occluded exactly where credit matters most, which is a credit-policy failure mode. Top-left is outside IG's top chrome (~60px for navigation) and visible in both IG Reels and YouTube Shorts player.
- **Overlay sizing:**
  - Font size: 2.5% of canvas height = 48px on a 1080×1920 canvas (not 24 — "24px" was correct for a 720×1280 canvas, which we aren't using)
  - Horizontal padding: 32px from left edge
  - Vertical padding: 90px from top edge (clears IG's top chrome)
  - Outline: 3px black stroke around white fill — legible over any busy video background
  - Background: optional 40%-alpha black box behind the text for extra legibility on white-heavy backgrounds
- **Text template:** `via @{author_handle} · {source_platform}` (literal, simple, no emoji in the overlay itself — emojis belong in the caption, not the burn-in).
- **Handle truncation:** at 30 characters, append `…`. Unicode handles (Japanese, Cyrillic, etc.) use the bundled Inter-Black which has reasonable Latin + extended coverage; for CJK fallback, try DejaVu Sans fallback path if Inter-Black glyph map misses.
- **Post-overlay verification probe (R12b):** after ffmpeg drawtext, extract frame 0 and frame 60 via `ffmpeg -ss N -frames:v 1`, compute a small image hash of a fixed rect in the overlay region, and assert it differs from the pre-overlay hash of the same rect. If the probe fails (meaning drawtext silently produced identical output), the function raises `CreditOverlayNotAppliedError` and the candidate is marked `failed_publish` with reason `credit_overlay_probe_failed`. This catches drawtext filter silently failing (happens when font path is wrong) — the original "publish contract" enforcement was one unverified call.
- **Caption template:** lives in `credit.py`, simple Python f-strings. Structure:
  ```
  {our_intro_line}

  via @{author_handle} · {source_platform}
  {source_url}

  {hashtags}
  ```
  `our_intro_line` defaults to a per-source template that encodes the source's editorial signal, not a generic exclamation (P2-12, design-lens review):
  - HN: `"Top of Hacker News right now —"` (signal = builder consensus)
  - arXiv: `"New paper from @{author_handle}:"` (signal = novelty + author identity)
  - HF trending: `"Trending on Hugging Face:"` (signal = leaderboard movement)
  - GitHub Trending: `"This just hit GitHub trending:"` (signal = star velocity)
  - Substack: `"From {feed_name}:"` (signal = publication brand)
  - Reddit: `"Spotted on r/{subreddit}:"` (signal = community context, NOT generic "spotted on Reddit")
  Owner can override in Telegram via the edit_caption flow.
- **build_caption enforces R12a at the module level:** if `author_handle` is empty or `None`, raises `MissingCreditError` and the call site flips candidate status to `failed_publish` with a `credit_enforcement_log` row. No fallback caption, no graceful degradation.

**Patterns to follow:**
- Existing ffmpeg filter patterns in `scripts/video_edit/`
- Existing caption builder pattern in `sidecar/caption_gen.py` (for the generative track)

**Test scenarios:**
- Overlay on a 9:16 1080×1920 clip → output has burned-in text at top-left coordinates (32, 90), verified by frame hash comparison
- Caption template for each source produces the expected shape with the source-specific intro
- Long author_handle (>30 chars) → truncated with `…`, no layout break
- Unicode handle (Japanese creator name) renders without missing-glyph tofu
- Empty author_handle → `build_caption` raises `MissingCreditError`
- Missing Inter-Black font file → raises early, does not silently fall back to default
- Post-overlay probe: silently-failed drawtext (e.g. wrong font path bypassed) → raises `CreditOverlayNotAppliedError`
- Static image candidate (media_type=image) → `overlay_credit` delegates to a single-image variant that composites the same text via PIL, not ffmpeg
- IG caption includes hashtags on a separate paragraph, YouTube caption has no hashtags line (YT uses description + tags separately)

**Verification:**
- 3 curated examples go through `normalize + overlay_credit` and the output plays cleanly in VLC with the overlay visible at the top-left throughout, never occluded by IG Reels chrome in a side-by-side comparison screenshot.
- A deliberately-broken test case (font path wrong) is caught by the post-overlay probe and raised, not swallowed.

### Phase 5: Approval + publish path

- [ ] **Unit 9: Extend send_approval_preview for curation kind + static images**

**Goal:** Make the Telegram preview handler work for both generation and curation approvals, and for both video and static-image candidates.

**Requirements:** R5, R6

**Dependencies:** Unit 1, Unit 7, Unit 8

**Files:**
- Modify: `sidecar/telegram_bot.py` (extend `send_approval_preview` with an optional `kind` keyword; branch on `media_type` for `send_photo` vs `send_video`)
- Modify: `sidecar/pipeline_runner.py` — the existing call site at line ~451 calls `send_approval_preview(app, run_id)`; this continues to work via the backwards-compatible signature
- Modify: `sidecar/tests/test_telegram_bot.py` — existing tests that pass `(app, int)` continue to work via the default `kind="generation"`; add new tests for `kind="curation"`
- Modify: `sidecar/db.py` (add `get_curation_candidate` helper paralleling `get_pipeline_run`)
- Test: `sidecar/tests/test_telegram_preview_curation.py`

**Approach:**
- **Backwards-compatible signature** (P1-E3 — feasibility reviewer caught that changing the positional signature breaks existing callers in pipeline_runner.py and its tests): the new signature is `send_approval_preview(app, target_id, *, kind="generation")`. Existing positional calls `send_approval_preview(app, run_id)` keep working. Curation call sites pass `send_approval_preview(app, candidate_id, kind="curation")`.
- When `kind="generation"`, reads from `pipeline_runs` (current behavior).
- When `kind="curation"`, reads from `curation_candidates` via the new `get_curation_candidate` helper.
- For image candidates, use `bot.send_photo` with the thumbnail; for video candidates, reuse the existing `_extract_preview_clip` logic.
- Inline keyboard callback data gains a `kind` prefix: `"approve:curation:42"` vs `"approve:generation:17"`. Generation-track callback data (which today has no prefix) is read with a default fallback: if the callback data has no colon prefix, it's treated as a generation callback with the existing int-only shape.
- `create_approval` gains an optional `kind="generation"` keyword, default preserves behavior.
- **Information architecture of the curation preview message** (P1-O4 — design-lens review): the Telegram message body is structured deliberately so the owner can decide in ~30 seconds:
  ```
  🎯 {score:.2f}  [TRUSTED ✓ | REVIEW]  {source}
  @{author_handle} · {caption_seed truncated to 120 chars}
  ⚠ {flags}       ← only shown if watermark_hint OR classifier_unavailable OR novelty<0.5
  ─────────
  {our_intro_line}
  via @{author_handle} · {source_platform}
  {source_url}
  ```
  The score + trust indicator is line 1 because it's the primary decision cue. Caption seed is line 2. Flags are conditional line 3. The proposed final caption (what will actually post) is below a separator.
- **T-2h warning digest format:** one message per slot, not one per candidate. Body:
  ```
  ⚠ Slot fires in 2h — 3 unreviewed candidates

  1. 🎯 0.82 [TRUSTED ✓] hackernews  — "Top of HN right now — ..."
  2. 🎯 0.71 [REVIEW]    reddit      — "Spotted on r/LocalLLaMA — ..."
  3. 🎯 0.64 [REVIEW]    huggingface — "Trending on Hugging Face: ..."

  Tap any line to see full preview.
  ```

**Patterns to follow:**
- Existing `send_approval_preview` in `sidecar/telegram_bot.py`
- `sidecar/db.py::create_approval` — add `kind` param
- Existing Telegram inline button handlers in `sidecar/telegram_bot.py::handle_approve` for callback data routing

**Test scenarios:**
- Video candidate → Telegram message has video clip + curation-formatted caption + Approve/Reject/Edit buttons
- Image candidate → Telegram message has static photo + caption + buttons
- Missing media_url → sends caption-only with a warning banner
- `kind="curation"` writes `approvals.kind = "curation"`
- Callback data includes the kind prefix for curation, no prefix for generation
- **Backwards compatibility:** old-style `send_approval_preview(app, run_id)` from pipeline_runner.py still works (kind defaults to generation)
- **Backwards compatibility:** existing tests in `test_telegram_bot.py` that use the old signature still pass without modification
- T-2h digest message renders all unreviewed candidates for the upcoming slot, ordered by score descending
- Telegram "kind" routing on the callback handler: `approve:curation:42` routes to curation_publish_action, `approve:42` (no kind prefix) routes to generation publish_action

**Verification:**
- Manual end-to-end: inject a curation_candidate, call `send_approval_preview(app, <id>, kind="curation")`, verify photo/video message arrives with working buttons.
- Regression: existing generative-track preview (from pipeline_runner.py success path) still arrives in Telegram correctly after the signature change.

---

- [ ] **Unit 10: Extend approvals_api for curation kind**

**Goal:** Route `approvals_api.approve/reject/edit_caption` based on the `kind` discriminator. Curation approvals trigger the new curation publish path instead of the generative one.

**Requirements:** R5

**Dependencies:** Unit 9

**Files:**
- Modify: `sidecar/routes/approvals_api.py` (branch on `approvals.kind`; curation → `curation_publish_action`, generation → existing `publish_action`)
- Modify: `sidecar/telegram_bot.py` (handle_approve / handle_reject callback routing follows the same branching)
- Create: `sidecar/jobs/curation_publish.py` (new publish_action variant for curation candidates, thin wrapper around the existing publish path)
- Modify: `sidecar/runtime.py` (add a new module-level `nas_heavy_work_lock: asyncio.Lock` singleton — see the shared NAS mutex decision in Key Technical Decisions)
- Modify: `sidecar/jobs/run_pipeline.py` (replace the local `_pipeline_lock` with `sidecar.runtime.nas_heavy_work_lock` so the existing generative track acquires the same shared lock curation now needs)
- Test: `sidecar/tests/test_approvals_api_curation.py`
- Test: `sidecar/tests/test_nas_heavy_work_lock.py` (covers mutual exclusion between generative and curation heavy work)

**Approach:**
- `curation_publish_action(candidate_id)` loads the candidate, then **acquires `sidecar.runtime.nas_heavy_work_lock`** before running `normalize + overlay_credit`, then calls `PostizClient.publish_post` with curation-specific caption + integration IDs. The lock is released after the Postiz upload completes (not after the scheduled slot fires — Postiz's own queue handles that part). The publish leg is IDENTICAL to generation from Postiz's perspective — only the caption source and media source differ.
- **Shared NAS mutex contract:**
  - Both `sidecar/jobs/run_pipeline.py::process_pending_runs` (generative) and `sidecar/jobs/curation_publish.py::curation_publish_action` (curation) acquire the same `nas_heavy_work_lock` from `sidecar.runtime`.
  - Lock scope covers ONLY the heavy work — for generative, the `pipeline_runner` subprocess call; for curation, the `normalize + overlay_credit + upload` chain. Everything else (scoring, Telegram previews, DB writes, scheduling) runs lock-free so neither track starves the other on lightweight operations.
  - Lock acquisition is non-blocking at the scheduler level: if the lock is held when a tick fires, the caller returns a `busy` result and the scheduler's next tick retries. For generative (interval 30s) this just delays the run by one tick. For curation publish (one-shot at slot time), the curation_publish_action retries via APScheduler's built-in `misfire_grace_time=300` window — plenty of time to wait for a generative run to finish.
  - Lock ordering is deterministic (always the same module-level singleton, no nested locks) so deadlock is impossible by construction.
- **Full candidate status lifecycle** (P1-O3, coherence review — original plan's `pending → approved → published` skipped the edit-and-re-review cycle):
  ```
  pending           — surfaced in Telegram, awaiting owner decision
    ├── rejected    — owner tapped Reject; terminal
    ├── edit_pending_review — owner tapped Edit, submitted new caption; preview re-fires in Telegram, returns to pending on next message send
    ├── approved    — owner tapped Approve OR autopilot auto-approved
    │     └── publishing — normalize + overlay + Postiz call in flight (uniqueness claim)
    │           ├── published       — Postiz accepted; terminal-success
    │           └── failed_publish  — Postiz rejected or overlay probe failed; terminal-failure with error reason
    ├── skipped_slot  — autopilot evaluated and chose not to fire (no eligible candidate); terminal
    └── removed_opt_out — post was published then deleted per opt-out; terminal, distinct from failed_publish for audit purposes
  ```
- **Edit flow:** `edit_caption` endpoint updates `final_caption`, sets status back to `pending`, sets `edit_count += 1`, and re-fires `send_approval_preview` so the owner sees the updated version. `edit_count` is surfaced in the Telegram preview so the owner knows this is an edited re-send.
- **Publishing state as uniqueness claim** (P1-E4 / adversarial slot-race): before dispatching the ffmpeg+Postiz chain, update the row to `status='publishing'` via a WHERE-status='approved' UPDATE. If zero rows affected, another worker already claimed this candidate — log and abort. This prevents autopilot and owner-approve racing to fire the same slot.
- Scheduler job ID prefix `curation_publish_<candidate_id>` so the existing misfire_grace and duplicate-job handling work cleanly.

**Patterns to follow:**
- `sidecar/jobs/publish.py::publish_action` — near-verbatim reuse for the Postiz side
- `sidecar/routes/approvals_api.py::approve` — existing handler shape

**Test scenarios:**
- POST `/approvals/{id}/approve` on a curation-kind approval → `curation_publish_action` scheduled
- POST `/approvals/{id}/approve` on a generation-kind approval → existing `publish_action` scheduled (regression safety)
- Reject on curation → candidate status flips to `rejected`
- Edit caption on curation → `final_caption` updated, publish not yet fired
- **NAS mutex — concurrent generation + curation:** fake a running generative subprocess (holds `nas_heavy_work_lock`), fire `curation_publish_action` → it waits for the lock (does not crash, does not race). When the generative call releases, curation proceeds.
- **NAS mutex — concurrent curation + curation:** two curation candidates approved back-to-back → second waits for the first's lock release, both eventually publish.
- **NAS mutex — misfire_grace_time covers the wait:** generative run that holds the lock for 6 minutes does not cause curation_publish_action to miss its Postiz slot; curation catches up within the 300-second misfire window.

**Verification:**
- Manual end-to-end: approve a curation candidate via API, watch Postiz receive a new post in QUEUE state with the curated caption and media.
- NAS mutex regression: approve a curation candidate while a generative run is in flight, confirm (via sidecar logs) that curation waits for the generative subprocess to finish before ffmpeg starts.

---

- [ ] **Unit 11: Track-aware slot allocation**

**Goal:** `compute_next_slot` becomes track-aware so generative posts always take the evening peak and curation posts rotate through morning/lunch/evening-2.

**Requirements:** R7, R8

**Dependencies:** Unit 1

**Files:**
- Modify: `sidecar/jobs/publish.py` (extend `compute_next_slot` with an optional `track` parameter; add a helper `next_curation_slot(now)` that inspects which curation slots have already fired today)
- Modify: `sidecar/jobs/curation_publish.py` (use `next_curation_slot`)
- Modify: `sidecar/config.py` (add `PIPELINE_SLOT_LUNCH`, `PIPELINE_SLOT_EVENING_2` defaults)
- Test: `sidecar/tests/test_slot_allocation_curation.py`

**Approach:**
- **New slot assignment** (R8 + P1-E2):
  - Curation owns: `PIPELINE_SLOT_MORNING` (default 09:00), `PIPELINE_SLOT_LUNCH` (default 13:00), `PIPELINE_SLOT_EVENING_2` (default 21:00)
  - Generative owns: `PIPELINE_SLOT_EVENING` (default 19:00, unchanged) **exclusively**
- **Breaking change to generative track:** today's `compute_next_slot` in `sidecar/jobs/publish.py` returns next of 09:00 or 19:00 — generative uses BOTH. After Unit 11, **generative loses its 09:00 slot.** The feasibility reviewer caught this as an implicit semantic shift; it's now explicit.
  - Migration: any currently-queued generative run scheduled for today 09:00 is moved to today 19:00 or tomorrow 19:00 by a one-shot migration helper `_migrate_existing_generative_09_to_19()`. Called once at sidecar startup after the Unit 11 rebuild; guarded by a migration-run flag in the settings table so it only fires once ever.
  - Regression test: after migration, no generative run has a scheduled_slot at 09:00.
- `next_curation_slot(now, db_conn)` queries `curation_slot_log` (from Unit 1) for today's fired slots and picks the next unused slot; falls back to tomorrow's morning if all three curation slots fired. The slot_log is the authoritative source of "did this slot fire yet" because a candidate can be in `publishing` state without yet appearing in `published` status.
- `compute_next_slot(track, now)` where `track` is `"generation"` or `"curation"`:
  - `"generation"` → always `PIPELINE_SLOT_EVENING`, either today if `now < slot`, else tomorrow
  - `"curation"` → delegates to `next_curation_slot`
- **Skipped slot semantics** (P1-O1): Unit 12's autopilot calls `log_slot_skip(slot_time, reason)` which writes a row to `curation_slot_log` with `fired=False`. The next day's `next_curation_slot` does NOT try to back-fill yesterday's skipped slots. Weekly cap is a soft target: a skipped slot is zero posts that day, full stop.
- **Weekly cap enforcement:** before returning a slot, count how many curation posts have been published this ISO week. If ≥ `CURATION_WEEKLY_CAP_PER_PLATFORM`, return None and log "weekly cap reached" — the caller demotes the candidate to `rejected` with reason `weekly_cap`. Skipped slots do NOT count against the cap.

**Patterns to follow:**
- Existing `compute_next_slot` in `sidecar/jobs/publish.py`
- Existing settings-table migration pattern in `sidecar/db.py::_apply_column_migrations`

**Test scenarios:**
- Morning call at 08:30 for curation → next slot = today 09:00
- Morning call at 10:00 for curation → next slot = today 13:00
- All three curation slots fired → next slot = tomorrow morning
- Weekly cap reached → returns None, caller handles it
- `compute_next_slot("generation")` at 08:30 → today 19:00 (not 09:00 — the regression test guarding the slot migration)
- `compute_next_slot("generation")` at 20:00 → tomorrow 19:00
- Existing generative run queued at today 09:00 → migrated to today 19:00 on first startup, migration flag set, subsequent startups don't re-migrate
- Skipped slot yesterday → next_curation_slot today does NOT include yesterday's skipped slot
- Skipped slots do not count against weekly cap

**Verification:**
- Unit tests cover all 8 permutations of "which slot is next given current time + today's slot_log state".
- Generative track regression test: running `compute_next_slot("generation")` at any time returns only the evening slot, never 09:00.
- Migration helper runs once, leaves a `generative_09_slot_migrated=true` row in settings, and is idempotent on rerun.

---

- [ ] **Unit 12: T-2h warning + T-30min autopilot**

**Goal:** Ship the graceful-degradation fallback described in R9 / R10 / R11.

**Requirements:** R9, R10, R11

**Dependencies:** Unit 3, Unit 10, Unit 11

**Files:**
- Create: `sidecar/jobs/curation_autopilot.py` (exposes `run_autopilot_tick()` that scans upcoming slots and fires warnings/auto-approves)
- Modify: `sidecar/app.py` (register a 5-minute interval job for `curation_autopilot`, gated by the same `SIDECAR_CURATION_TRIGGER_ENABLED` flag)
- Test: `sidecar/tests/test_curation_autopilot.py`

**Approach:**
- Runs every 5 minutes. On each tick, inspects the next curation slot (via `next_curation_slot`) and the set of pending/unreviewed candidates.
- **T-2h:** fire one Telegram message listing unreviewed candidates for the upcoming slot (digest format, per Unit 9). Use a dedupe flag on the slot (`warned_at` timestamp in `curation_slot_log`) to avoid re-warning every 5 minutes.
- **T-30min:** pick the highest-scored unreviewed candidate where ALL of the following hold (narrowed eligibility per R11, adversarial review, P1-E4):
  1. `score ≥ CURATION_AUTOPILOT_SCORE_FLOOR` (default 0.70)
  2. `source` is in `trusted_sources_set` (starts empty — owner adds per-source manually after 1 week of manual approvals from that source)
  3. **`source_is_original_publisher == True`** — each `ContentSource` implementation sets this field on every candidate it emits. arXiv source sets it to `True` only if the uploading author is in the paper's author list. HF trending sets it to `True` only if the model owner matches a known-good creator pattern. Aggregator sources (HN front-page links to third-party content) set it to `False`. This is the fix for the adversarial review's "HN-trusted ≠ third-party tweet screenshot is safe to repost" finding.
  4. **Safety re-classification passes at T-30min** — Unit 5's `classify_safety` is re-run on the candidate before auto-approve (threat model T3 mitigation). Cached verdicts are explicitly ignored for the autopilot path.
- If an eligible candidate is found, auto-approve it (create an approvals row with `kind="curation"`, `status="auto_approved"`) and invoke `curation_publish_action` immediately.
- If NO candidate satisfies the gate, log `log_slot_skip(slot_time, reason="no_eligible_candidate")` to `curation_slot_log` and **do not fire the slot**. Never lower the bar to hit volume. A Telegram notification `🚫 Slot skipped: {reason}` is sent to the owner so the skip is visible.
- **Slot claim / race avoidance** (P1-O8, feasibility review): before invoking `curation_publish_action`, the autopilot atomically updates the candidate row to `status='publishing'` via a conditional UPDATE (`WHERE status='approved' AND id=?`). If zero rows affected, another worker already claimed this candidate — log and abort. Same pattern as Unit 10's publishing-state claim.

**Patterns to follow:**
- `sidecar/jobs/publish.py::schedule_auto_approve` — the generative-track autopilot, similar shape
- `sidecar/app.py` for the interval job wire-up

**Test scenarios:**
- T-3h: nothing fires
- T-2h: warning sent once, slot_log entry gains warned_at
- T-2h same tick again: no duplicate warning
- T-30min + eligible candidate (score ≥ 0.70, trusted source, original_publisher=True, safety re-classified pass): auto-approved and scheduled
- T-30min + all candidates have source_is_original_publisher=False: slot skipped with reason=`no_original_publisher`
- T-30min + all candidates from untrusted sources: slot skipped with reason=`no_trusted_source`
- T-30min + trusted candidates all score < 0.70: slot skipped with reason=`no_high_score_candidate`
- T-30min + highest-scored candidate re-classifies to reject at T-30min (source content changed in cache window): candidate marked rejected, autopilot picks next eligible candidate
- T-30min race: autopilot tries to claim a candidate the owner just approved manually via API — claim UPDATE affects 0 rows, autopilot aborts cleanly, owner's approval wins
- Scheduler missed a tick (misfire): `misfire_grace_time=300` catches it

**Verification:**
- Simulated timeline tests cover all branches.
- Live manual test: inject a trusted-source candidate with score 0.85 and `source_is_original_publisher=True`, don't review, confirm auto-approval fires at T-30min.
- Live manual test: inject an HN front-page candidate with score 0.90 but `source_is_original_publisher=False`, don't review, confirm autopilot skips the slot and sends a "slot skipped: no_original_publisher" Telegram notification.

### Phase 6: Wave 2 RSS sources

- [ ] **Unit 13: Generic RSS source + ArXiv + Lobste.rs + Product Hunt + Substack pool**

**Goal:** Ship Wave 2. All five sources share the same underlying RSS parser, so we build one generic helper and thin wrappers for each.

**Requirements:** R2 (Wave 2)

**Dependencies:** Unit 1

**Files:**
- Modify: `sidecar/pipeline_requirements.txt` (add `feedparser==6.*` — it's ~50KB, negligible)
- Create: `sidecar/content_sources/rss_source.py` (exposes a reusable `fetch_rss(url, max_items) -> list[candidate_dict]` helper)
- Create: `sidecar/content_sources/substack_pool.py` (reads `SUBSTACK_FEEDS` env CSV, calls `fetch_rss` per feed, merges)
- Create: `sidecar/content_sources/arxiv_source.py` (wraps `fetch_rss` over `http://export.arxiv.org/rss/cs.AI` and `cs.CL`)
- Create: `sidecar/content_sources/lobsters_source.py` (wraps `fetch_rss` over `https://lobste.rs/rss`)
- Create: `sidecar/content_sources/producthunt_source.py` (RSS at `https://www.producthunt.com/feed`)
- Modify: `sidecar/content_sources/__init__.py` (register the four wrappers)
- Modify: `sidecar/config.py` (`SUBSTACK_FEEDS`, `ARXIV_CATEGORIES`, per-source enablement)
- Test: `sidecar/tests/test_rss_source.py` (uses a local XML fixture)
- Test: `sidecar/tests/test_substack_pool.py`
- Test: `sidecar/tests/test_arxiv_source.py`
- Test: `sidecar/tests/test_lobsters_source.py`
- Test: `sidecar/tests/test_producthunt_source.py`

**Approach:**
- `fetch_rss` takes a URL, HTTP-gets with httpx, parses with feedparser, maps each entry to the `ContentSource` candidate dict shape.
- Substack pool iterates a CSV env var and calls `fetch_rss` per feed. Merges with per-feed failure isolation.
- arXiv items: extract abstract as `caption_seed`, paper URL as `source_url`, first author as `author_handle`. No native media — media_type = `none` (classifier still surfaces the candidate for generative commentary, but the normalizer skips anything with `media_type=none` during publish).
- Lobste.rs items: similar to arXiv, no native media. First commenter's comment could seed caption but out of scope.
- Product Hunt items: RSS includes a thumbnail URL in the description's HTML — parse with BeautifulSoup (already in pipeline venv).

**Patterns to follow:**
- Unit 4's per-source pattern
- `sidecar/topic_sources/hackernews_source.py` for the httpx shape

**Test scenarios (per source):**
- Fixture feed → expected candidate list
- Malformed XML → returns `[]`
- Empty feed → returns `[]`
- Per-source media handling (PH has images, arXiv doesn't)

**Verification:**
- Full-day dry run with Waves 1+2 enabled collects candidates from all 8 sources.

### Phase 7: Wave 3 auth sources

- [ ] **Unit 14: Instagram creator source (Meta Graph scrape)**

**Status: OUT OF v1 SCOPE** — the original "creator scraping" approach has no Meta Graph API surface as of 2026 (see Scope Boundaries). This unit is preserved as a placeholder for a future spike on owner-owned-account reshare flow, and does not ship in v1.

**If revisited in a future scope:** the viable approach is NOT creator scraping — it's reshare of content from a saved-collection inside an owner-owned IG account (creators the owner personally follows and saves). That flow uses `instagram_business_basic_display` or saved-media endpoints that ARE available via App Review.

**Replacement work in v1:** The candidate pool that was going to come from Instagram is replaced by tightening the Wave 1-2 sources + the TOS-review-blessed subset. If the TOS review leaves the source list too thin, revisit this with the owner-owned saved-collection approach as the target, NOT the original creator-scraping design.

**Files (DEFERRED — do not create in v1):**
- ~~`sidecar/content_sources/instagram_source.py`~~
- ~~`sidecar/content_sources/instagram_creators.json`~~

---

- [ ] **Unit 15: X List source**

**Goal:** Fetch tweets from a curated X List via X API v2.

**Requirements:** R2 (Wave 3)

**Dependencies:** Unit 1, X bearer token (user-action prerequisite)

**Files:**
- Create: `sidecar/content_sources/x_source.py`
- Modify: `sidecar/content_sources/__init__.py`
- Modify: `sidecar/config.py` (`X_BEARER_TOKEN`, `X_LIST_IDS`)
- Test: `sidecar/tests/test_x_source.py`

**Approach:**
- `GET https://api.x.com/2/lists/{id}/tweets?tweet.fields=attachments,public_metrics,created_at&expansions=author_id,attachments.media_keys&media.fields=url,preview_image_url&max_results=50`
- Filter to last 24 hours.
- Prefer tweets with attached media. Text-only tweets: only keep if retweet_count + like_count crosses a threshold (configurable).
- `is_configured` returns False if `X_BEARER_TOKEN` or `X_LIST_IDS` are empty.

**Patterns to follow:**
- Unit 4's source pattern
- httpx bearer token header shape

**Test scenarios:**
- Valid bearer + list → returns candidate list
- 401 invalid token → returns `[]`, logs clearly
- 429 rate limit → returns `[]`, does not retry aggressively
- Text-only tweet above threshold → surfaced
- Text-only tweet below threshold → dropped

**Verification:**
- Live: once bearer token + list ID are provided, dry-run fetch returns real tweets.

---

- [ ] **Unit 16: YouTube trending source**

**Goal:** Fetch trending videos in the Science & Technology category via YouTube Data API v3.

**Requirements:** R2 (Wave 3)

**Dependencies:** Unit 1, existing Postiz YouTube OAuth (already wired — no user action needed)

**Files:**
- Create: `sidecar/content_sources/youtube_trending_source.py`
- Modify: `sidecar/content_sources/__init__.py`
- Modify: `sidecar/config.py` (`YOUTUBE_TRENDING_CATEGORY_ID=28`, `YOUTUBE_TRENDING_MAX_RESULTS=20`)
- Test: `sidecar/tests/test_youtube_trending_source.py`

**Approach:**
- `videos.list?chart=mostPopular&videoCategoryId=28&maxResults=20&part=snippet,statistics`
- Map each result to a `ContentSource` dict: `title`, `channel name → author_handle`, `video URL → source_url`, `thumbnail → media_url (image)`, `viewCount → engagement`.
- **Important:** YouTube content is NEVER downloaded and reuploaded. media_type is `image` (just the thumbnail). Curation posts for YT trending act as "watch this" callouts with the thumbnail + a pointer to the video. Full reaction videos remain a generative-track concern.
- Credit policy is strict: the video URL goes in the caption, the channel name is tagged, and the post is framed as "spotted on YouTube today".

**Patterns to follow:**
- Existing YouTube client wrapper in `sidecar/` (if one exists, else use `google-api-python-client` directly — already in pipeline venv)

**Test scenarios:**
- Valid call → 20 results with thumbnails
- Category 28 filter applied → no non-tech videos leak through
- Missing OAuth → `is_configured=False`
- 403 quota exceeded → returns `[]`, logs clearly

**Verification:**
- Live: run fetch, verify 20 valid candidates each with a thumbnail URL and channel name.

### Phase 8: Opt-out system

- [ ] **Unit 17: Denylist DB + unified opt-out processor + 24h removal job**

**Goal:** One denylist table, one processor that every opt-out channel feeds into, and a job that takes down published posts within 24h of an opt-out landing.

**Requirements:** R14, R14 subclauses

**Dependencies:** Unit 10 (for the publish path and post_ids_json lookup)

**Files:**
- Create: `sidecar/content_curation/denylist.py` (exposes `add(handle, source, reason, evidence)`, `is_denied(handle, source)`, `list_active()`)
- Modify: `sidecar/db.py` (new `creator_denylist` table + helpers)
- Create: `sidecar/jobs/opt_out_processor.py` (exposes `process_opt_out(handle, source, reason)` — adds to denylist, queues the 24h removal job for any published posts by that creator)
- Create: `sidecar/jobs/opt_out_remover.py` (fires immediately on new denylist entries; calls Postiz delete for every `curation_candidates.postiz_post_ids_json` row that matches)
- Modify: `sidecar/app.py` (wire both jobs into the scheduler)
- Test: `sidecar/tests/test_denylist.py`
- Test: `sidecar/tests/test_opt_out_processor.py`

**Approach:**
- **Denylist row shape:** `(id, handle, source, reason, evidence_url, added_at, expires_at, reversed_at, removed_posts_count)`. `expires_at` default is `added_at + CURATION_DENYLIST_RETENTION_DAYS` (default 730 = 2 years, per R16/P1-O6). Reversal is a soft-delete via `reversed_at` so the audit trail remains.
- **Blocking prerequisite: Postiz `delete_post` research spike** (Pre-Phase 1). This unit cannot start until the spike identifies the removal mechanism:
  - **Option A (preferred):** `PostizClient.delete_post(post_id)` via a newly-added method that calls `DELETE /api/public/v1/posts/:id` (if the endpoint exists in the running Postiz build). Research artifact: spike confirms endpoint exists + documents the success and error responses.
  - **Option B (fallback):** per-platform delete using the existing credentials:
    - Instagram: `DELETE https://graph.facebook.com/v20.0/{ig-media-id}?access_token=<token from Postiz postgres integration row>` — the token already exists in the Postiz postgres for publishing
    - YouTube: `videos.delete` via `google-api-python-client` with the existing Postiz YT OAuth credentials
  - The spike's output goes in Unit 17's approach section before implementation starts.
- Removal job: query `curation_candidates` for rows with matching `author_handle` + `source` + `status='published'`, call the chosen delete mechanism for each, update candidate status to `removed_opt_out` with `removed_at` timestamp. Never raises — failures are logged + retried on next job tick.
- **Denylist retention job:** daily cron at 04:00 calls a cleanup query `DELETE FROM creator_denylist WHERE expires_at < now() AND reversed_at IS NULL` — handles the 2-year TTL (P1-O6, GDPR right-to-erasure path). Additionally, a manual dashboard action (Unit 19) exposes "remove from denylist" for ad-hoc reversal.
- `scorer.py` consults the denylist via `is_denied(handle, source)` which joins on `WHERE reversed_at IS NULL AND expires_at > now()`. Reversed or expired entries no longer block future scraping.

**Patterns to follow:**
- `sidecar/jobs/publish.py` for scheduler job shape + failure isolation
- `sidecar/db.py` column migration pattern
- Existing `sidecar/postiz_client.py::publish_post` shape for adding `delete_post` (if Option A)
- Existing `sidecar/ig_direct.py` for Meta Graph API call shape (if Option B for IG)

**Test scenarios:**
- New opt-out → creator added to denylist, any published posts deleted via the chosen mechanism, candidate rows marked
- Duplicate opt-out → no-op, no crash
- Denylisted creator scraped again → `is_denied=True` short-circuits scoring
- Expired denylist entry → cleanup job removes the row, creator becomes scrapable again
- Reversed denylist entry → `is_denied=False`, but audit row preserved
- Postiz/Meta/YT delete 5xx → job retries on next tick, logs clearly, candidate eventually transitions to `removed_opt_out` once successful
- **If Option A:** `PostizClient.delete_post(<nonexistent-id>)` → 404, logged, candidate row is still marked `removed_opt_out` with a `notes='already_deleted_at_source'` flag (idempotent cleanup)

**Verification:**
- Pre-Phase 1 spike result is documented in this unit's approach section.
- Manual end-to-end: publish a test curation post, add the creator to the denylist, confirm the post is deleted via the chosen mechanism and the candidate row flips to `removed_opt_out`.
- Retention job: insert a denylist row with `expires_at = now() - 1 day`, run cleanup, row is gone.

---

- [ ] **Unit 18: Two automated opt-out channels + universal human confirmation**

**Goal:** Ship the two automated inbound opt-out pollers (email IMAP + Google Form). Both feed a unified `process_opt_out` handler that **never auto-processes** — every submission requires owner confirmation via Telegram before the denylist entry is created (R14a, threat model T1 mitigation).

IG DM opt-outs are a **manual channel** — the owner reads DMs in the Instagram app and forwards any opt-out messages to the Google Form themselves. See Scope Boundaries for why IG DM polling is out of scope.

**Requirements:** R14, R14a, R14b, R14c, R14d

**Dependencies:** Unit 17

**Files:**
- Create: `sidecar/jobs/opt_out_email_poller.py` (IMAP connection to the dedicated opt-out mailbox via `imaplib` stdlib, scan UNSEEN messages, extract sender + subject/body, fire Telegram confirmation for owner to verify before `process_opt_out`)
- Create: `sidecar/jobs/opt_out_form_poller.py` (Google Form responses via public CSV export URL — no OAuth, sheet is world-readable by design since it's behind a Google Form, poll every 15 minutes, fire Telegram confirmation for new rows)
- Create: `sidecar/jobs/opt_out_confirmation.py` (Telegram inline keyboard handler for the Confirm/Reject buttons that appear on every opt-out confirmation message; on Confirm, calls `process_opt_out`; on Reject, marks the `opt_out_events` row as `rejected`)
- Modify: `sidecar/telegram_bot.py` (register the new Confirm/Reject callback handlers)
- Modify: `sidecar/app.py` (register the two pollers at 15-min intervals, each gated behind its own enable flag: `OPT_OUT_EMAIL_ENABLED`, `OPT_OUT_FORM_ENABLED`, tolerant of missing credentials)
- Modify: `sidecar/config.py` (poller settings: IMAP host/user/pass from Docker secrets NOT `.env`, Google Form public CSV URL, per-submitter rate-limit config)
- Test: `sidecar/tests/test_opt_out_email_poller.py`
- Test: `sidecar/tests/test_opt_out_form_poller.py`
- Test: `sidecar/tests/test_opt_out_confirmation.py`

**Approach:**
- **Universal confirmation flow (T1 mitigation — adversarial opt-out spam):**
  Every inbound opt-out, regardless of channel, goes through the same 3-step flow:
  1. Poller detects a new inbound message
  2. Poller writes a row to `opt_out_events` with status `pending_confirmation` + the raw submitter metadata + the parsed handle/source guess
  3. Poller sends a Telegram message: *"⚠ Opt-out request from @handle on <source> via <channel>: <snippet>. Tap Confirm to add to denylist, Reject to dismiss."* with inline Confirm/Reject buttons. The callback handler is the ONLY path that calls `process_opt_out` from Unit 17.
- **Rate limiting per submitter** (R14c): before creating an `opt_out_events` row, check the count of `opt_out_events` rows with the same `submitter_identity` in the last 24 hours. If ≥3, silently drop the new submission and log a warning (prevents spam floods from drowning the owner's Telegram in confirmation messages). For email, `submitter_identity` is the sending domain (not the full address — easy to spoof the full address). For Google Form, `submitter_identity` is the form's respondent email if the form is set to collect emails, else a sentinel "form_anonymous".
- **Email poller:**
  - Uses Python stdlib `imaplib` (no new dep) to avoid module bloat
  - Dedicated opt-out mailbox (not an alias forwarding to the primary inbox) so credential compromise limits blast radius
  - Credentials live in `/secrets/opt_out_imap.json` (Docker-secret style mount), NOT `.env`
  - Naive extraction: handle from `From:` + regex-scan the subject/body for `@handle` and `reddit.com|x.com|hackernews` pattern; on ambiguity, the Telegram confirmation shows the full body for owner to disambiguate
- **Form poller:**
  - Reads Google Form responses via the public CSV export URL (form is world-readable by design, anyone with the link can submit, the CSV export is a convenient poll surface)
  - One row per submission with fields: `timestamp`, `submitter_email` (if form collects), `handle`, `source`, `reason_text`
  - Idempotency via the row's `timestamp` field — tracked in a new `opt_out_form_last_seen_at` setting row
- **Acknowledgement loop (R14d, P1-O7):** after the owner confirms a denylist entry, the channel-specific poller sends a receipt:
  - Email: auto-reply "Your opt-out request has been received and processed. Any affected posts will be removed within 24 hours."
  - Form: confirmation email if the form collected the submitter's email; otherwise no outbound ack (the form's built-in "thank you" page serves as the initial receipt)
- **Acknowledgement on reject:** if the owner taps Reject, no external ack is sent (silence is correct — rejecting is for spam, false positives, and unverified submissions; an ack would confirm to the spammer that their submission was received and dropped).

**Patterns to follow:**
- `sidecar/jobs/health_ping.py` for polling-job shape and per-service try/except isolation
- Existing Telegram inline keyboard handlers in `sidecar/telegram_bot.py` for the Confirm/Reject callback pattern

**Test scenarios (per channel):**
- Valid opt-out email → `opt_out_events` row created with `pending_confirmation`, Telegram message sent
- Spoofed email from same domain ≥3 times in 24h → rate-limited, dropped with log
- Email with ambiguous handle → Telegram confirmation shows full body
- New Google Form submission → `opt_out_events` row + Telegram confirmation
- Duplicate form submission (same timestamp) → no-op, idempotent
- Owner taps Confirm → `process_opt_out` called, denylist entry created, auto-reply sent
- Owner taps Reject → `opt_out_events.status` flipped to `rejected`, no denylist change, no external ack
- Owner ignores Telegram message for 48h → entry stays `pending_confirmation`, re-surfaced in daily review report
- Unconfigured IMAP credentials → poller skips with clear log, `is_configured=False` on startup check
- Unconfigured Google Form URL → poller skips with clear log
- Dashboard admin "remove from denylist" action (Unit 19) → `creator_denylist.reversed_at` is set, entry no longer blocks scraping

**Verification:**
- Manual end-to-end per channel: send an inbound opt-out, watch the Telegram confirmation arrive, tap Confirm, watch the denylist entry land, confirm the auto-reply was sent.
- Adversarial test: send 5 opt-out emails from the same fake domain targeting different handles within an hour → only the first 3 create `opt_out_events` rows, the rest are dropped with rate-limit logs.

### Phase 9: Dashboard, observability, engagement

- [ ] **Unit 19: Curation dashboard view**

**Goal:** Add a Curation tab to the existing sidecar dashboard showing per-source counts, pending reviews, approved/rejected/published lists, and the denylist.

**Requirements:** R16

**Dependencies:** Unit 2, Unit 17

**Files:**
- Modify: `sidecar/routes/dashboard.py` (new `GET /dashboard/curation` route)
- Create: `sidecar/templates/dashboard_curation.html` (Jinja template mirroring existing `sidecar/templates/runs.html` layout)
- Create: `sidecar/routes/curation_api.py` (small JSON endpoints: `/curation/candidates?status=pending`, `/curation/denylist`, `/curation/source_status`)
- Test: `sidecar/tests/test_dashboard_curation_route.py`

**Approach:**
- Per-source status row: name, enabled, last fetch timestamp, last fetch candidate count, last error.
- Candidates list paginated by `status` filter.
- Denylist view with "remove from denylist" admin action (rarely needed but worth having).

**Patterns to follow:**
- Existing `sidecar/routes/dashboard.py` route handlers
- `sidecar/templates/runs.html` for the HTML/CSS shape

**Test scenarios:**
- Unauthenticated access → 401 (auth middleware already in place)
- Empty database → empty but valid tabs
- Pending candidates present → listed with thumbnails + scores + action buttons

**Verification:**
- Visit `/dashboard/curation` in a browser, see the three tabs (pending, published, denylist), interact with the buttons.

---

- [ ] **Unit 20: Post-hoc engagement logger**

**Goal:** 7 days after a curated post publishes, fetch its engagement metrics from Postiz (if supported) or directly from IG Graph / YT Data API, and log back to `curation_candidates.engagement_tracked_json` for future scorer tuning.

**Requirements:** R15, success criterion "compare curated vs generated engagement after 2 weeks"

**Dependencies:** Unit 17, research on Postiz analytics endpoint (deferred question from brainstorm)

**Files:**
- Create: `sidecar/jobs/curation_engagement_logger.py`
- Modify: `sidecar/app.py` (register a daily 03:00 cron that finds all `curation_candidates` published exactly 7 days ago and fetches their metrics)
- Modify: `sidecar/db.py` (add `get_candidates_published_on_date` helper)
- Test: `sidecar/tests/test_curation_engagement_logger.py`

**Approach:**
- **Research first:** check Postiz container for `/api/public/v1/posts/:id/metrics` or similar. If present, use it (one call per post). If not, fall back to direct Meta Graph + YT Data API queries — same pattern as `sidecar/ig_direct.py`.
- Persisted metrics: `likes`, `comments`, `shares`, `saves`, `reach`, `impressions` per platform per post.
- Log both the final scorer breakdown and the actual engagement so a future scorer audit can compute "correlation between our score and real engagement, per signal".

**Patterns to follow:**
- `sidecar/ig_direct.py` for direct Meta Graph calls
- `sidecar/jobs/publish.py` for scheduled job shape

**Test scenarios:**
- Post published 7 days ago → metrics fetched and logged
- Post published 6 days ago → skipped (too early)
- Post not yet published → skipped
- Post removed due to opt-out → skipped (status check)
- Postiz endpoint missing → fallback to direct platform APIs
- Platform API 403 → logged, retry on next day's tick

**Verification:**
- Run the job manually against a 7-day-old fixture candidate and confirm `engagement_tracked_json` is populated.

---

- [ ] **Unit 21: Weekly scoring review report**

**Goal:** Monday morning Telegram report summarizing last week's curation performance: posts per source, approve/reject rate, autopilot hit rate, avg score of approved vs rejected, top 3 and bottom 3 performing posts by actual engagement.

**Requirements:** R15, plan success criterion

**Dependencies:** Unit 20

**Files:**
- Create: `sidecar/jobs/curation_weekly_report.py`
- Modify: `sidecar/app.py` (cron Mon 10:00)
- Test: `sidecar/tests/test_curation_weekly_report.py`

**Approach:**
- Query the last 7 days of `curation_candidates` + their `engagement_tracked_json` (for posts old enough to have metrics).
- Produce a compact Telegram message (≤ 2000 chars so it renders in one bubble) with the summary stats.
- Link to the dashboard `/dashboard/curation` for drill-down.
- Zero external deps — just SQL + string formatting.

**Patterns to follow:**
- `sidecar/jobs/cost_report.py` (existing generative-track weekly report) — this mirrors its shape

**Test scenarios:**
- Normal week → report sent with correct counts
- Empty week (nothing published) → report notes "no curated posts this week"
- Telegram bot unavailable → logged, next week retries

**Verification:**
- Manual run on a week of fixture data produces a readable Telegram message.

## System-Wide Impact

- **Interaction graph:** new curation path attaches to 3 existing systems (`send_approval_preview`, `approvals_api`, `PostizClient.publish_post`). Each extension point is explicitly tested for regression on the generative track (same callbacks, different discriminator).
- **Error propagation:** every new job wraps an outer try/except and never raises out, matching the sidecar's "job handlers never crash the scheduler" rule. Media pipeline failures flip candidate status to `failed_publish` with the error captured in a new column, mirroring how `pipeline_runs.error_log` works.
- **State lifecycle risks:** curation candidates can be in 6 states (`pending`/`approved`/`rejected`/`published`/`failed_publish`/`removed_opt_out`). Every transition is logged. The denylist removal path must be idempotent because the cron runs every 15 min and a just-denylisted creator might have posts in various stages.
- **API surface parity:** new curation approve/reject endpoints mirror the generative ones verbatim on the HTTP surface — no new route prefix, just a `kind` query/body parameter. Keeps Telegram callback data parseable by one handler.
- **Integration coverage:** the generative track's end-to-end test from earlier this week (inject pipeline_run → watch video generate → auto-preview → approve → publish) gains a curation sibling (inject candidate → safety classify → score → preview → approve → normalize → overlay → publish).
- **External contract surfaces touched:** new env vars (`SIDECAR_CURATION_TRIGGER_ENABLED`, `CURATION_TRUSTED_SOURCES`, per-source knobs), new compose bind mount needs for `/app/assets/fonts/Inter-Black.ttf` (already mounted from the assets bind), new `/secrets` entries for X bearer token and opt-out email creds. Update the deploy skill doc.
- **Resource footprint on NAS:** 3 ffmpeg normalizations/day at ~1 min each = 3 minutes of CPU; ~1 Claude Haiku classifier call per candidate at ~300 candidates/day = ~30 sec of network; ~1 Sonnet scoring call per candidate surfaced at 10/day = ~10 sec. All well within the sidecar's existing headroom.
- **Concurrency bound with generative track:** the shared `nas_heavy_work_lock` from `sidecar.runtime` guarantees at most one NAS-heavy job runs at a time across both tracks. This bounds peak memory at ~2 GB (the generative ceiling, which dominates curation's ~500 MB) and peak CPU at ~4 cores. Without the mutex, a morning curation slot (09:00) could trigger ffmpeg while the previous day's generative run is still wrapping up, pushing the 8 GB NAS into swap and starving Postiz + Temporal + Postgres. The mutex scope is deliberately narrow — only the ffmpeg + upload chain, not scraping, scoring, or Telegram previews — so lightweight operations never block each other.
- **Parallel with generative track:** curation and generation share the same APScheduler instance, database file, Telegram bot application, and Postiz client. There is no isolation risk at the process level because the sidecar is single-process single-asyncio-loop by design.

## Risks & Dependencies

### Threat Model (new — surfaced during document review)

The curation track opens three specific attack surfaces not present in the generative track. Each must have a concrete mitigation wired into an implementation unit before `SIDECAR_CURATION_TRIGGER_ENABLED=1` flips.

**T1 — Opt-out spam / competitor takedown.** Most likely.

- *Attack:* Adversary mass-submits opt-outs via the public Google Form or via spoofed email (SPF/DKIM-unverified) impersonating creators we've reshared. Each submission auto-processes → 24h deletion of published posts + permanent denylist entry → visibility drop + inability to ever repost legitimate viral content from that creator.
- *Mitigation (wired into Unit 18 + R14a):* Every inbound opt-out, regardless of channel, fires a Telegram confirmation to the owner *before* the denylist entry is created. No auto-processing. Plus rate-limiting per submitter IP/email domain (max 3 submissions per day per submitter) and a reversible denylist with audit trail so bad entries can be rolled back.

**T2 — SSRF via attacker-controlled media URLs.** Highest impact.

- *Attack:* A Reddit self-post or scraped GitHub README contains an attacker-chosen `media_url` pointing at `http://192.168.29.211:9000/` (the NAS Portainer admin port) or `http://169.254.169.254/` (cloud metadata endpoint). The sidecar media_normalizer fetches it, pipes to ffmpeg, and either leaks internal network responses via error logs or probes the LAN.
- *Mitigation (wired into Unit 7 + R17):* All external URL fetches go through a safe-fetch helper (`sidecar/content_curation/safe_fetch.py`) that (a) resolves the hostname and rejects any address in RFC1918 / link-local / loopback / multicast ranges, (b) enforces `Content-Length` ≤ 50 MB and `Content-Type` in a strict allowlist (`video/mp4`, `image/jpeg`, `image/png`, `image/webp`, `video/quicktime`), (c) uses a 30-second timeout, (d) runs ffmpeg with `ulimit -t 120 -v 2000000` to cap CPU + memory.

**T3 — Classifier cache poisoning.** Most subtle.

- *Attack:* Safety classifier caches verdicts by `source_url` hash for 24h. Reddit, Substack, and Medium URLs are editable. Adversary posts benign content → gets `pass` verdict cached → edits the post to inflammatory / copyright-violating content → autopilot fires within the 24h cache window, bypassing the classifier entirely.
- *Mitigation (wired into Unit 5):* Cache key is a composite hash of `caption + media_url + source_last_edited_timestamp` where available, not `source_url` alone. Autopilot re-classifies at T-30min regardless of cache (the Haiku call is cheap — ~$0.0001 — and running it twice on a hot candidate is acceptable). Sources that don't expose a last-edited timestamp (HN, GitHub READMEs) fall back to content-hash invalidation.

### Operational Risks

- **Platform TOS non-compliance (see Pre-Phase 1 TOS Review Gate)** — the biggest external blocker. Multiple sources likely fall out of scope after review. Mitigation: the review is a blocking gate before Unit 4 starts.
- **Instagram scraping API surface does not exist** — Meta Graph has no endpoint for the scrape use case we planned. Mitigation: moved explicitly out of scope (see Scope Boundaries). Reverse only if an owner-owned-account reshare spike proves viable.
- **Postiz `delete_post` may not exist** — 24h removal guarantee depends on it. Mitigation: Pre-Phase 1 research spike identifies the mechanism (Postiz API or per-platform fallback) before Unit 17 starts.
- **Credit enforcement must be multi-layered, not a single if-check** — a single Python exception in the caption builder can be bypassed by any refactor. Mitigation: R12a-d now requires DB constraint + post-overlay probe + integration test + audit log. All four layers ship in v1.
- **Autopilot on trusted sources conflates source trust with content trust** — HN/arXiv are trusted *aggregators* but the media they link to is often third-party with unclear rights. Mitigation: R11 narrowed — autopilot eligibility now requires the source platform to be the original publisher of the content, not an aggregator link. arXiv PDFs by listed authors, HF Spaces by listed creators, and Product Hunt entries by the maker pass; HN front-page links do not.
- **20 posts/week cadence is unvalidated** — IG's 2024-2026 "unoriginal content" classifier penalizes high-volume reshare accounts. Mitigation: R7 now specifies ramp from 7-10/week to 20/week only after N clean weeks of IG reach metrics. The cap is a variable, not a constant.
- **Scorer cold-start has no tuning signal for 2-4 weeks** — the first weeks of real posts run against untuned weights. Mitigation: Unit 20 engagement logger ships alongside or before Unit 6 scorer so day-1 scoring has real feedback. Trusted-source set starts empty and is populated per-source only after 1 week of manual approval.
- **Owner review time budget** — 10 candidates/day × 2 min = ~2.3 hours/week just on curation approvals, against a 5-10 hr/week total time budget (CLAUDE.md). Mitigation: Unit 21 weekly report includes owner review time as a tracked metric; if it exceeds 3 hr/week for 2 consecutive weeks, R6 is narrowed to 5 candidates/day.
- **Claude Haiku classifier false-negatives** — a benign-looking item might slip through. Mitigation: the owner still reviews every candidate in Telegram; the classifier is a cost-saving pre-filter, not the only line of defense.
- **RSS feed churn** — Substack feeds can change URL without notice. Mitigation: U13's pool iterates with per-feed try/except; a dead feed is logged but doesn't break the run.
- **ffmpeg edge cases** — unusual codecs or malformed videos can hang the normalizer. Mitigation: `subprocess.run(..., timeout=120, start_new_session=True)` with process-group kill plus the ulimit-based sandbox from T2 mitigation.
- **Weekly cap interaction with autopilot** — if the cap is reached mid-week, autopilot skips remaining slots. Mitigation: U19 dashboard shows "this week posted X/20" prominently; U21 weekly report flags cap exhaustion.
- **Engagement logger dependency on Postiz analytics availability** — if the current Postiz build doesn't expose per-post metrics, U20 falls back to direct Meta/YT API calls. Mitigation: explicitly deferred as a research task with a concrete fallback path.
- **IMAP + Meta + X token rotation, scope minimization, and storage** — no rotation plan = silent breakage after ~60 days for Meta long-lived tokens. Mitigation: R14 specifies dedicated opt-out mailbox (not aliased to primary inbox), Docker-secret storage not `.env` files, explicit 60-day rotation cadence for Meta tokens, separate Meta app for scrape vs publish.
- **Denylist stores creator PII with no retention policy** — indefinite storage of "do not use" labels about identifiable people. Mitigation: denylist rows expire after 2 years unless refreshed; dashboard exposes a deletion action (GDPR/CCPA right-to-erasure path).
- **Revenue attribution gap** — curation ships Shorts to platforms that don't pay the primary $5k/month AdSense stream. Mitigation: R18 + Unit 21 track at least one revenue-side metric, auto-pause after 4 weeks of zero measured revenue impact.
- **Implementation cost** — this is still a large plan. Mitigation: the TOS review gate may reduce it (fewer sources = fewer units). Phases are independently shippable and individually valuable. Opt-out (Phase 8) has been **promoted to a hard gate** — `SIDECAR_CURATION_TRIGGER_ENABLED=1` cannot be set to 1 until Unit 17 + 18 tests pass (enforced via a startup check, not just docs).

## Documentation / Operational Notes

- **Update `.claude/skills/cc-deploy-portainer/SKILL.md`** with:
  - New `/secrets` entries for X bearer, opt-out email IMAP creds
  - New compose bind requirements (none beyond what's already there — assets and secrets already mounted)
  - New env flags to flip when enabling curation
  - The `SIDECAR_CURATION_TRIGGER_ENABLED=1` flag is the single "go live" switch
- **Write `docs/solutions/integration-issues/curation-track-gotchas-<date>.md`** after Wave 1 ships capturing anything surprising (predictable ones: ffmpeg codec edge cases from Reddit videos, Meta Graph rate limiting, Postiz analytics endpoint shape).
- **Update owner-facing docs** (CommonCreed internal playbook, bio + YouTube About page) with:
  - The three opt-out channels (email alias + DM instructions + Google Form link)
  - Explicit statement that CommonCreed reshares with credit and removes on request within 24h
- **Runbook for flipping curation on:**
  1. Verify `SIDECAR_CURATION_TRIGGER_ENABLED=1` in NAS `.env`
  2. Verify trusted allowlist is set to the 6 defaults
  3. Verify at least one Wave 1 source is enabled via `PIPELINE_CONTENT_SOURCES`
  4. Watch first `curation_trigger` tick in logs, confirm non-zero candidate counts
  5. Watch first Telegram preview land
  6. Tap Approve on a test candidate, confirm Postiz publish + IG QUEUE state

## Alternative Approaches Considered

- **Surface-only assistant (brainstorm option B)** — scraper pushes candidates to Telegram, owner manually reshares via Postiz dashboard. Rejected by the owner during brainstorm: aggressive growth target (20 posts/week) doesn't survive the manual step.
- **One-source MVP before the rest** — ship only Reddit in v1, validate the whole chain, then add other sources. Owner explicitly overrode this during brainstorm: wants all 11 Wave 1-3 sources as v1 scope. The phased delivery in this plan still ships Wave 1 first internally.
- **Merge curation with generative pipeline_runs** — single table, single approval flow. Rejected: the two flows track different attributes and merging them forces every column to be nullable across both shapes. Splitting keeps schemas clean.
- **moviepy for overlay rendering** — reuse the generative track's existing video library. Rejected: ~5-10x slower than raw ffmpeg drawtext for this specific overlay pattern. moviepy's TextClip introduces font caching and PIL rendering overhead we don't need for a one-line burn-in.
- **Automatic opt-out confirmation from IG DMs via keyword match** — no human confirmation step. Rejected: free-text DMs on IG are high-false-positive ("please don't remove me" == opt-out? "can you credit me differently" == opt-out?). Human confirmation via Telegram is a necessary safety valve.
- **ML-based scoring** — train a model on engagement data. Rejected: we have zero engagement data for curated items today. Hand-tuned scoring is the right call until U20 + U21 produce 2-4 weeks of post-hoc data. Revisit after v1.
- **Full cross-posting to X + TikTok in v1** — scope. Rejected: credit policies and API shapes differ per platform; scope explosion. Future scope.

## Phased Delivery

**Phase order revised after document review.** Opt-out system (originally Phase 8) is now Phase 3 — it's a day-1 dependency for production posting, and the original position at the end of the plan made it possible to ship through Phase 7 and accidentally enable the flag before the safety layer existed. Also: Unit 14 (Instagram scraping) is deferred out of v1 scope per the Pre-Phase 1 review.

### Phase 0: Pre-Phase 1 Prerequisites (blocking — must complete before Unit 1)

1. **TOS Review Gate** — produce `docs/research/content-curation-tos-review.md` with a per-source clause-by-clause verdict. The v1 source list is determined by this review; some sources will be deleted from scope.
2. **Postiz `delete_post` Research Spike** — identify the removal mechanism (Postiz public API endpoint OR per-platform fallback via existing Meta/YT OAuth). Output goes in Unit 17's approach section.
3. **Revenue Attribution Plan** (recommended, not blocking) — `docs/research/curation-revenue-attribution.md`, half a page answering what success looks like from a $5k/month AdSense perspective.

### Phase 1: Foundation + Trusted-source scaffolding (Units 1-3)

Establishes the new `content_sources/` package, DB schema for candidates + slot log + denylist + credit enforcement log + opt-out events, config settings, and the empty `trusted_sources_set`. No sources yet, no posting yet — just the scaffolding that later phases plug into.

**Exit criteria:** `from sidecar.content_sources import load_enabled_sources` works inside the sidecar container; all five new tables exist; `approvals.kind` migration complete.

### Phase 2: Wave 1 sources + scorer + safety classifier (Units 4-6)

Ships the Wave 1 sources blessed by the TOS review + the safety classifier (with composite cache key) + the hand-tunable scorer (with engagement logger wired from day 1).

**Exit criteria:** at least one Wave 1 source returns non-zero candidates on a dry run; classifier handles T3 cache poisoning scenario; scorer emits breakdowns that populate `score_breakdown_json`.

### Phase 3: Opt-out system — promoted from Phase 8 (Units 17-18)

Ships denylist DB + opt-out processor + removal job + two automated channels (email + Google Form) + universal human confirmation. **This is a hard gate** — `SIDECAR_CURATION_TRIGGER_ENABLED=1` cannot flip until Phase 3 tests pass. Enforced by a startup check in `sidecar/app.py` that refuses to wire the curation trigger job if Unit 17's removal mechanism is unconfigured.

**Exit criteria:** manual end-to-end per channel (send opt-out → Telegram confirmation → Confirm → denylist entry → published post deleted via the chosen mechanism).

### Phase 4: Media pipeline + approval flow (Units 7-10)

Safe-fetch helper (RFC1918 blocker, size/mime limits, ffmpeg sandbox), media normalizer, credit overlay with post-overlay verification probe, Telegram preview extended for curation kind with backwards-compatible signature, approvals_api extended with the full edit-pending state machine.

**Exit criteria:** manual end-to-end — inject a Wave 1 candidate, watch the full chain: safe_fetch → normalize → overlay → Telegram preview → owner Approve → publish to Postiz. Plus: existing generative track regression test still passes unchanged.

### Phase 5: Autopilot + slot allocation with generative migration (Units 11-12)

Track-aware slot allocation (including the generative 09:00→19:00 migration), T-2h warning job, T-30min autopilot with narrowed eligibility (score + trusted set + `source_is_original_publisher`). First slot can fire autonomously after this phase — but only on trusted-source content the owner has explicitly allowlisted.

**Exit criteria:** simulated timeline tests pass all autopilot branches; live test with a trusted-source candidate fires at T-30min; live test with an untrusted candidate skips the slot with a Telegram notification.

### Phase 6: Wave 2 RSS sources (Unit 13)

Adds the TOS-blessed subset of arXiv, Lobste.rs, Product Hunt, Substack pool. Zero new infrastructure — same protocol, same scorer, same publish path. Just more volume.

**Exit criteria:** all TOS-blessed Wave 1+2 sources return candidates on a normal day.

### Phase 7: Wave 3 remaining auth sources (Units 15-16)

Adds X and YouTube trending. IG (Unit 14) is deferred out of scope per the review. X is gated on owner-supplied bearer token; YT reuses existing OAuth and ships immediately.

**Exit criteria:** YT trending source live; X source built but in `is_configured=False` state until bearer token arrives.

### Phase 8: Dashboard + observability + engagement (Units 19-21)

Dashboard curation view (with all 8 states specified), post-hoc engagement logger (shipped alongside scorer in Phase 2 for day-1 feedback, but Unit 20's dashboard integration + Unit 21 weekly report land here), weekly scoring review report with revenue-attribution field.

**Exit criteria:** dashboard renders all curation states correctly; engagement logger runs successfully against a 7-day-old fixture; first weekly report message includes the revenue-attribution line.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-08-content-curation-track-requirements.md](../brainstorms/2026-04-08-content-curation-track-requirements.md)
- **Raw idea doc:** [docs/ideas/content-scraper.md](../ideas/content-scraper.md)
- **Generative track plan (parallel):** [docs/plans/2026-04-06-002-feat-end-to-end-pipeline-plan.md](./2026-04-06-002-feat-end-to-end-pipeline-plan.md)
- **Existing TopicSource pattern to mirror:** `sidecar/topic_sources/__init__.py`, `sidecar/topic_sources/base.py`, `sidecar/topic_sources/hackernews_source.py`
- **Existing publish path to reuse unchanged:** `sidecar/jobs/publish.py`, `sidecar/postiz_client.py`
- **Existing Telegram approval machinery:** `sidecar/telegram_bot.py` (`send_approval_preview`, approval handlers)
- **Institutional learnings:** `docs/solutions/integration-issues/synology-portainer-deploy-gotchas-2026-04-07.md`, `docs/solutions/integration-issues/nas-pipeline-bringup-gotchas-2026-04-07.md`
- **Deploy skill to update:** `.claude/skills/cc-deploy-portainer/SKILL.md`
- **Postiz backend source** (local, inside the commoncreed_postiz container): `/app/apps/backend/dist/libraries/nestjs-libraries/src/dtos/posts/` — the DTOs we reverse-engineered for the publish payload this week
