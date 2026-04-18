---
title: Engagement Layer v2 — Orchestrator Runbook
status: active
date: 2026-04-18
execution_plan: docs/plans/2026-04-18-002-feat-engage-v2-agent-team-execution-plan.md
stream_manifest: docs/plans/2026-04-18-002-engage-v2-stream-manifest.yaml
conflict_register: docs/plans/2026-04-18-002-engage-v2-conflict-register.md
worker_prompt: docs/plans/2026-04-18-002-engage-v2-worker-prompt.md
spec_reviewer_prompt: docs/plans/2026-04-18-002-engage-v2-spec-reviewer-prompt.md
code_quality_reviewer_prompt: docs/plans/2026-04-18-002-engage-v2-code-quality-reviewer-prompt.md
progress_tracker: docs/plans/2026-04-18-002-engage-v2-progress.md
---

# Orchestrator Runbook

Step-by-step playbook for the leader of the `engage-v2-swarm` team. Executable top-to-bottom by a fresh Claude Code session given only this file and the origin plan. Every step names the exact tool or skill that implements it.

Read `docs/plans/2026-04-18-002-feat-engage-v2-agent-team-execution-plan.md` first for context; this runbook is the execution instrument, not the design.

## 0. Prerequisites (one-time)

- [ ] You are on branch `feat/engagement-layer-v2`. `git branch --show-current` confirms.
- [ ] `.worktrees/` is gitignored. `git check-ignore -v .worktrees/dummy` matches.
- [ ] Progress tracker exists at `docs/plans/2026-04-18-002-engage-v2-progress.md`.
- [ ] All scaffolding units (1–8) of the execution plan are complete.
- [ ] You have `tmux` available (preferred) or will fall back to `in-process` backend.
- [ ] No existing team named `engage-v2-swarm` — if one exists, `Teammate({ operation: "cleanup" })` first.

If any prerequisite fails, stop and resolve before continuing.

## 1. Team bootstrap

### 1.1 Create the team

```javascript
Teammate({
  operation: "spawnTeam",
  team_name: "engage-v2-swarm",
  description: "Parallel execution of engagement-layer-v2 (origin plan 2026-04-18-001). 14 streams across Wave 1 (Tier 0) and Wave 2 (Tier A/B/C)."
})
```

Confirm: `~/.claude/teams/engage-v2-swarm/config.json` exists.

### 1.2 Create task list from the manifest

Read `docs/plans/2026-04-18-002-engage-v2-stream-manifest.yaml`. For each stream, create one task:

```javascript
TaskCreate({
  subject: "Unit <unit_id>: <title>",
  description: "Branch: <branch>. Worktree: <worktree>. Depends on: <depends_on>. Verification tests: <test_paths>.",
  activeForm: "Implementing unit <unit_id>..."
})
```

Then set up dependencies from the manifest's `depends_on` lists:

```javascript
// Wave 1 internal deps
TaskUpdate({ taskId: "<0.2>", addBlockedBy: ["<0.1>"] })
TaskUpdate({ taskId: "<0.5>", addBlockedBy: ["<0.4>"] })
TaskUpdate({ taskId: "<0.6>", addBlockedBy: ["<0.5>"] })

// Wave 2 internal deps
TaskUpdate({ taskId: "<a3>", addBlockedBy: ["<a2>"] })
TaskUpdate({ taskId: "<c2>", addBlockedBy: ["<c1>"] })

// Wave 1 → Wave 2 gate: every Wave-2 task blocked by all Wave-1 tasks
const wave1 = ["<0.1>", "<0.2>", "<0.3>", "<0.4>", "<0.5>", "<0.6>"]
for (const w2 of ["<a1>", "<a2>", "<a3>", "<b1>", "<b2>", "<b3>", "<c1>", "<c2>"]) {
  TaskUpdate({ taskId: w2, addBlockedBy: wave1 })
}

// A1-pattern-dep for B1 (once A1 completes, B1 can rebase and use its patterns)
TaskUpdate({ taskId: "<b1>", addBlockedBy: ["<a1>"] })
```

(Replace `<0.1>`, `<a1>`, etc. with the actual numeric task IDs returned by `TaskCreate`.)

Confirm: `TaskList()` shows all 14 tasks with correct `blockedBy` relationships.

## 2. Wave 1 dispatch

Wave 1 = Tier 0. Three tasks start unblocked: 0.1, 0.3, 0.4. Dispatch them in parallel — **all three `Task` calls in a single message** per `superpowers:dispatching-parallel-agents`.

### 2.1 Prepare worktrees

For each unblocked task, the orchestrator creates the worktree **before** dispatching the worker. The worker's prompt assumes the worktree exists and is on the correct branch.

Create worktree for unit 0.1 (and 0.3, 0.4 in parallel — all three commands batched):

```bash
git worktree add .worktrees/engage-v2-0.1 -b feat/engage-v2/0.1-brand-assets feat/engagement-layer-v2
git worktree add .worktrees/engage-v2-0.3 -b feat/engage-v2/0.3-sfx-library   feat/engagement-layer-v2
git worktree add .worktrees/engage-v2-0.4 -b feat/engage-v2/0.4-article-extractor feat/engagement-layer-v2
```

For each worktree, per `superpowers:using-git-worktrees`, verify a clean test baseline:

```bash
cd .worktrees/engage-v2-0.1 && python3 -m pytest scripts/ -q --collect-only 2>&1 | tail -5
```

If the baseline doesn't pass, report and resolve before dispatching.

### 2.2 Render worker prompts

For each of 0.1, 0.3, 0.4, render the template from `docs/plans/2026-04-18-002-engage-v2-worker-prompt.md` with the manifest entry's values. Verify every `{...}` placeholder is filled (grep the rendered prompt for `{` — should find none from the template's variable names).

### 2.3 Dispatch workers in parallel

Send all three in a single message:

```javascript
Task({
  team_name: "engage-v2-swarm",
  name: "0.1",
  subagent_type: "general-purpose",
  prompt: <rendered worker prompt for 0.1>,
  run_in_background: true
})

Task({
  team_name: "engage-v2-swarm",
  name: "0.3",
  subagent_type: "general-purpose",
  prompt: <rendered worker prompt for 0.3>,
  run_in_background: true
})

Task({
  team_name: "engage-v2-swarm",
  name: "0.4",
  subagent_type: "general-purpose",
  prompt: <rendered worker prompt for 0.4>,
  run_in_background: true
})
```

Mark the three team tasks `in_progress` with owners:

```javascript
TaskUpdate({ taskId: "<0.1>", status: "in_progress", owner: "0.1" })
// Same for 0.3 and 0.4.
```

Update the progress tracker: set each of these rows' `Owner` to the subagent name and `Status` to `in_progress`.

## 3. Per-unit merge protocol (used by Wave 1 AND Wave 2)

Wait for each worker to return a structured report (see worker-prompt.md). When a worker reports, run this protocol:

### 3.1 Handle non-DONE statuses first

- **DONE_WITH_CONCERNS** — read concerns. If correctness/scope, re-dispatch with clarification; otherwise proceed to 3.2 and record the concern in the progress tracker's run log.
- **NEEDS_CONTEXT** — provide the missing context and re-dispatch the same subagent. Do not change the model.
- **BLOCKED** — assess:
  - Context gap → provide more context, re-dispatch.
  - Reasoning gap → re-dispatch with a more capable model (swap `general-purpose` for `subagent_type: "general-purpose"` with `model: "opus"` if not already).
  - Plan wrong → escalate to human; do not guess.
  - Task too large → escalate (origin-plan units are already sized; this is rare).
- **No response in 5 minutes** — per `orchestrating-swarms`, heartbeat timeout. Check `~/.claude/teams/engage-v2-swarm/inboxes/team-lead.json` for idle notifications. If the teammate is truly inactive, reclaim the task:
  ```javascript
  TaskUpdate({ taskId: "<unit_id>", owner: null, status: "pending" })
  ```
  Then re-dispatch a fresh worker with the same prompt.

### 3.2 Stage 1: Spec review

Render `docs/plans/2026-04-18-002-engage-v2-spec-reviewer-prompt.md` with the worker's report + commit SHA.

```javascript
Task({
  team_name: "engage-v2-swarm",
  name: "spec-reviewer-<unit_id>",
  subagent_type: "compound-engineering:review:pattern-recognition-specialist",
  prompt: <rendered spec reviewer prompt>,
  run_in_background: false
})
```

- If **PASS** → proceed to 3.3.
- If **FAIL** → re-dispatch the original worker with the GAPS list appended. Worker fixes + re-commits. Return to 3.2 (re-run spec review against new HEAD).

Never skip the re-review.

### 3.3 Stage 2: Code-quality review

Render `docs/plans/2026-04-18-002-engage-v2-code-quality-reviewer-prompt.md`. The `subagent_type` comes from the manifest's `code_quality_reviewer` field for this unit.

```javascript
Task({
  team_name: "engage-v2-swarm",
  name: "code-quality-reviewer-<unit_id>",
  subagent_type: <manifest.code_quality_reviewer for this unit>,
  prompt: <rendered code-quality reviewer prompt>,
  run_in_background: false
})
```

- If **APPROVE** → proceed to 3.4.
- If **REQUEST CHANGES** with Critical findings → re-dispatch worker with Critical list. Return to 3.3 (re-run code-quality review). Critical findings always block merge.
- If **REQUEST CHANGES** with only Important findings → orchestrator decides case-by-case whether to block or defer; default: block unless the finding is orthogonal to the unit's stated scope.
- Nits are non-blocking; record in progress tracker and proceed.

### 3.4 Rebase and merge into integration

In the worker's worktree:

```bash
cd .worktrees/engage-v2-<unit_id>
git fetch origin                       # no-op if no remote; safe
git rebase feat/engagement-layer-v2    # pick up any merges that landed since this worker started
```

If rebase raises conflicts:

- If the conflict is inside the unit's declared shared-file region → the worker made a legitimate edit; auto-accept its side only after spec reviewer re-confirms scope.
- If the conflict is outside the declared region → the unit has scope creep; return to Stage 1 with "region-scoped edit violation" as the gap.
- Do not auto-resolve conflicts without a round-trip through the worker.

After a clean rebase, re-run the unit's verification tests + the project regression slice:

```bash
cd .worktrees/engage-v2-<unit_id>
python3 -m pytest <unit test paths> -q
python3 -m pytest scripts/thumbnail_gen/tests/ scripts/video_edit/tests/ scripts/posting/tests/ -q
```

Both must pass. If regression tests fail after rebase, the worker's diff has an integration issue with work that landed since dispatch — escalate or re-dispatch with the regression context.

On green, merge:

```bash
cd /Users/vishalan/Documents/Projects/social_media    # main working tree
git checkout feat/engagement-layer-v2
git merge --ff-only feat/engage-v2/<unit_id>-<slug>
```

If fast-forward fails, the integration branch has advanced — repeat the rebase step in the worker's worktree, then retry.

### 3.5 Update progress tracker and team task

```markdown
| <unit row> | <branch> | <worktree> | <deps> | <owner> | ✅ merged | <YYYY-MM-DD HH:MM> |
```

```javascript
TaskUpdate({ taskId: "<unit_id>", status: "completed" })
```

Any task now unblocked auto-transitions to `pending` and becomes eligible for dispatch. Check `TaskList()` to see what just unblocked.

### 3.6 Per-branch cleanup (optional; defer to rollup)

Workers stay around in their worktrees until rollup, in case rebase + re-dispatch is needed. Do not remove worktrees mid-run.

Follow `superpowers:finishing-a-development-branch` conceptually (final review summary) but defer the branch deletion step until Phase 5 cleanup.

## 4. Wave 1 → Wave 2 gate

When all six Wave-1 tasks are `completed`, run the Gate 1 checklist from `docs/plans/2026-04-18-002-engage-v2-integration-gates.md`.

For each check, run the command or observation and record the result in the progress tracker's Gate 1 table.

- **All green** → proceed to Phase 5 (Wave 2 dispatch).
- **Any red** → do not dispatch Wave 2. Escalate to human. The failed check points at either a bug introduced by Tier 0 or a flaky regression; resolve before unlocking downstream work.

## 5. Wave 2 dispatch

After Gate 1 is green, the Wave-2 tasks auto-unblock (they had `addBlockedBy` on all Wave-1 tasks). At this point, the following become immediately dispatch-eligible:

- **A1** (depends on 0.1, 0.4, 0.5 — all complete)
- **A2** (depends on 0.1, 0.2 — all complete)
- **B2** (depends on 0.5 — complete)
- **B3** (no deps — complete)
- **C1** (no deps — complete)

Still blocked:

- **A3** — blocked by A2
- **B1** — blocked by A1 (pattern dep)
- **C2** — blocked by C1

Dispatch the five unblocked units in parallel — **all five `Task` calls in one message**. Follow the same pattern as Wave 1 (Steps 2.1–2.3). Worktree paths and branches come from the manifest.

As each Wave-2 unit completes via the merge protocol (Phase 3), A3/B1/C2 auto-unblock in order and are dispatched individually (or together if multiple unblock at once — still parallel-dispatchable).

### 5.1 Pattern-dep rebase for B1

When A1 completes, the orchestrator notifies (or the worker, if it has started, rebases). Because B1 is a pattern dep rather than a code dep, B1's Approach references A1's Playwright + concat structure; the worker should re-read A1's merged code once it's available.

## 6. Gate 2 (post-Wave-2)

After all eight Wave-2 tasks are `completed`, run the Gate 2 checklist.

- **All green** → proceed to Phase 7 (rollup).
- **Any red** → escalate; defer rollup until resolved.

## 7. Rollup

See `docs/plans/2026-04-18-002-engage-v2-rollout-runbook.md` for the full rollup sequence. Summary:

1. Confirm Gate 3 (all 14 rows merged, linear history, CHANGELOG drafted).
2. Push `feat/engagement-layer-v2` to origin.
3. Use `compound-engineering:git-commit-push-pr` to open the PR against `main`. PR body links:
   - Origin plan: `docs/plans/2026-04-18-001-feat-engagement-layer-v2-plan.md`
   - This execution plan: `docs/plans/2026-04-18-002-feat-engage-v2-agent-team-execution-plan.md`
   - Stream manifest: `docs/plans/2026-04-18-002-engage-v2-stream-manifest.yaml`
   - Progress tracker: `docs/plans/2026-04-18-002-engage-v2-progress.md`
   - Gate 1/2/3 evidence (link to commits or test logs)
4. Wait for human review. Do not auto-merge.

## 8. Cleanup

After human merges the rollup PR to `main`:

```bash
# Remove per-unit worktrees
for id in 0.1 0.2 0.3 0.4 0.5 0.6 a1 a2 a3 b1 b2 b3 c1 c2; do
  git worktree remove .worktrees/engage-v2-$id
done

# Prune merged branches
compound-engineering:git-clean-gone-branches

# Tear down team
for name in 0.1 0.2 0.3 0.4 0.5 0.6 a1 a2 a3 b1 b2 b3 c1 c2; do
  Teammate({ operation: "requestShutdown", target_agent_id: "$name" })
  # wait for shutdown_approved message in team-lead.json
done
Teammate({ operation: "cleanup" })

# Archive progress tracker
# Edit frontmatter: status: active → status: archived
```

## Monitoring during the run

- **Task graph**: `TaskList()` — shows pending / in_progress / completed; blocked tasks visible.
- **Active worktrees**: `git worktree list` — confirms per-unit isolation.
- **Team config**: `cat ~/.claude/teams/engage-v2-swarm/config.json | jq '.members[] | {name, agentType, backendType}'`
- **Team-lead inbox**: `cat ~/.claude/teams/engage-v2-swarm/inboxes/team-lead.json | jq '.'` — incoming worker reports + idle notifications.
- **Per-unit inbox** (if you need to message a worker directly): `~/.claude/teams/engage-v2-swarm/inboxes/<unit_id>.json`.
- **tmux panes** (if tmux backend auto-detected): `tmux list-panes` — one per teammate.

## Escalation matrix

| Symptom | Action |
|---|---|
| Worker BLOCKED with context gap | Provide context, re-dispatch same model |
| Worker BLOCKED with reasoning gap | Re-dispatch with Opus / more capable model |
| Worker BLOCKED "plan is wrong" | Escalate to human |
| Spec reviewer FAIL, worker disagrees after two loops | Escalate to human |
| Code-quality Critical finding worker cannot fix | Escalate to human with reviewer transcript |
| Rebase conflict outside declared region | Return to spec review with "region-scoped edit violation" |
| Rebase conflict inside declared region, auto-resolvable | Orchestrator accepts worker's side, records in log |
| Rebase conflict inside declared region, ambiguous | Re-dispatch worker with conflict context |
| Post-merge regression on integration branch | Revert the merge; re-dispatch responsible unit with failure log; escalate if unresolved after one retry |
| Origin plan amendment mid-run | Snapshot current state, update plan references (manifest + this runbook), escalate to human |
| Heartbeat timeout (>5 min silence) | Reclaim task; re-dispatch fresh worker |
| Team cleanup fails with "active members" | Request shutdown for each listed member, wait for shutdown_approved, then cleanup |

## Failure-mode drills

Before real Wave-1 dispatch, the orchestrator may dry-run one or more of these drills to confirm the protocol:

- **Spec-gap drill**: render Unit 0.1's worker prompt; synthetically inject a diff that adds an extra file; confirm spec reviewer flags it.
- **Secret-leak drill**: render a diff that includes a real-looking API key; confirm code-quality reviewer flags it as Critical.
- **Shared-file conflict drill**: synthetically create two branches that both edit `scripts/broll_gen/factory.py` in overlapping regions; confirm rebase produces a conflict and the orchestrator returns to spec review.

Drills are not mandatory but recommended for the first run of this topology.
