---
date: 2026-04-21
topic: story-channels-v1
---

# Story Channels v1 — Vesper (Horror, Shorts-First) + Thin Channel Profile

## Problem Frame

The CommonCreed pipeline proves end-to-end that a single avatar-fronted channel can be automated to daily posts across IG Reels, TikTok, YouTube Shorts, and YouTube long-form via a self-hosted Postiz layer on the Ubuntu server at `192.168.29.237`. CommonCreed is currently paused on avatar visual quality. The owner's meta-goal is $5,000+/month recurring income; the owner wants a second production workstream — a **faceless, picture-and-voiceover horror story channel** — that runs in parallel to CommonCreed's avatar work without contending for the same compute or review budget.

Three things make this distinct from CommonCreed:

1. **No avatar.** Stories are narrated over generated pictures (slow Ken Burns, subtle I2V on hero shots). This removes the most expensive and brittle part of CommonCreed (EchoMimic / VEED avatar generation) and replaces it with a much cheaper visual layer. Vesper can ship while CommonCreed's avatar problem remains unsolved.
2. **Shorts-first sequencing.** Launch with vertical shorts only. Long-form compilations ship later, stitched from retention-validated short-form stories.
3. **Thin factory profile, not a full abstraction.** The pipeline is parameterized by `channel_id` and stops hardcoding "CommonCreed" strings in shared code, but v1 does **not** build a 14-field `channel_profile` schema, a queue scheduler, or a dummy-channel-2 acceptance test. The real abstraction shape will be cleaner after one real repetition (channel #2) than after one speculation.

**v1 scope:** Ship *Vesper* (horror narration, shorts-first) to professional retention quality, with shared pipeline code parameterized by `channel_id` so a future channel #2 is a config drop-in without a pipeline rewrite — but without pre-building the schema for channels that don't yet exist.

**Brand name:** *Vesper* — Latin "evening", understood across Romance languages (Spanish *víspera*, Italian *vespero*, French *vêpres*, Portuguese *véspera*), loanword in English/German/Russian/Hindi. Two syllables, no hard phonemes — pronounceable globally. Horror/paranormal fit via the evening/twilight connotation. Handle `@vesper` verified free on Instagram + YouTube; TikTok + X need final confirmation on namechk.com at claim time. If `@vesper` is unavailable on any platform, fallback to `@vesper.tv` or `@thevesper`. Working-name from the earlier brainstorm (*Vesper*) is retained as a phrase in brand voice (tagline candidate: *"Transcribed at Vesper — nothing here begins before dark"*).

## Channel #1 Positioning — Vesper

- **Narrator persona:** "The Archivist" — a low, tense, semi-whispered voice that frames stories in third-person remove ("this was shared with me", "the following is taken from…"). Not a participant, not a therapist, not a dramatic reader; a quiet custodian of the account. Reuses chatterbox with a channel-specific reference clip.
- **Sub-niche:** Night-shift encounters (truckers, night-watch security, hospital staff, ER nurses), rural-America liminal spaces (backroads, empty diners, small-town gas stations, isolated state parks), and quiet supernatural paranoia. Deliberately narrower than "general horror" to give the algorithm a clear fingerprint.
- **Format signature:** Every video opens on a black frame with a single timestamp in bone-on-black typography (e.g. `02:47`), held for ~1 s before the cold-open line. This is the channel's single most-repeated brand anchor across shorts, longs, and thumbnails — cheap to render, visually distinctive, instantly recognizable. The timestamp is always within the Vesper window (late evening through the pre-dawn hours), reinforcing the brand name.
- **Differentiation thesis:** The wedge against 2026's saturated faceless-horror field is not "better AI" — it's *quieter-than-average horror with a consistent narrator persona and a time-stamp identity*. Most 2026 AI horror channels lean loud and jumpscare-dense; Vesper deliberately runs slow-tension. Retention gate tests this hypothesis.

## Requirements

### Tier A — Thin channel profile (must land before Vesper content ships)

- **R1. Thin channel profile.** Introduce a per-channel Python/YAML module (e.g. `channels/vesper.py`) holding the values that would otherwise live as env vars or module constants: reference-audio path, Flux prompt prefix/suffix, grade preset, source-config (subreddit list for Vesper, RSS feeds for future news channel), cadence, Postiz identifier/profile values, Telegram-message prefix, brand-palette hex values, `languages_enabled: ["en"]`. Not a schema, not a registry. A second channel is "add a second module". The full structured schema is extracted in the `story-channels-second-niche` brainstorm, when the channel-2 shape is concrete.

- **R2. Shared pipeline code is `channel_id`-parameterized.** The pipeline entry-point takes `channel_id` as a CLI / top-level parameter. Shared pipeline code (script generator, chatterbox client, video assembler, Postiz poster, analytics tracker, Telegram bot, thumbnail compositor) contains zero `"CommonCreed"` or `"Vesper"` string literals or CommonCreed-specific constants. A channel's runs fetch its module and inject the values at the call site. Cron has one entry per channel, staggered.

- **R3. Postiz integration takes an identifier-set from the channel profile.** The Postiz client is invoked with the channel profile's Postiz identifiers (`profile` strings or whatever unit the current Postiz version exposes — verified during planning). No new Postiz instance, no new workspace. One API key today is acceptable; per-channel Postiz API-key isolation is deferred until a second approver or operator exists.

### Tier B — Vesper content pipeline (shorts-first)

- **R4. Reddit-sourced, LLM-rewritten stories.** Vesper ingests top self-text posts from a configured subreddit list (initial: `r/nosleep`, `r/LetsNotMeet`, `r/ThreeKings`, `r/Ruleshorror`, `r/creepyencounters`). A Claude Sonnet call rewrites each story in the Archivist's voice (see positioning) at a bounded length (short = 150-200 spoken words; long = 1000-1400 spoken words per segment). A **prompt-injection guardrail** wraps Reddit content in explicit delimiters, instructs the model to treat ingested text as data not instructions, and runs an LLM-classifier pass that rejects outputs deviating from expected narrative shape (contains URLs not in source, contains brand names, length out of bounds, off-niche content). A **monetization-first mod filter** rejects stories that (a) name real people, (b) describe self-harm or suicide with method specificity, (c) involve minors as victims or perpetrators, (d) describe real identifiable crimes, (e) contain graphic violence likely to trigger YouTube limited-ads. Each published video's description credits the source (subreddit + post title), includes a takedown contact email, and sets the platform's AI-generated-content disclosure flag.

- **R5. Dedup against prior posts.** Stories are deduplicated against Vesper' prior post history (stored in the existing `AnalyticsTracker` SQLite scoped by `channel_id`, or an equivalent per-channel table — planning decides). A story whose source URL or normalized title was posted in the last 180 days is skipped. The 180-day window is the *source-side* dedup boundary, independent of the 30-day retention-measurement window in Success Criteria.

- **R6. Archivist voice profile via chatterbox.** Vesper ships with a distinct chatterbox voice reference (low, tense, semi-whispered male read — not the CommonCreed narrator). Reference path is in the channel profile. Planning verifies whether chatterbox's runtime reference swap is sufficient or whether the HTTP contract needs to accept a reference per `/tts` call, and whether a single reference clip plus style prompt is enough for the Archivist's whispered register or whether the reference itself must be a whispered clip. Prosody-cue support in `ChatterboxVoiceGenerator` (today silently drops style params) is resolved as part of this work or explicitly deferred with a fallback reference-clip strategy.

- **R7. Hybrid visual stack — Flux stills + Ken Burns + hero-shot I2V + anti-slop safeguards.** ~80% of shots per video are Flux-generated cinematic horror stills animated with Ken Burns pan/zoom, color grade, film grain, and vignette. ~20% ("hero" beats — a reveal, a face, a moving shadow) get local I2V (Wan2.2-class family; exact model TBD in planning) generating 4-8 seconds of subtle motion. Hero-shot selection is driven by the script/timeline planner (proper noun, jumpscare moment, emotional climax). **Anti-slop safeguards** (non-optional): at least N% of still beats receive parallax/2.5D treatment rather than flat Ken Burns; an overlay pack (film grain, dust, light leaks, subtle flicker, low fog) is applied throughout; shot durations are bounded to a min/max (both to break the "fixed-4s slideshow" rhythm and to couple to VO cadence — see R8 pacing rule); at least one non-Ken-Burns camera move (push-in, rack-focus sim, whip-cut, match-cut on motion) per video. This is what keeps the 80% still-based beats from reading as AI slideshow.

- **R8. Short-form pipeline (60-90 s, 9:16) — the entire v1 content surface.** Vertical shorts with the **timestamp cold-open** (see format signature) held ≥0.8 s on black, the first narrative line whispered over the same black frame or a first still, and the hook resolved in the first 2-3 seconds. Word-level animated captions and SFX transients on cuts come from engagement-layer-v2 (hard dependency — see below). Pacing rule: shot duration bounded to [min, max] seconds driven by VO word-rate; SFX transient density capped during whispered delivery. Hook visual grammar: black-frame-over-timestamp → first still at line one → captions appear from line two onward (not in the cold-open frame). One short produced per day; cross-posted to IG Reels, YT Shorts, TikTok via Postiz.

- **R9. Long-form pipeline (8-12 min, 16:9) — gated to v1.1.** Long-form ships only after Vesper has **10-15 shorts with retention data** (~3-4 weeks post-launch) so that compilations chain actual winners. The long-form track adds: 16:9 video assembly, 16:9 thumbnail compositor variant, interstitial cards between stories (visual template spec'd in Visual Language below), YouTube-native chapter-list emit on upload, and chatterbox concat across ≥10 minutes (validated during gating). Until the gate clears, R9 is not built.

- **R10. Thumbnail with Vesper visual language.** Thumbnails follow the spec in Visual Language below (bone-on-black title, moody cinematic portrait, timestamp motif when natural, never-do list applied). Produced by the existing thumbnail engine after it is refactored to accept palette + aspect as channel-profile config (today both are hardcoded CommonCreed constants — planning resolves). YouTube A/B thumbnail swap is out of scope for v1 and revisited after the first long-form retention baseline.

- **R11. Telegram approval reuses CommonCreed's flow.** Same bot, same owner chat, same single-owner allowlist. Messages carry a channel-prefix badge (e.g. `[Vesper]`, `[CommonCreed]`). Approval callback posts to that channel's Postiz identifier-set. Per-channel approver scoping is deferred to whenever a non-owner approver is onboarded.

- **R12. Multi-language reserved to `languages_enabled` on the profile only.** The channel profile carries `languages_enabled: ["en"]` for Vesper. The pipeline does not factor in translation, per-language voice mapping, per-language subtitle emit, or multi-audio YouTube upload in v1. Full multi-lang shape is designed in the `story-channels-multilang` brainstorm once English traction is proven — designing it now is triple-speculative (pre-traction, pre-first-real-alt-render, pre-platform-capability-audit).

## Visual Language — Vesper

### Brand palette (distinct from CommonCreed navy/sky-blue at thumbnail scale)

- `#0A0A0C` near-black — dominant background, thumbnail matte
- `#E8E2D4` bone / aged paper — primary title and caption-inactive color
- `#8B1A1A` oxidized blood — keyword-punch accent, sparing use (≤2% of frame area)
- `#2C2826` warm graphite — mid-shadow, card backgrounds, grade shadow tone

### Typography

- **Thumbnail & timestamp:** a heavy-weight serif or slab (final selection in planning — candidates: Cormorant Garamond Bold, IM Fell DW Pica, Libre Caslon Display). High-contrast, wide tracking on timestamps.
- **Captions (R8):** inherits engagement-v2 word-level animation but overrides: bone color for inactive words, oxidized-blood for active/keyword-punch word, near-black stroke at 85% opacity, animation easing on the slower end of the v2 range (matches whispered pacing, avoids strobe feel).
- **Interstitial cards (R9, when it ships):** same serif, bone-on-near-black, single-line title + small-caps "STORY N OF 6" label, held ~2.5 s, center fade-in/out.

### SFX palette (override engagement-v2 defaults)

The CommonCreed SFX pack is whooshes and UI blips — wrong palette for horror. Vesper overrides engagement-v2's SFX pack with: low drones, sub-bass thumps, reverb tails, single-note risers, ambient wind/static beds, distant-footstep stingers. Engagement-v2's SFX-pack parameter (or wherever the pack is defined) is parameterized per channel; Vesper ships with its own vetted pack. A "no-go" list: no positive tech whooshes, no UI blips, no keyboard clicks.

### Anti-slop requirements (enforcement for R7)

- Parallax/2.5D motion on ≥20% of still beats (above and beyond the 20% I2V hero shots)
- Overlay pack baseline on every short: film grain (subtle), dust particles (occasional), light-leak or projector-flicker transients (keyword-punch aligned)
- Shot duration varies: no more than 3 consecutive shots at the same duration
- ≥1 non-Ken-Burns camera move per short (push-in, rack-focus sim, whip-cut, match-cut-on-motion)
- Transition vocabulary: default hard cut; dip-to-black on scene change; SFX-synced flash on keyword punch; no cross-fade unless explicitly tagged for a specific slow-tension beat

### Thumbnail spec (R10)

- Composition: rule-of-thirds subject placement, large negative-space zone (top-left or center-bottom) for title, never a centered subject with text around it
- Title: ≤5 words, bone color, heavy serif, 1-2 lines max
- Optional timestamp element (`02:47` style) bottom-right at 30% subject size
- Face/no-face rule: face present ~50% of thumbnails; when present, eyes are not the focal point and subject is partially obscured (shadow, hand, hair)
- Never-do list: no red arrows, no circled elements, no shocked-face close-ups with open mouth, no bright saturated backgrounds, no more than 2 saturated hues total

## Success Criteria

### Pre-launch quality gate

- At least 10 shorts produced end-to-end and reviewed by the owner before public launch. Owner rates retention feel (voice + pacing + visuals) ≥ 4/5 on a blind side-by-side against a reference set of 2026 top-quartile horror shorts.
- Handle `@vesper` verified free on Instagram + YouTube at brainstorm time. TikTok + X need final confirmation on namechk.com before the quality-gate batch is generated; if `@vesper` is taken on either, claim `@vesper.tv` or `@thevesper` instead. Brand name itself does not change at this stage (Vesper survives handle-variant fallbacks).
- Engagement-layer-v2 word-captions + SFX + keyword-punch are shipped. Vesper does not launch with a stripped-polish fallback — the retention targets assume polished captions, and without them the gate measures noise.

### Production volume (post-launch, shorts-first)

- 7 shorts/week cross-posted to IG Reels, YT Shorts, TikTok, automatically. Long-form is not in this phase.
- Owner review time: ≤ 45 min/day average across Vesper and CommonCreed combined, with a ≤ 60 min/day spike allowance during Vesper' first 2 weeks. If the cap is exceeded, trim-under-stress rules apply in order: (1) sampled approval on CommonCreed shorts (approve N-of-M, not all), (2) auto-approve below an automated quality-score threshold (planning defines the score), (3) thumbnail-only review on near-duplicate stories.

### Retention gate (month-3 traction decision for channel-#2 work)

- Proceed to channel-2 work iff **all** of:
  - YouTube subscribers ≥ 2,000
  - Trailing-14-day YouTube Shorts average view duration ≥ 55%
  - Trailing-14-day IG Reels completion rate ≥ 25%
  - Trailing-14-day TikTok avg watch time ≥ 55%
  - Monetized-RPM × view-volume projects to ≥ $100/month sustained run-rate
- Hold-and-iterate iff 3 of 5 hit. Kill-and-pivot-niche (new sub-niche, new voice, new thumbnail language) iff ≤ 2 of 5 hit. Decision date: month 3 post-launch; recorded on the doc.
- Pre-launch benchmark pass: 2-4 hours of sampling top-quartile 2026 horror shorts + longs to confirm whether 55% AVD / 25% completion are p50 or off-reality; numbers are updated before launch if benchmarks disagree.

### R9 long-form gate (v1.1)

- Long-form pipeline (R9) is built and first long ships only after Vesper has 10-15 shorts with ≥14 days of retention data. The first long stitches only shorts above the channel's own p50 AVD.

### Cost model (derived, with ceilings)

Target costs per produced video (derived, not asserted):

| Component | Short (60-90s) | Long (8-12 min) |
|-----------|----------------|------------------|
| Flux stills (~25 shots for short, ~80 for long at $0.02-0.04/image) | $0.50-1.00 | $1.60-3.20 |
| Chatterbox TTS (self-hosted) | ~$0.00 | ~$0.00 |
| Local I2V hero shots (~5 for short, ~16 for long; amortized GPU time) | $0.05-0.25 | $0.15-0.80 |
| LLM rewrite + timeline planner (Claude Sonnet) | $0.05-0.15 | $0.30-0.60 |
| Retry buffer (1 in 5 shorts regenerates) | $0.20-0.40 | $0.60-1.20 |
| **Target total** | **~$0.80-1.80** | **~$2.65-5.80** |

Budget ceilings: **$1.50/short** and **$6.00/long** (above the target range, below portfolio-breaking). Planning revises if actual first-week costs breach the ceiling; the decision is *raise the ceiling or cut a component* — not "absorb overage silently". Cloud-I2V-on-every-shot is explicitly ruled out (would breach $6 long ceiling with a single shot at the high end of the $3-8 cloud-I2V range).

### Operational

- No CommonCreed run is delayed or fails due to Vesper sharing the Ubuntu server. Verified by (a) measuring CommonCreed's current peak CPU + RAM + GPU-plane footprint during planning and (b) one week of parallel operation without alerts after launch. Stagger schedule chosen so Vesper' shorts cron and MoviePy assembly peak does not overlap CommonCreed's assembly window.
- The sidecar's MoviePy memory peak (recently bumped 2→4 GB) is re-measured under Vesper long-form when R9 ships; additional bump is acceptable if the 8 GB host can absorb it.

## Scope Boundaries

- **Out of scope: channels 2 through 15.** Thin profile is in; full factory schema is not. Additional channels are gated on Vesper' traction gate above — not on calendar time.
- **Out of scope: long-form pipeline (R9) in v1.** R9 is gated to v1.1 on short-form retention data.
- **Out of scope: full multi-language scaffolding.** Only `languages_enabled` field on the thin profile; no translation path, no per-language voice map, no multi-audio upload.
- **Out of scope: adult / NSFW content.** Platform bans on IG and YouTube, Adsense disqualification, and brand contamination across the Postiz workspace make this a hard no.
- **Out of scope: non-horror niches for this brainstorm.** Deferred to future channel profiles.
- **Out of scope: separate Postiz instance per channel.** One self-hosted Postiz, per-channel identifier scoping.
- **Out of scope: new GPU server / hardware changes.** Reuse existing Ubuntu server + existing fal.ai / RunPod access patterns.
- **Out of scope: verbatim-Reddit reposting.** All stories are rewritten.
- **Out of scope: source-video clipping.** Visuals are generated, not sourced.
- **Out of scope: avatar / lip-sync.** Vesper is faceless.
- **Out of scope: final handle variant if `@vesper` is squatted on TT/X.** Fallback to `@vesper.tv` or `@thevesper` at claim time if needed; fallback is not a brainstorm decision.
- **Out of scope: YouTube A/B thumbnail swap** until after first long-form baseline.
- **Out of scope: per-channel approver scoping in Telegram allowlist.** Deferred until a non-owner approver exists.

## Key Decisions

- **Thin profile, not factory schema.** Rejected the full 14-field `channel_profile` construct after four reviewers converged on YAGNI. Scaffolding's shape is discovered on channel #2, not speculated on channel #1. What matters for v1 is (a) zero hardcoded CommonCreed/Vesper strings in shared code and (b) `channel_id` as the entry-point parameter.
- **Shorts-first, long-form gated on retention data.** Long-form explicitly stitches "validated short-form stories" — we use that dependency as the phase boundary. Halves v1 production surface and delays the heaviest review burden until the system is stable.
- **Engagement-layer-v2 is a hard blocker, not a soft dependency.** Retention targets presume polished word-level captions + SFX + keyword punch. Launching stripped invalidates the gate. If v2 slips, Vesper launch slips with it.
- **Channel #1 niche = horror with a specific wedge.** Archivist narrator + night-shift/rural-America/liminal-spaces sub-niche + timestamp cold-open. The wedge is tested by the retention gate; if it misses, the kill-and-pivot branch picks a different sub-niche.
- **Horror RPM treated as a risk, not a feature.** $4-10 RPM range is quoted as best-case; limited-ads under YouTube's 2024-2026 advertiser-friendly guidelines tightening could land Vesper at $1-3. Mod filter is scoped to monetization-first (not only age-gate avoidance). Traction gate evaluates on monetized-RPM × views, not AVD alone.
- **Reddit source accepted with explicit risk policy.** Transformation + attribution is the posture; on top, we ship (a) takedown email in description, (b) rapid-unpublish runbook, (c) source-deletion detection, (d) >2% DMCA in 60 days triggers pivot to LLM-original seeded from public-domain horror themes + 1960s-70s paranormal archives.
- **Prompt-injection guardrail is required on Reddit → Claude path.** Wrap content in delimiters, instruct model to treat as data, post-filter outputs. Horror genre makes adversarial content indistinguishable from legitimate prose on vibes alone — we don't rely on vibes.
- **AI-generated-content disclosure flags set on every upload.** YouTube, TikTok, Instagram. Missing these penalizes the shared Postiz workspace and cascades to CommonCreed.
- **Vesper brand palette = near-black + bone + oxidized-blood + graphite.** Explicitly distinct from CommonCreed navy/sky-blue at thumbnail scale to prevent brand-bleed across the shared engagement-v2 primitives.
- **SFX pack override per channel.** Engagement-v2's SFX pack is parameterized per channel; Vesper ships its own (drones, sub-bass, risers, reverb tails, ambience). Tech whooshes are never used.
- **Cost caps derived, not asserted; ceilings raised if derivation doesn't close.** Target ~$0.80/short, ~$3.50/long; ceilings $1.50/short, $6/long. If first-week costs exceed ceilings, decision is raise or cut — not absorb silently.
- **Review budget raised to 45 min/day avg, 60 min/day spike.** 30 min/day was structurally unachievable across two channels. Trim-under-stress rules explicit.
- **Handle viability verified before pre-launch batch.** If no acceptable Vesper variant is available on IG/TT/YT, brand renames before thumbnails / descriptions / voice-identity decisions are locked.
- **Brand = *Vesper*.** Selected for (a) universal pronounceability (2 syllables, no hard phonemes), (b) cross-language recognition (Latin "evening"; native in Spanish/Italian/French/Portuguese, loanword in English/German/Russian/Hindi), (c) horror/paranormal fit via the evening/twilight/evensong connotation, (d) Archivist-persona coupling (vespers = monastic evening prayers, watchful and quiet), and (e) handle `@vesper` verified free on IG + YT with fallback variants if TT/X require them.
- **One Postiz, per-channel identifier scoping.** Multi-workspace Postiz rejected. API-key isolation deferred until a second operator exists.

## Dependencies / Assumptions

- **Hard dependency: engagement-layer-v2 shipped** (word captions + SFX + keyword punch). Vesper launch is gated on this. Engagement-v2's SFX-pack + typography parameters are per-channel-overridable by launch — planning confirms the override surface.
- **Hard dependency: the existing chatterbox sidecar and pipeline.** Chatterbox runtime reference swap (or contract extension) is resolved during planning; if it's impossible in the current shape, Vesper launch is gated on whichever mechanism is chosen.
- **The existing thumbnail engine** is extended in planning to accept palette + aspect as config. R10's spec is implementable only after that extension; scope is acknowledged in planning as "refactor, not config drop-in".
- **Ubuntu server `192.168.29.237` headroom** is measured, not assumed. Planning measures CommonCreed's current peak CPU+RAM+GPU-plane footprint during typical runs before committing the stagger schedule. If combined load exceeds the 8 GB host, additional capacity planning branches in.
- **fal.ai + RunPod budget** supports Vesper' daily Flux + occasional Wan2.2-class I2V within the derived cost ceilings. If actual costs breach the ceilings in the first week, caps are raised or components cut.
- **Reddit API access** is available (PRAW or commercial tier — planning picks). If Reddit's 2026 commercial-access terms require enterprise licensing for LLM-derivative use, Vesper pivots to the LLM-original fallback source.
- **New OAuth tokens** for Vesper' IG + TikTok + YouTube accounts are issued under the same owner identity as CommonCreed (single-operator). A compromise of Vesper' tokens does not compromise CommonCreed's tokens because Postiz integrations are per-account — but a single cascading policy strike on the owner identity affects both. This is accepted for v1.
- **Telegram bot** is reused (single owner, existing allowlist). Channel-prefix in messages is added in planning.
- **The owner provides a horror-narrator reference clip** (30-60 s whispered, tense, mid-pitch male read) before pre-launch batch generation. Public-domain audiobook excerpt or custom recording. If the reference doesn't deliver the Archivist register at generation time, R6's deferred fallback strategies apply (whispered-reference-clip vs prosody-prompt).

## Outstanding Questions

### Resolve Before Planning

_All remaining product decisions are resolved. Launch-day ops tasks (handle claim, voice reference recording) are captured as pre-launch-batch prerequisites, not planning blockers._

### Deferred to Planning

- **[Affects R1/R2][Technical]** Thin profile surface — exactly which values move from env/constants to the channel module, by module. Planning audits `scripts/commoncreed_pipeline.py`, `scripts/voiceover/chatterbox_generator.py`, `scripts/video_edit/`, `sidecar/postiz_client.py`, `scripts/thumbnail_gen/compositor.py`, `scripts/analytics/`, `scripts/telegram_bot/` for CommonCreed-coupled constants and proposes the full list.
- **[Affects R3][Technical]** Postiz identifier scoping — exact mechanism in current Postiz version (profile strings, integration IDs, or similar) and whether Vesper' accounts need to be added via Portainer UI or API.
- **[Affects R4][Technical]** Reddit ingestion mechanism — PRAW with dedicated OAuth app, Reddit commercial data tier, or a hybrid. Decision depends on 2026 Reddit TOS confirmation during planning.
- **[Affects R4][Technical]** Prompt-injection guardrail implementation — delimiter scheme, output-shape validator rules, LLM-classifier pass (same or different model as the rewrite).
- **[Affects R4][Technical]** Monetization-first mod-filter — regex + LLM classifier split; run pre-rewrite, post-rewrite, or both.
- **[Affects R4][Technical]** LLM rewrite style prompt and attribution-embed format.
- **[Affects R5][Technical]** Dedup data store — extend `AnalyticsTracker` with `channel_id` scoping, or per-channel table. Bias toward the former unless a concrete reason emerges.
- **[Affects R6][Needs research]** Chatterbox per-channel reference swap mechanism — runtime arg vs sidecar contract extension vs per-channel client instantiation.
- **[Affects R6][Needs research]** Chatterbox prosody-cue effectiveness for whispered horror delivery. If the current silently-dropped style param can't be made to work, the whispered register comes from the reference clip alone.
- **[Affects R7][Technical]** Flux variant — 1-dev local vs 1.1-pro via fal.ai. Benchmark per-image cost and latency in planning.
- **[Affects R7][Technical]** Local I2V model choice — Wan2.2 I2V vs CogVideoX-5B vs newer 2026 open. Benchmark on target GPU plane.
- **[Affects R7][Technical]** Hero-shot selection heuristic — likely script-planner-emitted tags (emotional-climax, proper-noun, reveal-moment), biased toward climax beats over literal proper-noun hits.
- **[Affects R7][Technical]** Parallax/2.5D implementation — depth-estimator + displacement vs LoRA-style cinematic motion vs template-based camera moves.
- **[Affects R7][Technical]** Overlay pack licensing — sourcing grain/dust/flicker/fog assets under commercial-use license.
- **[Affects R8][Technical]** Short-form hook engine — prompt template vs hook-archetype library. Constrained by format signature (black-frame timestamp → line 1 → captions from line 2).
- **[Affects R8][Technical]** Pacing rule implementation — how the timeline planner bounds shot duration to VO word-rate.
- **[Affects R10][Technical]** Thumbnail engine refactor — palette-as-config + aspect-as-config + font-as-config. Scoped as refactor during planning.
- **[Affects R10][Technical]** Cinematic portrait render mode for thumbnails — Flux prompt template for the composition spec.
- **[Affects R11][Technical]** Telegram message channel-prefix format and any UI badge on inline keyboards.
- **[Affects R2][Technical]** Ubuntu server CPU/RAM/GPU footprint under combined load; exact stagger schedule.

## Spin-Off Brainstorms (recommended)

- **`story-channels-second-niche`** — Scoped when Vesper clears the traction gate. Picks channel-#2 niche and uses that concrete repetition to extract a real structured channel_profile schema from Vesper' thin module. This is when the full factory abstraction is actually designed.
- **`story-channels-multilang`** — Ship multi-lang fan-out once English traction is proven. Covers translation quality gate, per-language voice map, per-language IG/TT account strategy, YouTube multi-audio upload automation, per-language moderation (native-speaker or LLM-classifier).
- **`story-channels-portfolio-ops`** — Once 3+ channels exist: queue scheduler, dashboards, cross-channel A/B infra, consolidated Postiz UI.
- **`vesper-long-form-v1-1`** — Design and build R9 after Vesper has 14 days of short-form retention data. Covers 16:9 assembly, interstitial card design, YouTube chapter-list emit, long-form chatterbox concat, long-form thumbnail variant.

## Next Steps

→ `/ce:plan` for structured implementation planning.
