# Changelog

All notable changes to the CommonCreed pipeline are documented here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions align with deploy tags.

## [Unreleased] — Engagement Layer v2

Three coordinated waves of engagement upgrades on top of the existing pipeline. Built in parallel on 11 feature branches via the `engage-v2-swarm` agent-team execution plan (see `docs/plans/2026-04-18-002-feat-engage-v2-agent-team-execution-plan.md`). Delivered 10/11 origin-plan units (A3 pending Unit 0.3 SFX sourcing at time of draft).

### Added

**Tier 0 — shared substrate**

- **Brand assets module** (`scripts/branding.py`) — single source of truth for CommonCreed navy/sky-blue/white hex constants, Inter font candidate lists, `find_font(weight)` helper, and `to_ass_color(hex)` → ASS BGR+alpha format converter. Inter v4.0 TTFs (Bold, Regular, SemiBold) committed under `assets/fonts/` (SIL OFL). `scripts/broll_gen/headline_burst.py` migrated as proof; other generators follow opportunistically. Sidecar Dockerfile COPY + fc-cache + Inter assertion block; `fonts-noto-color-emoji` apt package added for emoji fallback. (Unit 0.1)
- **libass caption-render smoke gate** (`scripts/video_edit/tests/test_caption_render_smoke.py`) — one-second ASS karaoke burn on a 1080×1920 black video. Sidecar Dockerfile gains `RUN ffmpeg -filters | grep -qE "^ . ass"` build-time assertion so a broken ffmpeg image fails early. Skipped on macOS dev; runs in container CI. (Unit 0.2)
- **Article text extractor** (`scripts/topic_intel/article_extractor.py`) — Trafilatura-based fetch + extract + paragraph filter; drops <40-char captions and sponsored-content lines; returns `None` when body <80 chars (paywall signal). Disk cache by URL hash under `~/.cache/commoncreed_articles/` with 7-day TTL. Wired into `_generate_script_voice_avatar` and `smoke_e2e.main()` with full failure isolation (never raises to caller). (Unit 0.4)
- **VideoJob + BrollSelector extension** (`scripts/broll_gen/registry.py` new) — single source of truth for 11 b-roll types via `BROLL_REGISTRY: dict[str, BrollMeta]` with `(needs_gpu, blocked_by_field_missing, description)`. Replaces hardcoded `cpu_types`/`gpu_types` literals in both orchestrators with dual-imported `cpu_types()` / `gpu_types()` calls. Four new VideoJob optional fields: `extracted_article`, `tweet_quote`, `split_screen_pair`, `keyword_punches` (plus `chart_spec` added by C2). Selector short-circuit at lines 104-108 replaced with `_compute_forced_primary_candidates(topic_url, extracted_article)` static helper — article URL + ≥2 body paragraphs now prefers `phone_highlight`, unblocking R1/R5/R6. (Unit 0.5)
- **Three-file registration linter** (`scripts/broll_gen/tests/test_registration_consistency.py`) — pure-ast pytest that locks the four sources of b-roll-type truth (`_VALID_TYPES`, factory if-chain literals, `_RESPONSE_SCHEMA` primary/fallback enums, `BROLL_REGISTRY` keys) together. Drift fails the build with a message naming the missing type + file. (Unit 0.6)

**Tier A — engagement floor**

- **Phone-highlight generator** (`scripts/broll_gen/phone_highlight.py`) — vertical phone mockup of the article being narrated, currently-spoken phrase highlighted in sky-blue with karaoke-style past-phrase dimming (55-alpha). Jinja template + Playwright screenshot-per-event + FFmpeg concat demuxer. Phrase chunker is a single-pass state machine (250ms silence gaps, conjunction-after-3-words, punctuation-end-of-word flush, hard 7-word cap). Haiku trim picks lead + 2 body paragraphs. Match-rate <60% logs WARN. iPhone chrome overlay PNG shipped as 1080×1920 RGBA placeholder (black rounded border + notch); production swap is a pure-asset update. (Unit A1)
- **Animated word-level ASS karaoke captions** (`scripts/video_edit/video_editor._build_ass_captions`) — per-word `Dialogue:` lines with ASS karaoke timing tags. Active word highlighted via thick sky-blue border-as-background (`\bord12 \3c`); inactive words navy outline. Inter font replaces Arial across all captions. Word-drift guard skips malformed segments with WARN. Brand colors flow through `to_ass_color` helper — no raw hex literals in ASS output. (Unit A2)

**Tier B — differentiator formats**

- **Tweet-reveal generator** (`scripts/broll_gen/tweet_reveal.py`) — CommonCreed-branded tweet card (white on navy matte, sky-blue verified checkmark SVG, 48px Inter Regular body). Animated like counter 0 → estimate over 1.5s with cubic ease-out; card slide-up + fade-in during first 0.4s; final card held through target duration. 30 Playwright frames (CSS-driven counter/translate/opacity via Jinja per-frame render), FFmpeg concat demuxer. Selector extension: Haiku call populates `tweet_quote: {author, handle, body, like_count_estimate, verified}` when article quotes a named person. (Unit B1)
- **A/B split-screen composer** (`scripts/broll_gen/split_screen.py`) — 540×1920 per-side hstack with 12px white outer glow + 6px sky-blue divider, all in a single `-filter_complex`. Invokes existing generators (browser_visit, image_montage, stats_card) with new `width_override` kwarg; `_SideJobProxy` lets each side carry its own topic/script. Concurrent sub-generator invocation via `asyncio.gather`. Selector populates `split_screen_pair: {left, right}` for A-vs-B topics. (Unit B2)
- **Editing-rhythm rules in timeline planner** (`scripts/broll_gen/browser_visit._plan_timeline`) — 2026 short-form rhythm appended to `_TIMELINE_SYSTEM_PROMPT` (cut every 2–4s, burst sequences every 15s, target ~target_duration_s/2.5 segments). Budget enforcement: `MAX = max(8, int(target/1.5))`, `hard_cap = int(MAX*1.5)`; if Haiku overshoots, one retry with compaction instruction; truncate on still-over. Padding only kicks in when Haiku under-returns, so the rhythm rules can legitimately produce denser cuts than the caller's `n_segments` target. (Unit B3)

**Tier C — cinematic data viz**

- **Remotion sidecar container** (`deploy/remotion/`) — Node 20 + Chromium + ffmpeg + fontconfig; Express HTTP server with `POST /render` + `GET /healthz`; three templates (BarChart, NumberTicker, LineChart) animated bar chart / number ticker / line chart at 1080×1920 / 30fps. Build context = repo root (matches Unit 0.1 compose fix). `docker-compose.yml` peer service on `commoncreed` network with shared `commoncreed_output` volume. Remotion 4.0.205 pinned. (Unit C1)
- **cinematic_chart b-roll type** (`scripts/broll_gen/cinematic_chart.py`) — async `httpx.AsyncClient` posting to the C1 sidecar's `/render` endpoint; BrollError on non-200/timeout. Haiku helper `extract_chart_spec(script_text, topic)` identifies numeric comparisons (bar/ticker/line). Env-flag gated: `CINEMATIC_CHART_ENABLED=true` required; selector gates separately via `_compute_chart_forced_candidates(chart_spec)` so chart wins over `phone_highlight` when both article + chart_spec fire. Dual-layer defense (selector refuses + generator raises if flag off). (Unit C2)

**Tier 0 (final) + Tier A (completion)**

- **SFX library + audio mix helper** (`assets/sfx/*.wav` × 15, `scripts/audio/sfx.py`) — 15 curated short transient SFX (cut_whoosh/swoop/swish, pop_short/high/low, ding_clean/chime, tick_soft/hard, thud_soft/dramatic, whoosh_long, swipe_in/out) synthesized in-repo via `scripts/audio/_generate_sfx.py` (numpy + scipy.io.wavfile). Each <50 KB, mono int16 @ 44.1 kHz, peak-normalized to -3 dB. License: repo-CC0. `pick_sfx(category, intensity, seed)` seed-deterministic file selection; `mix_sfx_into_audio(voiceover_path, sfx_events, output_path)` single-pass ffmpeg amix with per-event adelay and -18 dB SFX weights vs 1.0 voiceover. `.gitignore` amended with `!assets/sfx/*.wav` whitelist so the bundle survives the blanket `*.wav` ignore. (Unit 0.3)
- **Zoom-punch + SFX combined final-pass** (`scripts/video_edit/video_editor._apply_engagement_pass`, `scripts/content_gen/keyword_extractor.py`) — Claude Haiku extracts 4–7 highest-value tokens (proper nouns, dollar figures, percentages, version numbers) per script; drift-guard drops any word not matching caption_segments by case-insensitive text. Per-punch zoom curve: `if(between(t, t0, t0+0.2), delta*sin(PI*(t-t0)/0.2), 0)` summed across punches (light=0.10, medium=0.15, heavy=0.20). SFX pre-mixed into voiceover via Unit 0.3's `mix_sfx_into_audio`, then a single combined ffmpeg filter_complex (scale + crop + ass=burn) replaces the prior two-pass flow. `_write_with_captions` preserved verbatim via `_finalize` router; all non-BROLL_BODY call sites stay byte-for-byte identical. Thumbnail-hold alignment: keyword_punches + sfx_events time-shifted by `_THUMBNAIL_HOLD_S`; voiceover prepended with silent leader. Failure isolation: keyword-extraction wraps in try/except with WARN-and-continue (never breaks the pipeline). (Unit A3)

### Changed

- `sidecar/Dockerfile` build context migrated from `sidecar/` to repo root (via `deploy/portainer/docker-compose.yml`) so `COPY assets/fonts/` and `COPY sidecar/requirements.txt` both resolve at build time. Existing COPY paths rebased to `sidecar/*` prefixes.
- `scripts/pytest.ini` gains `pythonpath = .` so tests' dual-import fallback is deterministic regardless of pytest positional-arg order.
- `scripts/broll_gen/factory.py` accepts `width_override` kwarg, plumbed through `browser_visit`, `image_montage`, `stats_card`, `headline_burst` for the A/B split-screen composer.

### Fixed

- `scripts/broll_gen/selector.py` short-circuit at lines 104–108 previously forced `["browser_visit", "headline_burst"]` for every non-social URL, making R1/R5/R6 b-roll types unreachable. Replaced with extraction-aware gating. (Unit 0.5)

### Infrastructure / Test discipline

- **Test parallelism model**: 11 feature branches under `feat/engage-v2/*`, executed via `engage-v2-swarm` agent team with per-unit worktrees under `.worktrees/`. All merges fast-forward; no merge commits. Conflict register (`docs/plans/2026-04-18-002-engage-v2-conflict-register.md`) governs shared-file serialization.
- **Test count**: 50 pre-run → 120 at time of draft (+70 new tests). 1 skipped (libass smoke on macOS; runs in container CI). Zero regressions.
- **Follow-ups captured**:
  - `scripts/broll_gen/stats_card.py` layout at 540-px width needs font auto-scaling (B2 deferred per scope).
  - `deploy/remotion/` needs `npm install` in a network-capable env to generate `package-lock.json` before first `docker build`.
  - 5 pre-existing failures in `test_browser_visit.py` / `test_stats_card.py` patch module-level symbols that don't exist; unrelated to this run, flagged separately.

### Rollout

Per `docs/plans/2026-04-18-001-feat-engagement-layer-v2-plan.md` § *Verification Strategy & Rollout*:

- **Tier A canary**: 1 video/day for 3 days; manual review.
- **Tier A production**: 14-day A/B vs baseline; gates = composite retention ≥+10%, no first-3-s regression, ≤5% per-platform loss, ≤90s render-time delta.
- **Tier B opt-in**: 1 week via topic flag; then automatic via selector.
- **Tier C opt-in**: 2 weeks via `CINEMATIC_CHART_ENABLED=true`; then automatic.

Per-feature env-flag kill switches: `ENGAGEMENT_PHONE_HIGHLIGHT_ENABLED`, `ENGAGEMENT_WORD_CAPTIONS_ENABLED`, `ENGAGEMENT_ZOOM_PUNCH_ENABLED`, `CINEMATIC_CHART_ENABLED` (all default `true` after canary; flip to `false` for runtime rollback).
