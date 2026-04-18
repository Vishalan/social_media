---
title: Engagement Layer v2 — Shared-File Conflict Register
status: active
date: 2026-04-18
execution_plan: docs/plans/2026-04-18-002-feat-engage-v2-agent-team-execution-plan.md
stream_manifest: docs/plans/2026-04-18-002-engage-v2-stream-manifest.yaml
---

# Shared-File Conflict Register

Files touched by more than one origin-plan unit, the order in which those units must land on `feat/engagement-layer-v2`, and the file region each unit owns. Workers must not touch regions outside their assigned scope. Spec reviewer enforces this.

**Rule of thumb:** two workers never hold uncommitted writes to the same file region at the same time. Serialization is by merge order; concurrency is by region disjointness.

**Rebasing rule:** before merge, every worker rebases onto the current `feat/engagement-layer-v2` tip and re-runs verification. Downstream workers on a shared file rebase after each upstream merge; region-scoped edits apply cleanly because they do not overlap.

## Quick conflict matrix

| File | Units | Order |
|---|---|---|
| `sidecar/Dockerfile` | 0.1 → 0.2 | Serial |
| `sidecar/requirements.txt` | 0.4 | Single writer |
| `requirements.txt` | 0.4 | Single writer |
| `scripts/commoncreed_pipeline.py` | 0.4 → 0.5 → A3 | Serial; non-overlapping blocks |
| `scripts/smoke_e2e.py` | 0.4 → 0.5 → A3 | Serial; mirror of pipeline.py |
| `scripts/broll_gen/selector.py` | 0.5 → C2 | Serial; different regions |
| `scripts/broll_gen/factory.py` | 0.5 → { A1 ∥ B1 ∥ B2 ∥ C2 } | 0.5 first (scaffolds placeholder branches); then per-type in any order (region-disjoint) |
| `scripts/broll_gen/browser_visit.py` | B2 ∥ B3 | Parallel; different functions |
| `scripts/broll_gen/headline_burst.py` | 0.1 → B2 | Serial (B2 rebases onto 0.1's branding migration) |
| `scripts/broll_gen/image_montage.py` | B2 | Single writer |
| `scripts/broll_gen/stats_card.py` | B2 | Single writer |
| `scripts/video_edit/video_editor.py` | A2 → A3 | Serial; different functions |
| `deploy/portainer/docker-compose.yml` | C1 | Single writer (0.3 is read-only verify) |
| `scripts/news_sourcer.py` (topic-selection Haiku) | B1 ∥ B2 | Parallel; different JSON-schema fields |
| `.gitignore` | Execution-plan Unit 1 only | Single writer |

## Detailed per-file rules

### `sidecar/Dockerfile`

- **Units:** 0.1, 0.2.
- **Order:** 0.1 → 0.2.
- **0.1 region:** add a `COPY assets/fonts/ /usr/local/share/fonts/commoncreed/` + `RUN fc-cache -f -v && fc-list | grep -qi "Inter"` block near the existing font/apt install section; add `fonts-noto-color-emoji` to the apt install line.
- **0.2 region:** append a `RUN ffmpeg -filters 2>&1 | grep -qE "^ . ass "` libass-check block **immediately after** the line that installs `ffmpeg` via apt.
- **Conflict resolution:** 0.2 rebases after 0.1 lands; because 0.2's block lives below 0.1's additions, no merge conflict is expected. If one occurs, 0.2 accepts 0.1's block verbatim and re-appends the libass check below.

### `sidecar/requirements.txt` / `requirements.txt` (repo root)

- **Unit:** 0.4 only.
- **Region:** append `trafilatura>=1.6.0`.
- **Rule:** repo root mirrors sidecar; both get the same line in the same relative position. No other unit edits these files; downstream units treat them as read-only.

### `scripts/commoncreed_pipeline.py`

- **Units:** 0.4, 0.5, A3.
- **Order:** 0.4 → 0.5 → A3.
- **0.4 region:** inside `_run_topic` (near line 446 per origin plan), after the topic URL is resolved, insert the `extract_article_text(topic_url)` call and stash on `topic["extracted_article"]`.
- **0.5 region:** `VideoJob` dataclass at line 78 — add four new optional fields (`extracted_article`, `tweet_quote`, `split_screen_pair`, `keyword_punches`). Plus `cpu_types` / `gpu_types` registry imports from the new `registry.py`.
- **A3 region:** insert `extract_keyword_punches(...)` step between the existing transcribe and assemble steps in `_finalize_job` (line ~446 area); pass `keyword_punches` + `sfx_events` to `editor.assemble`.
- **Non-overlap proof:** 0.4 writes inside `_run_topic`; 0.5 writes inside the `VideoJob` dataclass at line 78 + new imports at the top; A3 writes inside `_finalize_job`. Three distinct functions; no line overlap.
- **Rebasing:** 0.5 rebases onto 0.4; A3 rebases onto 0.5.

### `scripts/smoke_e2e.py`

- **Units:** 0.4, 0.5, A3.
- **Order:** 0.4 → 0.5 → A3 (same order as `commoncreed_pipeline.py`).
- **Regions:** mirror of `commoncreed_pipeline.py` — 0.4 edits `step_topic`; 0.5 edits module-level registry imports + the synthetic-job construction; A3 inserts keyword-punch step between `transcribe` (step 6) and `step_assemble` (step 7).
- **Stdout contract:** the final `print(...)` block consumed by `sidecar/pipeline_runner.py` is **additive only**. Units append new keys; no unit removes or restructures existing keys. Spec reviewer diff-checks this.

### `scripts/broll_gen/selector.py`

- **Units:** 0.5, C2.
- **Order:** 0.5 → C2.
- **0.5 region:** `_VALID_TYPES` frozenset (add four new types), `_RESPONSE_SCHEMA["properties"]["primary"]["enum"]` + `["fallback"]["enum"]` (mirror), `_SYSTEM_PROMPT` (append one-line descriptions), and the short-circuit logic at lines 104–108 (replace hard-coded `["browser_visit", "headline_burst"]` with the conditional `forced_primary_candidates` block).
- **C2 region:** gating logic only — add a numeric-density preference: when `chart_spec is not None`, prefer `cinematic_chart` primary with `stats_card` fallback. Does **not** edit `_VALID_TYPES`, `_RESPONSE_SCHEMA`, or `_SYSTEM_PROMPT` (those already have `cinematic_chart` registered by 0.5).
- **Rebasing:** C2 rebases onto 0.5; their edits live in different blocks.

### `scripts/broll_gen/factory.py`

- **Units:** 0.5, A1, B1, B2, C2.
- **Order:** 0.5 first; A1/B1/B2/C2 in any order after 0.5 merges.
- **0.5 region:** add four placeholder branches to the `if type_name == "..."` chain in `make_broll_generator` — each placeholder raises `NotImplementedError("phone_highlight not yet wired")` etc. This keeps the registration linter (Unit 0.6) green immediately after 0.5 lands.
- **A1 region:** replace the `phone_highlight` placeholder branch only.
- **B1 region:** replace the `tweet_reveal` placeholder branch only.
- **B2 region:** replace the `split_screen` placeholder branch only.
- **C2 region:** replace the `cinematic_chart` placeholder branch only.
- **Non-overlap proof:** each Wave-2 unit edits exactly one `if type_name == "<its type>"` block; the four blocks are textually disjoint and Git resolves them independently.
- **Rebasing:** when a Wave-2 unit prepares for merge, it rebases onto the latest integration branch. If another Wave-2 unit has landed a different branch, the diff is textually disjoint and rebase applies cleanly.

### `scripts/broll_gen/browser_visit.py`

- **Units:** B2, B3.
- **Order:** parallel-safe (different functions).
- **B2 region:** `__init__` / `generate` signature — add `width_override: int | None = None` param; plumb through `_VIEWPORT_W` usage.
- **B3 region:** `_TIMELINE_SYSTEM_PROMPT` (lines ~245) + `_plan_timeline` (compaction retry logic).
- **Non-overlap proof:** `__init__`/`generate` vs prompt-module + `_plan_timeline`. Distinct symbols; no overlap. Either order of merge is acceptable; late one rebases.

### `scripts/broll_gen/headline_burst.py`

- **Units:** 0.1, B2.
- **Order:** 0.1 → B2.
- **0.1 region:** replace per-file `_BOLD_CANDIDATES = [...]` constant with `find_font("bold")` import from `scripts/branding.py`; replace per-file color literals with brand constants.
- **B2 region:** add `width_override` param, parameterize the `1080` viewport/canvas literal.
- **Conflict risk:** both edit the file's top-level constants. Resolution: B2 rebases onto 0.1's constant-migration, then adds `width_override` to the generator's constructor (separate spot).

### `scripts/broll_gen/image_montage.py` / `scripts/broll_gen/stats_card.py`

- **Unit:** B2 only.
- **Region:** add `width_override` param; parameterize `1080` canvas literal. `stats_card` may need font auto-scaling at 540px (origin-plan flag — worker decides at implementation time).
- **Rule:** single writer; no conflict possible.

### `scripts/video_edit/video_editor.py`

- **Units:** A2, A3.
- **Order:** A2 → A3.
- **A2 region:** replaces `_build_ass_captions` wholesale (per-word `Dialogue:` lines with karaoke timing). Style block updated to `Inter` font. Adds word-drift guard.
- **A3 region:** replaces the `_write_with_captions` call site inside `_assemble_broll_body` with a new `_apply_engagement_pass` helper (single combined FFmpeg final-pass: zoompan + ass + sfx amix).
- **Non-overlap proof:** A2 edits `_build_ass_captions` function body; A3 edits `_assemble_broll_body` and adds a new `_apply_engagement_pass` function. Distinct functions. A2's output (ASS file) becomes A3's input (as `{ass_path}` in the filter graph).
- **Rebasing:** A3 rebases onto A2's merge; A3's `_apply_engagement_pass` takes the `ass_path` produced by A2's `_build_ass_captions` as an argument, so the contract is clean.

### `deploy/portainer/docker-compose.yml`

- **Units:** 0.3 (verify-only), C1 (add `commoncreed_remotion` service).
- **Order:** single writer (C1). 0.3 merely verifies the `assets/` mount is already present; no edit expected. If 0.3's verification reveals a missing mount, it's a separate one-line addition and lands under 0.3's branch before C1.

### `scripts/news_sourcer.py` (or the topic-selection Haiku owner)

- **Units:** B1, B2.
- **Order:** parallel-safe (different JSON-schema fields).
- **B1 region:** extend the Haiku prompt + structured response schema with `tweet_quote: {author, handle, body, like_count_estimate, verified} | null`.
- **B2 region:** extend the same prompt + schema with `split_screen_pair: {left: {...}, right: {...}} | null`.
- **Conflict risk:** both edits likely appear in the same "additional fields" block of the prompt string and the JSON schema. Resolution: whichever lands first owns the structural scaffolding (the `if this topic has...` stanzas); the second rebases and appends its stanza below.
- **Rule:** both workers add their field as a **new top-level optional key** — neither replaces or restructures existing keys.

### `.gitignore`

- **Unit:** execution-plan Unit 1 only.
- **Region:** append `.worktrees/` under a new header.
- **Rule:** no origin-plan unit touches `.gitignore`.

## Enforcement

- **Spec reviewer** — on worker DONE, the spec reviewer diff-checks `touched_files` against this register. A diff that edits a file region outside the unit's assigned scope is returned to the implementer as a spec gap.
- **Orchestrator** — before invoking merge, orchestrator runs `git diff <integration-branch>..<unit-branch> -- <shared-file>` for each shared file and confirms the diff lives in the unit's declared region (by checking the line ranges / affected functions against this register).
- **Merge-time** — if a rebase produces an actual conflict, the orchestrator does **not** auto-resolve. The worker is re-dispatched with the conflict context; the worker decides whether its region truly overlaps (spec gap) or whether the conflict marker can be resolved without scope creep.

## Amending this register

This register is authoritative for the run. If an origin-plan amendment introduces a new shared-file edit, update this register in the same commit and bump the `date` in frontmatter. The stream-manifest `shared_files` entries must stay consistent with this document.
