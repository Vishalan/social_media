---
title: "chore: Post-engage-v2 consolidation — close-out + in-flight triage + feature-plan queue"
type: chore
status: active
date: 2026-04-19
origin: (no brainstorm — operational consolidation from session work)
---

# Post-engage-v2 Consolidation Plan

## Context

Engagement Layer v2 shipped to production on 2026-04-19 (commit `8a7e7ea`). Sidecar rebuilt with 11 new origin-plan units live. The immediate next job is **not another feature** — it's closing out engage-v2 fully, cleaning up the 44 uncommitted files from before the run started, triaging the 6 other pending feature plans, and capturing compounding learnings so the next run is cheaper.

## Goals

1. **Close engage-v2** — wrap Remotion (Unit C1) so cinematic_chart is actually usable; validate canary path is ready; capture learnings.
2. **Triage the 44 in-flight files** — partial work for 5 separate features has been sitting in the working tree since before engage-v2 started. Split into topic branches so each feature can be picked up independently.
3. **Queue the remaining feature plans** — 6 plans exist (server-migration, local-llm, meme-sources, wan22-avatar, meme-quality, youtube-shorts). Rank by readiness. Dispatch the top one for parallel agent-team execution.
4. **Compound learnings** — one solutions doc on the engage-v2 agent-team pattern (what worked, what broke, what to change next time).

## Scope Boundaries

- **Not executing all 6 feature plans in this session.** Engage-v2 took a full session for 11 units. Six more = six more sessions. We QUEUE + DISPATCH ONE.
- **Not building revenue dashboards.** That's a new feature, needs its own brainstorm.
- **Not running live canary shorts.** Requires real API keys + monitoring infrastructure; queued for your session 1:1 with the pipeline.

## Tracks (execute in order)

- [x] **Track 1 — Server migration close-out** (already effectively done; just status flip + archive)
- [x] **Track 2 — In-flight triage → 5 topic branches on origin**
- [x] **Track 3 — Remotion wrap-up** (`npm install` → lockfile → uncomment → redeploy) — shipped commit `e18cf99`; internal `/healthz` returns `{"ok":true}`
- [x] **Track 4 — Compound retrospective** (`docs/solutions/workflow-issues/agent-team-parallel-execution-2026-04-19.md`)
- [x] **Track 5 — Feature-plan readiness matrix** (see table in Track 5 section below)
- [x] **Track 6 — Dispatch top-priority plan** (meme-quality-overhaul — plan 2026-04-16-001) — merged to main (commit `4953a9b`); plan frontmatter flipped to `completed`

## Track details

### Track 1 — Server migration close-out

`docs/plans/2026-04-11-001-refactor-server-migration-plan.md` is `status: active` but production has been on Ubuntu 192.168.29.237 for at least 36 hours (confirmed via docker ps). The stack is live. Whatever migration work was in that plan is de facto complete.

**Action:** flip frontmatter `status: active → completed`, add `completed_at` + evidence of live production. No code work.

### Track 2 — In-flight triage

44 uncommitted files cluster into 5 topic branches based on which pending plan they belong to:

| Branch | Origin plan | In-flight files (approx) |
|--------|-------------|-------------------------|
| `wip/local-llm-inference` | 2026-04-12-001 | `sidecar/llm_client.py` (171 lines) + topic_selector + llm-related sidecar changes |
| `wip/meme-sources-expansion` | 2026-04-13-001 | `sidecar/meme_sources/mastodon_memes.py` (165) + reddit_memes modifications + meme_sources/__init__.py |
| `wip/wan22-avatar-provider` | 2026-04-15-001 | `scripts/avatar_gen/wan22_s2v_client.py` (105) + factory modifications + 4 comfyui_workflows/wan*.json |
| `wip/chatterbox-voice` | (solution doc 2026-04-18) | `scripts/voiceover/chatterbox_generator.py` (114) + voiceover/__init__.py |
| `wip/youtube-shorts-source` | 2026-04-16-002 | `sidecar/meme_sources/youtube_shorts.py` (193) |
| `wip/sidecar-hardening` | (operational, spans plans) | `sidecar/app.py`, `config.py`, `db.py`, `jobs/*`, `meme_pipeline.py`, `postiz_client.py`, `requirements.txt` + brainstorm/plan docs |

**Action:** for each track, create a branch off `main`, stage only the files belonging to that track, commit with a clear "wip:" message, push. Leave branches on origin for future per-plan PRs.

**Risks:**
- File ownership may overlap (e.g. `sidecar/meme_pipeline.py` may serve both meme-sources expansion AND meme-quality overhaul). When ambiguous, commit to the most-specific branch and note overlap in the commit message.
- `sidecar/requirements.txt` is shared — commit it with the most-dependent branch, cherry-pick if others need it later.

### Track 3 — Remotion wrap-up

Unit C1 shipped code + compose service but the service block is commented out because `deploy/remotion/package-lock.json` was never generated (scaffolding agent's sandbox blocked `npm install`).

**Action:**
1. `cd deploy/remotion && npm install` (generates `package-lock.json` — needs network, runs on macOS dev)
2. Commit the lockfile + uncomment the service block in compose
3. Push to main
4. SSH + `docker build` the Remotion image on the Ubuntu server
5. `python3 .claude/skills/cc-deploy-portainer/cc_update_stack.py` to pick up the uncommented service
6. Verify `curl http://192.168.29.237:3030/healthz` returns `{"ok":true}`
7. Optionally flip `CINEMATIC_CHART_ENABLED=true` in `.env` to unblock Unit C2

### Track 4 — Compound retrospective

Write `docs/solutions/workflow-issues/agent-team-parallel-execution-2026-04-19.md` capturing:
- What worked: worktree-per-unit, conflict register, two-stage review discipline (in practice: truncated to spec + light code review via parent).
- What broke: agent sandbox blocks on git + network + curl (mitigated by parent committing on agents' behalf, parent using `dangerouslyDisableSandbox`); one agent wrote files to main tree instead of worktree (recovery: cp + restore); rate-limit hits (2 retries); pytest rootdir depending on positional-arg order (fixed via pytest.ini pythonpath); `.gitignore` silently swallowed 15 SFX WAV files (fixed via whitelist); Dockerfile libass regex was format-brittle (fixed in prod).
- What to change: pre-flight compose-context sanity check; skill's `regen_prod_compose` regex needs to handle commented sections + inline comments in `build:` block; agent prompts should explicitly mandate `git status` verification (not system-prompt snapshot).

### Track 5 — Feature-plan readiness matrix

For each of the 6 remaining plans, rank on three axes:

| Plan | Code ready? | External deps? | Prod-impact? | Priority |
|------|------------|----------------|--------------|----------|
| server-migration | ✅ (done in prod) | none | zero (already live) | CLOSE |
| meme-quality-overhaul | partial | none | HIGH (fixes real quality issue) | **1st** |
| meme-sources-expansion | partial | Mastodon API | medium | 2nd |
| youtube-shorts-source | partial | YouTube API OAuth already configured | medium | 3rd |
| local-llm-inference | partial | Ollama + Qwen 3 model download on RTX 2070 | low (perf gain, not feature) | 4th |
| wan22-avatar-provider | partial | `blocked-upstream` per plan frontmatter | high (quality) | queued |

### Track 6 — Dispatch top-priority plan

**Pick `meme-quality-overhaul` (fix)** as the first follow-up execution because:
- It's a `type: fix` — already-identified real bug (low-quality meme surfacing)
- Small scope (scoring threshold + dedup window + surface limits)
- No new external dependencies
- Partial code already in-flight
- High prod-impact (directly affects posting quality Tier A cares about)

**Action:** after Track 2 consolidates its partial code to `wip/meme-quality-overhaul` branch, dispatch a plan-runner (similar to engage-v2's pattern but much smaller — this is likely 3-5 units, not 11).

## Success criteria

- [ ] 5 topic branches on origin, each with a coherent first commit
- [ ] Remotion service running healthy in production (`healthz` passes)
- [ ] `docs/solutions/workflow-issues/agent-team-parallel-execution-2026-04-19.md` written + committed
- [ ] server-migration plan marked `completed`
- [ ] Feature-plan matrix captured in this doc + 1st priority plan dispatched for background execution
- [ ] Main working tree clean at session end (or only benign linter touches)

## Explicit non-goals

- Running real canary shorts (user's call, needs live keys)
- Revenue-dashboard brainstorm/plan (separate session)
- Executing plans 2–6 in parallel (each deserves its own engage-v2-scale session)
