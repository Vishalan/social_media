---
title: "Parallel Agent-Team Execution for Large Feature Plans"
date: 2026-04-19
category: workflow-issues
module: meta
problem_type: workflow_issue
component: tooling
symptoms:
  - "Single-agent execution of 11-unit plans exhausts context before completion"
  - "Sequential unit execution wastes wall-clock when units are independent"
  - "Agent sandbox restrictions silently break git/network/curl operations mid-flight"
  - "Worker agents write to main tree instead of assigned worktree"
  - ".gitignore rules silently swallow curated binary assets (SFX wavs)"
  - "pytest discovery is order-dependent without explicit pythonpath"
  - "Docker regex assertions are brittle across tool version upgrades"
root_cause: coordination_pattern
resolution_type: process_improvement
severity: high
related_components:
  - development_workflow
  - background_job
  - tooling
tags:
  - agent-teams
  - parallel-execution
  - git-worktree
  - sandbox-limits
  - compound-engineering
  - claude-code
---

# Parallel Agent-Team Execution for Large Feature Plans

## Problem

The Engagement Layer v2 plan (`docs/plans/2026-04-18-001-feat-engagement-layer-v2-plan.md`) contained **11 implementation units** with a mix of sequential dependencies and independent work streams. Executing it inline in a single agent conversation would:

1. Exhaust context long before reaching the last unit (each unit involves ~3-8 files + tests + verification)
2. Serialize units that could run in parallel (e.g., the 3 scaffolding units in Wave 0 had no dependencies on each other)
3. Offer no recovery path if a single unit failed mid-way — the entire conversation had to be re-primed

We needed a coordination pattern that could ship **11 units across 14 git branches in a single session** while keeping the parent context clean.

## Symptoms Observed During Execution

- One worker agent committed files to the main working tree instead of its assigned worktree — silent until `git status` revealed it post-run
- Worker agents consistently hit sandbox blocks on `git commit` (network resolution), `curl`, and `npm install` — but the sandbox error was not always loud
- Rate limits hit twice mid-run; had to pause and re-dispatch after reset
- One agent's `gitStatus` was stale (from the system-prompt snapshot) — agent refused to deploy because it thought the working tree was dirty
- `.gitignore`'s blanket `*.wav` rule silently excluded 15 synthesized SFX files from Unit 0.3
- pytest rootdir varied based on positional-arg order, causing "test not found" errors that only happened in CI
- Dockerfile `grep -qE "^ . ass "` assertion broke on ffmpeg 7.x which prints ` ... ass ` (3-dot prefix) — invisible until the Docker build failed

## Root Cause

Large-plan execution requires **both** parallelization (wall-clock wins) and **coordination rigor** (to prevent silent drift across workers). The pitfalls above are structural, not accidental:

- **Sandbox boundaries differ between parent and children.** The parent session may have `dangerouslyDisableSandbox` active; spawned agents do not. Commands that work in parent must be validated before delegating.
- **Worktrees are not enforced by the sandbox.** An agent instructed to `cd .worktrees/unit-X` can still absent-mindedly write to the parent tree. There is no filesystem boundary.
- **System-prompt `gitStatus` is a snapshot.** It is NOT refreshed during the conversation. Agents that rely on it instead of running `git status` fresh act on stale state.
- **`.gitignore` precedence over `git add`.** Without a `!` whitelist rule, binary assets like curated audio files are invisible to the add command. You need `git add -f` or a whitelist.
- **Tool-version drift in regex assertions.** Assertions that pattern-match on ffmpeg or other upstream tool output will break silently on minor-version upgrades.

## Resolution — Coordination Pattern

### 1. Plan-per-unit worktrees on pre-created branches

Parent session pre-creates all worktrees and branches before dispatching any agents:

```bash
for unit in A1 A2 B1 B2 C1 C2 D1 D2 D3 E1 E2; do
  git worktree add -b "feat/engage-v2-$unit" ".worktrees/engage-v2-$unit"
done
```

Each agent is then given: absolute worktree path, branch name, and the instruction "**all edits happen under this path; verify with `pwd && git branch --show-current` before starting**."

### 2. Parent session owns git operations

Agents are told explicitly: **do not attempt `git commit` or `git push`**. They write files and report back. The parent session runs `git status` in each worktree, verifies what changed, stages, commits with a proper message, and pushes. This works around the sandbox restriction on git in child contexts.

### 3. Dispatch topology matches the plan's dependency graph

Wave 0 (scaffolding, 3 units) dispatched in parallel. Wave A (avatar + stitching, 2 units) dispatched after Wave 0 completes. Wave B (post-production, 2 units) after A. Each wave is a single message with N parallel Agent tool calls.

### 4. Two-stage review with truncated agent context

Stage 1: agent summary shows what they claim to have done. Stage 2: parent reads the actual diff with `git diff --stat` + spot-checks key files. The two rarely match perfectly. Never trust the summary.

### 5. Sandbox escape for deploy-time operations only

`dangerouslyDisableSandbox: true` is used ONLY for:
- SSH + docker build on the remote production server
- Running the Portainer update script which must hit a self-signed HTTPS API

Never used during agent authoring work — we want those to stay in the sandbox so they can't accidentally touch production.

### 6. Retrospective fixes applied this session

- `scripts/pytest.ini`: added `pythonpath = .` so test discovery is deterministic regardless of invocation directory
- `.gitignore`: added `!assets/sfx/*.wav` whitelist so curated SFX survive the blanket `*.wav` rule
- `sidecar/Dockerfile`: libass assertion changed from `grep -qE "^ . ass "` → `grep -qw ass` (version-agnostic word match)
- `.claude/skills/cc-deploy-portainer/cc_update_stack.py`: `regen_prod_compose()` regex generalized from a sidecar-specific pattern to a loop over ALL service `build:` blocks, because Portainer's sandboxed runner can't see any build contexts on the host

## What Worked

- **Parent-as-coordinator, agent-as-worker split.** Zero silent commits to main, zero lost work across 14 branches.
- **Pre-creating worktrees.** Made the work deterministic — every agent knew exactly where to write.
- **Small unit size (~1-3 files + tests).** Kept agent context clean and verification cheap.
- **Explicit "do not commit" instruction in every agent prompt.** Eliminates the sandbox-blocks-git failure mode by not attempting it.
- **Plan checkbox discipline.** Each finished unit → plan checkbox flipped → next wave dispatched only after.
- **Keychain-backed credential handling.** `security find-generic-password` is faster and safer than .env parsing for one-shot scripts.

## What Broke

1. **One agent wrote files to main tree (A1).** Recovered via `cp` to worktree + `git restore` on main tree. Root cause: agent's shell cwd drifted during a multi-step edit. Mitigation: instruct agents to re-run `pwd` between edits.
2. **Two rate-limit hits.** Not preventable in-session; resumed after reset with no data loss because worktrees persist.
3. **`.gitignore` swallowed 15 SFX files silently.** Fix: whitelist + `git add -f`. Lesson: binary assets always need explicit whitelists, not blanket ignores.
4. **Dockerfile regex broke on ffmpeg 7.x.** 3 iterations to fix. Lesson: never pattern-match a leading space or dot count; use word-boundary.
5. **Deploy agent refused on stale gitStatus.** Re-dispatched with explicit "run `git status` fresh, do NOT use the snapshot" instruction.
6. **Remotion unit shipped scaffolding but commented out the compose service** because `npm install` was blocked in sandbox. Tracked as a follow-up — finished next session via parent-side `npm install` + manual uncomment + regen_prod_compose regex generalization.

## What to Change Next Time

- **Pre-flight compose-context sanity check.** Before any wave dispatches, parent should `docker compose config` the prod compose to catch build-context errors before the agent wave runs. (Unit C1 would have caught the remotion issue here.)
- **Agent prompts must mandate `git status` verification.** Not system-prompt snapshot. Put it as the first instruction.
- **Agent prompts must require `pwd` after every `cd`.** Cheap insurance against cwd drift.
- **Version-agnostic assertions in Dockerfiles.** No `grep -qE "^ X ..."` patterns. Use `grep -qw` or grep with a stable substring.
- **Parent should run a pre-wave "write-only" test.** Dispatch one trivial unit first to confirm the worktree path routing works end-to-end before committing to parallel dispatch of N units.
- **Binary-asset whitelists pre-declared.** When a plan mentions generating audio, video, or image assets, add the `.gitignore` whitelist BEFORE the unit runs.
- **Capture the deploy-time skill regex expectations in the skill's own tests.** The `cc_update_stack.py` regex broke twice — once when engage-v2 added a second build service, and again when remotion was re-enabled. A snapshot test of `regen_prod_compose()` output would have caught both.

## Related

- `docs/plans/2026-04-18-002-feat-engage-v2-agent-team-execution-plan.md` — the execution-topology plan this retrospective is about
- `docs/plans/2026-04-19-001-chore-post-engage-v2-consolidation-plan.md` — the consolidation plan that includes this retrospective as Track 4
- `.claude/skills/cc-deploy-portainer/cc_update_stack.py` — the deploy-time script that needed two fixes
- `docs/solutions/integration-issues/server-migration-synology-to-ubuntu-2026-04-11.md` — context on the production target this deployed to
