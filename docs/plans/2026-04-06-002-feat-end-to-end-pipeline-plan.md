---
title: "feat: Self-hosted end-to-end CommonCreed pipeline on Synology + Portainer"
type: feat
status: active
date: 2026-04-06
origin: docs/brainstorms/2026-04-06-end-to-end-pipeline-requirements.md
---

# feat: Self-Hosted End-to-End CommonCreed Pipeline

## Overview

Wrap the existing CommonCreed video pipeline in a self-hosted stack that runs unattended on a Synology DS1520+ via Portainer. Postiz owns all social posting + scheduling + account management; a new CommonCreed "sidecar" service owns everything that's not posting — Gmail trigger, LLM topic selection, pipeline orchestration, Telegram approval bot, caption generation, and a small dashboard for run history + settings. Existing pipeline code is reused verbatim; nothing in `scripts/` is rewritten.

## Problem Frame

The CommonCreed video pipeline runs today as a one-off smoke script on the owner's Mac. To reach the $5K/month revenue target it has to run every day without manual intervention — scan the inbox for the latest TLDR AI newsletter, pick 2 topics, produce 2 videos, route them through a Telegram approval loop, and publish to Instagram + YouTube from multiple collaborating accounts. The owner has a Synology DS1520+ running Portainer and no public IP. (see origin: docs/brainstorms/2026-04-06-end-to-end-pipeline-requirements.md)

## Requirements Trace

- R1. Self-hosted stack on DS1520+, portable to any Docker host
- R2. Daily Gmail trigger at 05:00, previous evening's TLDR newsletter
- R3. LLM-scored topic selection (Sonnet), picks top 2
- R4. Automated video generation reusing existing pipeline
- R5. Two fixed slots: 09:00 and 19:00; both videos built in a single 05:00 run
- R6. Telegram approval loop with inline buttons + force-reply Edit Caption
- R7. Auto-approve at T-30 min before scheduled slot
- R8. Dashboard = Postiz + sidecar with pipeline history, approval queue, Gmail logs, settings
- R9. All secrets editable via dashboard; changes restart affected services automatically
- R10. Platform-aware caption + hashtag engine (IG + YT) via LLM
- R11. Instagram Collab (Postiz field if present, direct Graph API fallback)
- R12. YouTube credit-only collaboration via description + pinned comment
- R13. Telegram notification pipeline preserved and extended
- R14. Pipeline run history + observability in dashboard and Telegram
- R15. Per-video failure isolation — one failure never blocks the other

## Scope Boundaries

- NOT rewriting the existing pipeline code in `scripts/` — only wrapping and orchestrating it
- NOT building custom UI for what Postiz already does — scheduling, media library, OAuth flows stay in Postiz
- NOT building public internet exposure — LAN-only; Tailscale is a deferred follow-up
- NOT adding platforms beyond IG + YouTube in this plan
- NOT running video gen on cloud GPU — CPU on DS1520+ is the default
- NOT adding engagement analytics or dynamic scheduling
- NOT building a new secrets manager — Portainer env vars + sidecar write-through is the whole story
- NOT automating the one-time OAuth dance for Gmail or Postiz social accounts — those are manual bootstrap steps

## Context & Research

### Relevant Code and Patterns

- **Existing pipeline code** lives in `scripts/`. The sidecar will invoke `scripts/smoke_e2e.py`-style orchestration as a subprocess with env injection. Key entry points:
  - `scripts/smoke_e2e.py` — current end-to-end orchestrator with `step_script`, `step_thumbnail`, `step_voice`, `step_avatar`, `step_broll`, `step_assemble`
  - `scripts/content_gen/script_generator.py` — Claude Sonnet script generation
  - `scripts/thumbnail_gen/` — completed thumbnail engine (Unit 7 of the prior plan)
  - `scripts/posting/postiz_poster.py` — Postiz REST client with factory dispatch (already built)
  - `scripts/posting/social_poster.py` — `make_poster()` factory
- **Postiz docs**: `POST /public/v1/posts` accepts per-platform settings. Field names for IG Collab and YT thumbnail uploads must be verified at integration time (TODO comments already in `postiz_poster.py`).
- **Per-video cost baseline** verified in the prior e2e run: $1.96 per video (Sonnet ~$0.01, Haiku ~$0.001, ElevenLabs ~$0.37, VEED ~$1.57).
- **Newsletter sample** at `assets/newsletter/Gmail - Claude Code leak 🔓, Veo 3.1 Lite ⚡, 1-bit models 🤏.pdf` — used as reference for TLDR AI format and arrival time (~18:57 local).
- **Telegram notification pattern** already present in the pipeline (outbound only). No inline-button/callback handling yet — this plan adds it.

### Institutional Learnings

- `docs/solutions/integration-issues/haiku-drops-version-number-periods-2026-04-06.md` — when asking an LLM for structured text that must preserve non-word punctuation (version numbers, model names), use both a prompt rule with negative examples AND a regex validator that rejects + retries drift. Applies to the caption engine (Unit 5) and the topic scorer (Unit 3).
- `docs/solutions/integration-issues/avatar-lip-sync-desync-across-segments-2026-04-05.md` — the pipeline's avatar sync depends on `audio_duration` driving `_compute_avatar_windows()`; the held-frame offset for thumbnails must NOT shift that timeline. Already respected in existing code — this plan does not touch the assembler.

### Relevant Memories

- `project_posting_layer` — Postiz replaces Ayrshare; self-hosted via Portainer on Synology; OAuth-based per platform; REST API for pipeline integration.
- `reference_tiktok_cover_limit` — TikTok API caveat (not in scope for this plan but preserved in case TikTok is added later).
- `project_commoncreed` — Instagram-first, AI tech news shorts, 2-3/day cadence, Telegram review.

### External References

- Postiz public API: `docs.postiz.com` — verify per-platform field names for IG `collabTag` / `coCreators`, YT `title`/`description`/`thumbnail`, and scheduling timestamps at integration time.
- Instagram Graph API Collab: `/{ig-user-id}/media?collaborators=["other_ig_user_id"]` parameter on the `POST media` endpoint — this is the direct-API fallback path if Postiz does not expose the field.
- Gmail API `users.messages.list` with `q=from:dan@tldrnewsletter.com newer_than:1d` — the clean way to fetch the latest TLDR newsletter.
- `python-telegram-bot` v22+ async API — recommended framework for the approval bot.
- APScheduler — lightweight Python scheduler for the 05:00 trigger, T-30min cutoff, and the hourly Gmail retry.

## Key Technical Decisions

- **Single combined Portainer stack** containing Postiz (+ its Postgres + Redis) and the CommonCreed sidecar. One `docker-compose.yml`, one restart policy, one network. Splitting across multiple stacks adds Portainer friction without meaningful isolation gain for a single-user home deployment.
- **Sidecar = FastAPI + APScheduler + SQLite**, Python 3.11. Reasons: (a) the pipeline itself is Python so subprocess invocation is zero-friction, (b) FastAPI gives REST + HTML dashboard from one framework, (c) APScheduler handles cron + one-shot jobs in-process, (d) SQLite is file-based and needs zero infra — fine for single-writer sidecar workloads.
- **Sidecar invokes the video pipeline as a subprocess** against the existing `scripts/smoke_e2e.py`-style entry point, with env vars injected per-run from the sidecar's settings store. This keeps the existing pipeline code untouched and avoids importing its heavy dependencies into the sidecar's long-running process (MoviePy + Whisper + Playwright + rembg would double the sidecar memory footprint).
- **Pipeline code mounted as a read-only volume** into the sidecar container, not copied into the image. Same pipeline code runs locally on the Mac and inside the container — one source of truth, no image rebuilds when the pipeline code changes.
- **Memory discipline**: all pipeline subprocesses run strictly sequentially (never parallel), with a global lock in the sidecar. Postiz + Postgres + Redis baseline ~1.5 GB, pipeline peak ~2 GB → fits in 8 GB with margin. Docker memory limits on the sidecar worker prevent OOM cascades.
- **Telegram bot via polling, not webhooks** — no public IP means webhooks aren't viable. `python-telegram-bot` with long-polling runs inside the sidecar process. Polling is fine for single-user approval volumes.
- **Gmail via OAuth + Gmail API, not IMAP + app password** — app passwords are deprecated for new Google accounts and IMAP has rate-limit and labeling quirks. Gmail API is more work upfront but durable.
- **SQLite schema owns three tables**: `pipeline_runs`, `approvals`, `settings`. Minimal relational surface. No migrations framework — raw SQL at startup with `CREATE TABLE IF NOT EXISTS` is enough for this scale.
- **Caption engine is a NEW sidecar module**, not an extension of `script_generator.py`, because it has different prompt shape, different output structure (per-platform), and runs after assembly rather than before. Reusing the same Anthropic client instance is fine; reusing the prompt template would be wrong.
- **Auto-approve is a scheduler job, not a reactive timer**: when an approval record is created, a one-shot APScheduler job is added for `scheduled_slot - 30min`. On fire, it checks approval state in SQLite and publishes if still pending. Cancellable if the owner acts first. Survives sidecar restart because APScheduler jobstore is SQLite-backed.
- **IG Collab integration is publish-then-verify-then-fallback**: the sidecar sends the post to Postiz with the collab field populated. After Postiz confirms publish success, the sidecar reads the posted media back from the IG Graph API (`GET /{ig-media-id}?fields=collaborators`) to verify the collaborator was actually applied. If the field is empty, the sidecar edits the media to add collaborators via the direct Graph API (or, if edit is unsupported for collab-adds post-publish, deletes and re-creates). The read-back is a single extra API call per post and is the only reliable detection signal — Postiz may return a 200 and silently drop the field.
- **Dashboard rendering = FastAPI + Jinja2 + HTMX**, no SPA framework. Server-rendered HTML partials + HTMX swaps handle run history, approval queue, and settings with far less complexity than React/Svelte for a single-user LAN app. Postiz's native UI handles everything else; the sidecar only adds CommonCreed-specific views.
- **Settings persistence layered**: the source of truth is the stack `.env` file on disk (mounted into both Postiz and sidecar). The sidecar has a Settings UI that reads and writes that file atomically. For settings that affect *other* containers (Postiz), the sidecar signals a restart via the Docker socket. For settings that affect the *sidecar itself* (Anthropic, Telegram, Gmail tokens), the sidecar re-reads `.env` on-demand at the point of use — it NEVER restarts itself from its own API, because that would kill the in-flight HTTP response the user is waiting on. SQLite caches current values for hot reads but `.env` is authoritative.
- **Dashboard auth = sidecar-owned session with single admin password**: the sidecar issues its own session cookie via a simple login page, authenticated against a single `SIDECAR_ADMIN_PASSWORD` stored in `.env`. Zero coupling to Postiz's cookie/session internals, no reverse-proxy cookie-rewriting gymnastics, and it works regardless of whether Postiz and the sidecar share a hostname/path scope. Trade-off: two separate logins (Postiz for posting UI, sidecar for CommonCreed views). Acceptable for single-user LAN operation. If session-sharing becomes important later, it can be layered on top without rewriting the sidecar's auth surface.

## Open Questions

### Resolved During Planning

- **Combined vs split Docker stack?** Combined. One stack, one restart policy, one network.
- **FastAPI vs Flask vs Django for sidecar?** FastAPI — async support for the Telegram bot poller, and ASGI server fits with APScheduler's async mode.
- **SQLite vs sharing Postiz's Postgres?** SQLite. Isolating sidecar state from Postiz keeps Postiz upgradeable without schema coupling.
- **Webhook vs polling for Telegram?** Polling. No public IP.
- **Subprocess vs importing pipeline code into sidecar?** Subprocess. Keeps the sidecar light and decouples upgrade cycles.
- **Where does the caption engine live?** New sidecar module, called post-assembly.
- **How does auto-approve survive restarts?** APScheduler SQLite jobstore.

### Deferred to Implementation

- Exact Postiz API field names for IG Collab (`collabTag` vs `coCreators` vs something else) — verify against running Postiz instance at integration time.
- Exact Postiz API shape for YT thumbnail upload (multipart field name) — verify at integration time.
- Whether Postiz exposes an admin endpoint to read IG tokens, or if the sidecar must read them directly from Postiz's Postgres as a fallback — decide based on Postiz version at build time.
- Reverse proxy choice (Caddy vs Traefik) — Caddy is simpler for the single-domain LAN case, Traefik is more flexible. Pick at implementation.
- Exact faster-whisper + MoviePy memory profile on ARM-free x86_64 Celeron — profile during the first benchmark smoke run and tighten Docker memory limits.
- Retention policy specifics (days to keep generated videos, thumbnails, audio) — start with 14 days and revise after a week of data.
- Whether to checkpoint pipeline runs at each step for partial retry, or just re-run the whole video on failure — start with whole-video retry, add checkpointing if per-step failures become common.
- Image for the sidecar worker: a single image with ffmpeg + Playwright + Python, or two images (one lightweight web container + one heavyweight worker) — start with a single image; split if build times become painful.
- TLDR AI newsletter parsing: regex extraction from HTML body vs LLM-based extraction. Start with LLM extraction because format can drift.

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
┌─────────────────────────────────────────────────────────────────┐
│                    Portainer stack (single)                     │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌─────────┐  ┌──────────────────┐ │
│  │ Postiz   │  │ Postgres │  │ Redis   │  │ CommonCreed      │ │
│  │ (posting │  │ (Postiz) │  │(Postiz) │  │ Sidecar          │ │
│  │  layer)  │  │          │  │         │  │ (FastAPI +       │ │
│  │          │  │          │  │         │  │  APScheduler +   │ │
│  └────┬─────┘  └──────────┘  └─────────┘  │  SQLite +        │ │
│       │                                   │  Telegram bot)   │ │
│       │ REST API                          └────────┬─────────┘ │
│       └──────────────────────────────────────────┘ │           │
│                                                    │           │
│  Mounted into sidecar:                             │           │
│   - scripts/ (pipeline code, read-only)            │           │
│   - output/ (video assets, read-write)             │           │
│   - .env (stack secrets, read-write)               │           │
│   - /var/run/docker.sock (for restarts)            │           │
│                                                    │           │
└────────────────────────────────────────────────────┼───────────┘
                                                     │
                                                     │ subprocess
                                                     ▼
                                            ┌─────────────────┐
                                            │ scripts/        │
                                            │ smoke_e2e.py    │
                                            │ (existing)      │
                                            └─────────────────┘

Daily flow:
  05:00 ── cron ──▶ sidecar ─▶ Gmail API ─▶ pick yesterday's TLDR
                           │
                           ▼
                   Sonnet scores items → pick top 2 → persist pipeline_runs
                           │
                           ▼
                   For each topic (sequential):
                     subprocess smoke_e2e.py (via existing code)
                     → script + thumbnail + voice + avatar + broll + assemble
                     → caption engine (new) → persist + Telegram preview
                           │
                           ▼
                   Approval flow (inline buttons + force-reply)
                           │
                           ▼
                   Scheduler waits → at T-30 min, auto-approve if pending
                           │
                           ▼
                   Postiz REST API publishes to IG + YT
                   (IG with collab fallback to Graph API)
```

## Implementation Units

- [x] **Unit 1: Portainer stack skeleton + Postiz bootstrap**

**Goal:** Get Postiz + Postgres + Redis running cleanly on the DS1520+ with persistent volumes, reachable from LAN, with all four social accounts connected via OAuth.

**Requirements:** R1, R8 (partial), R11, R12

**Dependencies:** None — this is the foundation.

**Files:**
- Create: `deploy/portainer/docker-compose.yml` — single stack definition
- Create: `deploy/portainer/.env.example` — all required env vars documented
- Create: `deploy/portainer/README.md` — Synology deployment walkthrough including NAS folder setup, Portainer stack import, OAuth connection steps for IG + YT + Gmail

**Approach:**
- Start from Postiz's official `docker-compose.yml`, trim to the four services we need, pin image versions.
- Named volumes for `postgres_data`, `postiz_uploads`, `commoncreed_output`, `sidecar_db`.
- Single Docker network; no exposed ports beyond the reverse proxy.
- `.env` at a well-known path on the NAS (`/volume1/docker/commoncreed/.env`) mounted into the sidecar read-write and Postiz read-only.
- Manual steps documented in README: Portainer stack import → visit Postiz web UI → OAuth connect `@commoncreed` IG + `@vishalan.ai` IG + `@common_creed` YT + `@vishalangharat` YT → save API keys into `.env`.

**Test scenarios:**
- Stack comes up on first import without errors
- All four Postiz accounts show as connected after OAuth
- NAS reboot → stack restarts cleanly with no manual intervention
- `docker compose down && docker compose up -d` preserves all data

**Verification:**
- Manually post a test text message from Postiz UI to each connected account
- NAS reboot test passes
- `.env` edits are visible to the sidecar without rebuild

---

- [x] **Unit 2: CommonCreed sidecar service skeleton**

**Goal:** Build the sidecar Docker image, wire it into the stack, expose a health endpoint, and confirm it can read the mounted pipeline code and `.env` file.

**Requirements:** R1, R8 (partial), R15

**Dependencies:** Unit 1

**Files:**
- Create: `sidecar/Dockerfile` — python:3.11-slim base with ffmpeg, Playwright Chromium deps, and pipeline Python deps installed from `requirements.txt`
- Create: `sidecar/app.py` — FastAPI entry point, lifespan handlers, route wiring
- Create: `sidecar/config.py` — settings loader from `.env` with typed model
- Create: `sidecar/db.py` — SQLite connection + schema bootstrap (`pipeline_runs`, `approvals`, `settings`)
- Create: `sidecar/routes/health.py` — `GET /health` returning `{ok: true, pipeline_code_visible: bool, env_readable: bool, db_writable: bool}`
- Create: `sidecar/tests/test_app_bootstrap.py`
- Modify: `deploy/portainer/docker-compose.yml` — add sidecar service with volume mounts and Docker socket
- Create: `sidecar/requirements.txt` — fastapi, uvicorn[standard], apscheduler, python-telegram-bot, anthropic, google-api-python-client, google-auth, google-auth-oauthlib, jinja2, htmx-style deps (none needed, HTMX is browser-side)

**Approach:**
- Single image layers the pipeline's system deps (ffmpeg, Playwright) so both the sidecar's own HTTP server and subprocess-launched pipeline share the runtime.
- Entry point runs `uvicorn` in production mode; `app.py` uses FastAPI lifespan hook to bootstrap DB + load settings + start APScheduler + start Telegram bot.
- Mounts in docker-compose: `/app/scripts:ro` (pipeline code), `/app/output` (video outputs), `/var/run/docker.sock` (for restarts), `/env/.env` (secrets), `/app/sidecar_db` (SQLite).
- Memory limit: 4 GB (leaves ~2.5 GB for Postiz + host).
- Health endpoint confirms all required mounts are visible and writable before any real work starts.

**Test scenarios:**
- `GET /health` returns 200 with all three flags true
- Missing `.env` mount → `/health` returns 503 with clear error
- Stack restart → SQLite tables persist, settings are re-read
- Sidecar can `ls /app/scripts` and see `smoke_e2e.py`

**Verification:**
- Sidecar container healthy in Portainer after deploy
- `/health` green from LAN browser
- Logs show APScheduler started with zero jobs (expected at this stage)

---

- [x] **Unit 3: Gmail trigger + LLM topic selection**

**Goal:** At 05:00 daily, fetch the most recent TLDR AI newsletter from Gmail, extract items, score them with Claude Sonnet, and persist the top 2 topics to `pipeline_runs`.

**Requirements:** R2, R3

**Dependencies:** Unit 2

**Files:**
- Create: `sidecar/gmail_client.py` — Gmail API client with OAuth refresh; query `from:dan@tldrnewsletter.com newer_than:1d`; returns parsed message body
- Create: `sidecar/topic_selector.py` — LLM-based item extraction + scoring using Claude Sonnet; returns list of `{title, url, description, score, rationale}`
- Create: `sidecar/jobs/daily_trigger.py` — APScheduler job that orchestrates Gmail fetch → topic selection → pipeline_runs insert
- Create: `sidecar/tests/test_gmail_client.py` — fixture-based tests using a saved sample newsletter
- Create: `sidecar/tests/test_topic_selector.py` — mock Sonnet, verify score parsing + top-2 selection
- Create: `sidecar/tests/fixtures/tldr_sample.json` — one real TLDR newsletter stored as fixture
- Modify: `sidecar/db.py` — add `pipeline_runs` columns for `topic_title`, `topic_url`, `topic_score`, `selection_rationale`, `source_newsletter_date`

**Approach:**
- Gmail credentials stored in `.env` as `GMAIL_OAUTH_TOKEN_JSON` (refresh-token-based; one-time manual OAuth dance documented in Unit 1 README).
- Topic extraction prompt: pass the full newsletter body, ask Sonnet to return a JSON array of `{title, url, description, category}` for each story. Model: `claude-sonnet-4-6`.
- Scoring prompt: second call with the extracted items, asks Sonnet to score each on virality, novelty, thought-provocation, and AI-tech relevance (1-10 each), and pick the top 2 with rationale. JSON output enforced.
- Retry pattern: if `selection_rationale` fails JSON parsing, retry once with a stricter prompt.
- Failure handling: if Gmail fetch returns no newsletters within 24h, APScheduler hourly retry job runs until noon, then sends Telegram "day skipped" message.
- Failure handling: if Sonnet extraction returns 0 items, log, send Telegram warning, skip the day.
- `pipeline_runs` row created for each selected topic with status `pending_generation`.

**Patterns to follow:**
- LLM structured output discipline from `docs/solutions/integration-issues/haiku-drops-version-number-periods-2026-04-06.md` — prompt-level rules + regex/JSON validation + retry on drift.
- `scripts/content_gen/script_generator.py` Anthropic client pattern.

**Test scenarios:**
- Sample newsletter → extracts 10-20 items (TLDR AI typical count)
- Empty newsletter body → returns empty list without raising
- Sonnet JSON parse failure → retries once, then raises with context
- No newsletter within 24h → `daily_trigger` enters retry mode, does not insert runs
- `pipeline_runs` rows are created with correct metadata after successful selection

**Verification:**
- Feeding the existing TLDR newsletter PDF text through the scorer produces 2 sensible picks (manual inspection)
- APScheduler job list shows `daily_trigger` at 05:00
- `/runs` endpoint returns today's picks after a manual trigger via test endpoint

---

- [x] **Unit 4: Pipeline runner integration**

**Goal:** Sequentially execute the existing video pipeline for each selected topic via subprocess, persist results to `pipeline_runs`, and enforce per-video failure isolation.

**Requirements:** R4, R15

**Dependencies:** Unit 3

**Files:**
- Create: `sidecar/pipeline_runner.py` — subprocess launcher, env injection, output path capture, crash recovery
- Create: `sidecar/jobs/run_pipeline.py` — APScheduler job that picks up `pending_generation` runs and invokes `pipeline_runner`
- Create: `sidecar/tests/test_pipeline_runner.py` — mocked subprocess tests for env injection, path capture, and failure isolation
- Modify: `sidecar/db.py` — add `pipeline_runs` columns for `video_path`, `thumbnail_path`, `audio_path`, `cost_sonnet`, `cost_haiku`, `cost_elevenlabs`, `cost_veed`, `error_log`, `started_at`, `finished_at`

**Approach:**
- One pipeline subprocess at a time, enforced by a global `asyncio.Lock` in the sidecar process. Second-topic subprocess only starts after first finishes (or fails).
- Env vars for the subprocess constructed fresh from the settings store, not inherited from the sidecar's env. This way a settings edit takes effect on the next run without sidecar restart.
- Subprocess working directory = `/app/scripts` (mounted pipeline code).
- Subprocess command: `python smoke_e2e.py` with `SMOKE_TOPIC` and `SMOKE_URL` env vars set from the `pipeline_runs` row. `SMOKE_USE_VEED=1` forced on.
- Output paths captured by parsing the subprocess stdout (existing pipeline prints them in known formats) and/or by scanning the `output/` directory for new files with timestamps after `started_at`.
- Failure isolation: if topic 1's subprocess exits non-zero or times out (hard cap 15 min), log the error, mark the run failed, and continue to topic 2. Never raise out of the APScheduler job.
- Cost extraction: parse the existing pipeline's cost report stdout, persist to the row.

**Patterns to follow:**
- Failure isolation approach from `scripts/thumbnail_gen/step.py` — catch everything, log, continue.
- Existing `scripts/smoke_e2e.py` env-flag API (`SMOKE_TOPIC`, `SMOKE_URL`, `SMOKE_USE_VEED`).

**Test scenarios:**
- Happy path: two pending runs → both succeed → both marked `generated`, paths persisted
- Topic 1 fails → topic 2 still runs and succeeds
- Timeout → subprocess killed, row marked `failed_timeout`, Telegram notification sent
- Settings update between runs → second subprocess sees new env vars
- Concurrent trigger attempt while one is running → blocks on lock, does not spawn parallel

**Verification:**
- Manual trigger produces two videos in sequence on the NAS, both with DB rows populated
- A forced failure on topic 1 (e.g., invalid API key in settings for that run only) leaves topic 2 untouched
- Pipeline end-to-end stays under ~8 min per video; total run under ~16 min

---

- [x] **Unit 5: Caption + hashtag engine**

**Goal:** Generate platform-aware captions and hashtags for each completed video, persist them, and make them editable by the owner before posting.

**Requirements:** R10

**Dependencies:** Unit 4

**Files:**
- Create: `sidecar/caption_gen.py` — LLM caller that produces `{instagram: {caption, hashtags}, youtube: {title, description, hashtags}}` for one video
- Create: `sidecar/tests/test_caption_gen.py` — mock Sonnet, verify per-platform shape, length limits, hashtag count
- Modify: `sidecar/db.py` — add `captions_json` column to `pipeline_runs`
- Modify: `sidecar/jobs/run_pipeline.py` — call caption_gen after subprocess finishes, before Telegram preview

**Approach:**
- Single Sonnet call returns JSON for both platforms. Prompt includes the full script and the chosen headline.
- Output constraints: IG caption ≤ 125 chars (visible above fold), IG hashtags 5-10 in a separate block, YT Shorts title ≤ 100 chars, YT description ≤ 500 chars with credit-to-@vishalangharat line appended programmatically (R12).
- Hashtags biased toward AI + tech trending tags with 1-2 niche tags (`#commoncreed` brand tag, topic-specific).
- Validation: JSON parse + length limits enforced + regex-retry pattern from the Haiku learning doc. Fallback on retry failure: use the headline as the caption and a fixed hashtag set.
- Caption is editable via Telegram force-reply (Unit 6) and via the dashboard approval queue (Unit 8).

**Patterns to follow:**
- Haiku/Sonnet structured-output discipline (ref. learning doc above).
- Existing Anthropic client construction in `scripts/content_gen/script_generator.py`.

**Test scenarios:**
- Happy path: returns valid JSON with both platforms populated, lengths under limits
- Length overflow in response → retry, then fallback
- Invalid JSON → retry, then fallback
- YT description always has the @vishalangharat credit line appended (R12)
- Hashtag count always in 5-10 range

**Verification:**
- Run the caption engine on 3 real scripts from the `output/scripts/` directory; manually confirm the captions read naturally and the hashtags are relevant

---

- [x] **Unit 6: Telegram approval bot**

**Goal:** Implement the owner-facing approval loop. Send preview, handle inline actions (Approve, Reject, Reschedule), handle force-reply caption edits, update DB, and trigger the posting flow on approve.

**Requirements:** R6, R13

**Dependencies:** Units 4, 5

**Files:**
- Create: `sidecar/telegram_bot.py` — `python-telegram-bot` v22 async Application, polling mode, command + callback handlers
- Create: `sidecar/tests/test_telegram_bot.py` — mocked bot tests for callback handling and force-reply state
- Modify: `sidecar/db.py` — add `approvals` table (`pipeline_run_id`, `status`, `owner_action_at`, `proposed_time`, `telegram_message_id`)
- Modify: `sidecar/jobs/run_pipeline.py` — after caption_gen, call `send_approval_preview(run_id)` to emit the Telegram message

**Approach:**
- Bot runs in the sidecar process as a background task started in FastAPI lifespan. Long-polling; survives Postiz restarts.
- Preview payload: thumbnail PNG + 10-second MP4 clip (trimmed from the final video via ffmpeg) + caption text + inline keyboard with 4 buttons: Approve ✓, Reject ✗, Reschedule ⏰, Edit Caption ✏.
- Callback handlers update `approvals.status` and respond with a new inline keyboard reflecting state (e.g., after Approve → button row shrinks to "Approved at HH:MM, publishing at HH:MM").
- Reschedule button opens an inline keyboard of alternative slot times (next 6 slots across the next 3 days); on pick, updates `scheduled_slot` in the run and reschedules the auto-approve cutoff job.
- Edit Caption uses `ForceReply` — bot sends a new message with `ForceReply(selective=True)` prompting "Reply with new caption". When the owner replies, the reply-handler updates `captions_json` and re-sends a preview confirmation.
- Auto-approve cutoff (R7) is NOT in this unit — lives in Unit 8 (scheduler). This unit is pure Telegram interaction.
- All notifications from the existing pipeline (errors, cost reports) continue to go through the same bot instance (R13).

**Patterns to follow:**
- Existing Telegram notification pattern in the pipeline (outbound-only paths stay unchanged; inbound callback handling is new).

**Test scenarios:**
- Preview message successfully sends with all three attachments
- Approve callback → approval row updated, publish job scheduled
- Reject callback → approval row marked rejected, publish job NOT scheduled
- Reschedule callback → new slot picker shows, picking a slot updates the DB
- Edit Caption → ForceReply sent, reply updates `captions_json`, confirmation preview re-sent
- Bot reconnects after polling network interruption without losing state

**Verification:**
- Manual end-to-end: trigger a run → receive preview on owner's Telegram → tap each button → confirm DB state matches UI state
- Large video preview (10s clip should be < 5 MB) sends within Telegram's 50 MB inline limit
- Simultaneous previews for topic 1 and topic 2 don't collide in DB

---

- [ ] **Unit 7: Postiz posting + auto-approve scheduler + IG Collab fallback**

**Goal:** On Approve (or auto-approve timeout), publish the video + caption + thumbnail to IG + YT via Postiz. Fall back to direct IG Graph API if Postiz does not support the Collab field. Handle the T-30min cutoff via scheduler.

**Requirements:** R7, R11, R12, R14, R15

**Dependencies:** Units 2, 6

**Files:**
- Create: `sidecar/postiz_client.py` — thin wrapper around Postiz public REST API (`POST /public/v1/posts`, `GET /auth/me`, account list endpoint)
- Create: `sidecar/ig_direct.py` — direct Instagram Graph API Collab posting, used only as fallback
- Create: `sidecar/jobs/publish.py` — APScheduler-triggered publish action for an approval row
- Create: `sidecar/jobs/auto_approve.py` — T-30min cutoff job
- Create: `sidecar/tests/test_postiz_client.py`, `sidecar/tests/test_ig_direct.py`, `sidecar/tests/test_auto_approve.py`
- Modify: `sidecar/db.py` — add `post_ids_json` to `pipeline_runs` (maps platform → Postiz post ID or IG media ID), `publish_attempted_at`, `publish_error`

**Approach:**
- On approval (manual or auto), the publish job:
  1. Reads `pipeline_runs` row + `approvals` row + `captions_json`.
  2. Calls Postiz `POST /public/v1/posts` with a multipart body containing the video file, the thumbnail file, per-platform settings (IG caption + collab + cover, YT title + description + thumbnail), and the scheduled slot.
  3. Parses response; persists platform → post_id to `post_ids_json`.
  4. For IG: **verify**, don't guess. After Postiz reports success, the job calls `ig_direct.verify_collab(ig_media_id)` which reads back the posted media via `GET /{ig-media-id}?fields=collaborators` and checks whether `@vishalan.ai` is present. If missing, `ig_direct.add_collab(ig_media_id)` edits the media to add the collaborator (or, if the IG API doesn't support post-publish collab edits, deletes and re-creates via direct Graph API). Either way the Postiz post ID is superseded by the direct-API media ID in `post_ids_json`. Verification adds one extra API call per IG post but is the only reliable signal that the collab actually took effect.
- Auto-approve job (`auto_approve.py`): scheduled as a one-shot job at `scheduled_slot - 30min` when the approval row is created. On fire: re-reads approval status from SQLite; if still `pending`, flips to `auto_approved` and triggers the publish job. If already `approved`/`rejected`, no-op.
- Publish failure handling: log to `publish_error`, send Telegram notification with traceback, mark run as `publish_failed`. Do NOT retry automatically — manual action required via dashboard.
- YouTube credit line (R12): `ig_direct.py` handles IG; YT credit is baked into the caption engine's YT description output (Unit 5) so it's applied before publish.

**Patterns to follow:**
- Existing `scripts/posting/postiz_poster.py` — the sidecar can reuse this class directly (mounted pipeline code is importable inside the sidecar for utility use, even though the video pipeline itself runs as a subprocess).
- `make_poster()` factory from `scripts/posting/social_poster.py`.

**Test scenarios:**
- Happy path: approval → publish succeeds on both platforms → `post_ids_json` populated
- Auto-approve: no owner action for 4h → cutoff fires at T-30min → publishes
- Reject: approval marked rejected → auto-approve job fires → no-ops
- Postiz returns 500 → marked `publish_failed`, Telegram notification sent, no retry
- IG Collab fallback: Postiz silently drops collab → fallback re-publishes via Graph API → both IG posts share the media
- Slot already passed when job fires → publish immediately, log the overrun

**Verification:**
- Manual approval test on a real video → both platforms show the post scheduled, credit line present on YT, collab tag present on IG
- Force a 4h pause on a test run → auto-approve fires and publishes
- Check IG Graph API logs to confirm the collab_tag path works end-to-end with a test account pair

---

- [ ] **Unit 8: Dashboard UI + settings management**

**Goal:** Ship the sidecar-rendered HTML dashboard covering run history, approval queue, Gmail trigger logs, and the Settings page that edits secrets + triggers container restarts.

**Requirements:** R8, R9, R14

**Dependencies:** Units 2, 3, 4, 6, 7

**Files:**
- Create: `sidecar/routes/dashboard.py` — FastAPI router for `/`, `/runs`, `/runs/{id}`, `/approvals`, `/settings`
- Create: `sidecar/routes/settings_api.py` — POST `/settings/update` with validation + atomic `.env` write + restart signal
- Create: `sidecar/templates/` — Jinja2 templates: `base.html`, `runs.html`, `run_detail.html`, `approvals.html`, `settings.html`
- Create: `sidecar/static/` — minimal CSS, HTMX from CDN
- Create: `sidecar/auth.py` — Postiz session cookie verification middleware
- Create: `sidecar/docker_manager.py` — Docker socket client for restarting affected containers after settings update
- Create: `sidecar/tests/test_dashboard_routes.py`, `sidecar/tests/test_settings_api.py`
- Modify: `deploy/portainer/docker-compose.yml` — add reverse proxy (Caddy) in front of Postiz + sidecar sharing the same domain and cookie

**Approach:**
- Server-rendered HTML + HTMX. No SPA framework. Partials returned for HTMX swaps on button clicks.
- All dashboard routes wrapped with `auth.py` middleware that checks for a valid Postiz session cookie via `GET /auth/me` on Postiz. If invalid → 401 redirect to Postiz login.
- `/` = summary page: last 7 days of runs, approval queue count, Gmail trigger last-success timestamp, cost this month.
- `/runs` = paginated run history with filters (status, date range). Each row links to `/runs/{id}` which shows full detail including video embed, thumbnail, captions, cost breakdown, logs, and action buttons (retry publish, regenerate caption, view in Postiz).
- `/approvals` = pending approvals view; same controls as the Telegram flow but from the browser.
- `/settings` = grouped form for API keys (Anthropic, ElevenLabs, VEED, fal.ai, Pexels, Telegram, Gmail OAuth refresh token) and runtime config (schedule times, cutoff duration, retention days). Each group labeled with which container(s) need restart when that group changes.
- Settings save flow:
  1. Validate input (non-empty, length bounds, regex for obvious format)
  2. Write the full `.env` atomically (`.env.new` → rename)
  3. Compute which containers touch each changed key (static map: Postiz-related keys → Postiz; sidecar-internal keys like Anthropic/Telegram/Gmail → sidecar re-reads on demand, no restart; subprocess-only keys like ElevenLabs/VEED/Pexels → picked up on next pipeline run, no restart)
  4. Restart only *other* containers (Postiz) via Docker socket. **The sidecar never restarts itself** — doing so from its own API would kill the in-flight HTTP response the user is waiting on. Sidecar-affecting settings are re-read from `.env` at the point of use (e.g., re-read the Anthropic key before each LLM call, re-read the Telegram token on bot reconnect, refresh the Gmail OAuth token on next daily trigger).
  5. Show confirmation toast listing which containers were restarted and which settings will take effect on next use
- Docker socket access wrapped in a narrow client that only supports `container.restart(name)` for names in an allowlist that does NOT include the sidecar itself — no arbitrary exec, no self-restart path.
- Settings update audit: each change logged to the `settings` SQLite table with `changed_at`, `changed_keys`.

**Patterns to follow:**
- Postiz's own admin layout for visual consistency (colors, spacing) — the sidecar should feel like a CommonCreed-themed extension, not a separate app.
- FastAPI + Jinja pattern.

**Test scenarios:**
- Unauthenticated request to `/runs` → 401, redirect to Postiz login
- Authenticated request → full render with data
- Settings save with a new Anthropic key → `.env` updated, sidecar restart signal fired, subsequent run uses the new key
- Settings save with an invalid key format → validation error, no `.env` write
- Atomic write: crash mid-write does not corrupt `.env`
- Approval action from dashboard matches Telegram behavior (same DB state transitions)

**Verification:**
- Navigate the full dashboard from LAN browser, log in via Postiz, view yesterday's runs, approve a pending one
- Rotate the Anthropic key through the Settings page, confirm next subprocess pipeline run uses the new key without manual restart
- Check `settings` audit table shows the change

---

- [ ] **Unit 9: Failure isolation hardening + retention + operational polish**

**Goal:** Ensure per-video failure isolation is bulletproof, add a disk retention policy, and add the operational glue (backups, cost tracking, Telegram health pings) that makes the system actually survive 30 days unattended.

**Requirements:** R15, success criteria (30 days unattended, zero missed days, no duplicate posts)

**Dependencies:** Units 1-8

**Files:**
- Create: `sidecar/jobs/retention.py` — daily job that prunes old video/audio/thumbnail files per retention policy
- Create: `sidecar/jobs/health_ping.py` — hourly job that verifies Postiz reachability, Gmail API reachability, Telegram bot reachability; Telegram notification on any failure
- Create: `sidecar/duplicate_guard.py` — checks before publish: has this topic URL already been posted in the last 30 days? If so, flag and alert rather than duplicate
- Create: `sidecar/tests/test_retention.py`, `sidecar/tests/test_duplicate_guard.py`, `sidecar/tests/test_health_ping.py`
- Modify: `sidecar/jobs/publish.py` — call `duplicate_guard.check()` before publishing; on hit, mark run `duplicate_blocked` and send Telegram

**Approach:**
- Retention: delete video/audio/thumbnail files older than `RETENTION_DAYS` (default 14) but KEEP the DB row with paths set to `null` and a `retention_pruned_at` timestamp. History stays; bytes don't.
- Duplicate guard: before publish, query `pipeline_runs` for any completed run in the last 30 days with the same `topic_url` or a high-similarity `topic_title` (Jaccard on word set, threshold 0.85). If hit, abort the publish for that topic and send a Telegram alert asking the owner to decide.
- Health pings: hourly background job calls `GET` on each dependency's health endpoint (Postiz `/auth/me` with service key, Telegram `getMe`, Gmail profile endpoint). Any failure → Telegram "service X unreachable" with last-success timestamp. Rate-limit alerts to max 1 per service per hour.
- Cost tracking: weekly summary job rolls up `pipeline_runs` cost columns and sends a Telegram Monday morning report with "videos posted this week, total cost, projected monthly burn".
- Zero-touch rollout note: after deploy, the first 7 days should have daily manual verification (owner spot-checks the morning runs); after 7 successful days, trust the auto-approve path fully.

**Patterns to follow:**
- Existing pipeline's cost reporting format.
- APScheduler cron + one-shot job patterns from earlier units.

**Test scenarios:**
- Retention: files older than N days get deleted, DB row preserved, retention timestamp set
- Duplicate guard: re-attempt the same topic within 30 days → publish blocked, Telegram alert sent
- Health ping: simulate Postiz down → alert fires; simulate recovery → next ping is healthy, no spam
- Weekly cost report: sums match manual SQL

**Verification:**
- Manual simulation of each failure mode produces the expected Telegram alert
- Retention job run in dry-run mode shows correct file list
- After 7 days of real running, `/runs` shows a clean history with no duplicates, and the weekly cost report matches reality

## System-Wide Impact

- **Interaction graph**: The sidecar is the new hub. It talks to: Gmail (pull), Claude (Sonnet for topic selection + captions), Telegram (inbound + outbound), existing pipeline (subprocess), Postiz (REST), optionally Instagram Graph API (direct fallback), Docker socket (restarts). Existing pipeline code is unchanged — it continues to talk to Claude, ElevenLabs, VEED, Pexels, Postiz exactly as it does today.
- **Error propagation**: Three tiers of failure boundary. (1) Individual pipeline step failures are already isolated inside `scripts/` code (thumbnail, avatar, etc. have their own try/except). (2) Per-video failures are isolated by the sidecar's pipeline runner (Unit 4) — one video never blocks the other. (3) Day-level failures (Gmail unreachable, no newsletter, Sonnet down) are isolated by the daily trigger job and surface as Telegram alerts, never as stack crashes.
- **State lifecycle risks**: SQLite writes from concurrent APScheduler jobs need serialization (SQLite handles this at file level with WAL mode). Pipeline subprocess writes to `output/` while the sidecar reads from it — filesystem race window is acceptable because the sidecar only reads post-completion. `.env` atomic write is critical — a half-written `.env` could corrupt the entire stack. Use the temp-file + rename pattern.
- **API surface parity**: All approval actions (Approve, Reject, Reschedule, Edit Caption) must be reachable from BOTH Telegram and the dashboard, and must update the same DB state. Duplication here is by design per R6 + R8.
- **Integration coverage**: Unit tests alone cannot prove the end-to-end flow works. A manual verification checklist in `deploy/portainer/README.md` covers: deploy → OAuth all accounts → manual trigger → receive Telegram preview → approve → see post on both platforms. This runs as the acceptance gate before the first autonomous 24-hour cycle.

## Risks & Dependencies

- **DS1520+ memory ceiling (8 GB)**: The single biggest operational risk. Mitigations: sequential pipeline runs only, Docker memory limits per service, retention policy for large files, Unit 9 health pings to catch OOM-driven restarts. If RAM is upgraded to 16 GB the whole plan becomes much more comfortable.
- **Postiz API field uncertainty for IG Collab and YT thumbnails**: Mitigated by the direct IG Graph API fallback (Unit 7) and existing Postiz poster TODO comments. The fallback path must actually work — not just be documented.
- **Postiz = self-hosted AGPL-3.0 OSS, not the hosted SaaS**: We are deploying `gitroomhq/postiz-app` from source via Docker Compose. It has no quota of its own, no usage meter, no feature gating — the whole free-tier vs paid-tier conversation does not apply. Rate limits that matter are the underlying platform APIs (Instagram Graph API daily quota, YouTube Data API daily units), which apply identically regardless of how we call them. No Postiz-side quota monitoring is needed; platform-side quota errors surface as normal API errors and are handled by the publish job's failure path.
- **Gmail OAuth refresh token expiry**: Refresh tokens can be invalidated by Google if unused for 6+ months or if the user changes their password. Mitigated by the hourly health ping (Unit 9) which will alert on auth failure. Manual re-OAuth flow is documented in Unit 1 README.
- **TLDR AI format drift**: If TLDR changes their HTML structure, LLM extraction should survive it (vs. a brittle regex). Mitigation already baked in via LLM extraction in Unit 3.
- **Docker socket privilege**: Acknowledged in the origin doc's Dependencies. The narrow wrapper in `docker_manager.py` limits the attack surface to container restarts only. Any future public exposure of the sidecar must remove this privilege.
- **Stack migration path**: The plan commits to portable Docker Compose. Any feature that relies on Synology-specific paths (`/volume1/`) must use env vars so the stack can move to a Mac or VPS without edits.
- **Cost runaway**: The weekly cost report is the canary. If a bug causes repeated retries, costs could spike fast. Mitigation: pipeline runner hard-caps subprocess retries at 1 per video per day; health ping catches loops.
- **Duplicate posting**: R15 success criterion says "zero duplicate posts". Unit 9's duplicate guard is the only defense. Worth verifying with an explicit integration test against historical runs.
- **"Zero missed days" is not a system guarantee, it's an external input contract**: The origin doc's success criterion "zero missed days across a 30-day rolling window" assumes TLDR AI publishes daily, Gmail delivers on time, and every LLM/VEED/Postiz API is up on that day. A single bad day from any of those external systems breaks the criterion through no fault of the pipeline. **Relaxed internal success criterion**: "≥95% of days *with a received TLDR newsletter* produce at least one published post". External-input gaps (no newsletter, API outages) are surfaced as Telegram alerts so the owner understands why a day was skipped. The original "zero missed" bar is retained as a north-star goal but not as a build gate.
- **Telegram polling reliability**: Long-polling can silently drop on flaky network. Mitigation: health ping every hour, auto-restart the bot coroutine on exception, log reconnect events.

## Documentation / Operational Notes

- `deploy/portainer/README.md` is the operator runbook — deployment steps, OAuth walkthroughs, recovery procedures, rollback instructions, how to rotate keys without downtime.
- Add a one-page architecture diagram to `docs/architecture/self-hosted-pipeline.md` showing the stack, volumes, secrets flow, and data flow. Link from the README.
- Update top-level `README.md` to mention the self-hosted mode vs. the local Mac mode.
- Cost calibration: after 7 days of operation, revisit the brainstorm's $1.88/video estimate and update the success criteria if the real number drifts significantly.
- Acceptance gate: the system is "live" only after passing the Unit 9 manual verification checklist AND surviving 24 hours of autonomous operation with 2 successful posts.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-06-end-to-end-pipeline-requirements.md](../brainstorms/2026-04-06-end-to-end-pipeline-requirements.md)
- Previous plan: [docs/plans/2026-04-06-001-feat-thumbnail-engine-plan.md](2026-04-06-001-feat-thumbnail-engine-plan.md) — status: completed
- Related learning: [docs/solutions/integration-issues/haiku-drops-version-number-periods-2026-04-06.md](../solutions/integration-issues/haiku-drops-version-number-periods-2026-04-06.md)
- Related learning: [docs/solutions/integration-issues/avatar-lip-sync-desync-across-segments-2026-04-05.md](../solutions/integration-issues/avatar-lip-sync-desync-across-segments-2026-04-05.md)
- Related code: `scripts/smoke_e2e.py`, `scripts/posting/postiz_poster.py`, `scripts/posting/social_poster.py`, `scripts/content_gen/script_generator.py`, `scripts/thumbnail_gen/`
- Related memories: `project_posting_layer`, `reference_tiktok_cover_limit`, `project_commoncreed`
- External: Postiz public API (`docs.postiz.com`), Instagram Graph API Collab docs, Gmail API `users.messages.list`, `python-telegram-bot` v22 docs, APScheduler docs
