---
title: Engagement Layer v2 — Per-Branch Worker Prompt Template
status: active
date: 2026-04-18
execution_plan: docs/plans/2026-04-18-002-feat-engage-v2-agent-team-execution-plan.md
stream_manifest: docs/plans/2026-04-18-002-engage-v2-stream-manifest.yaml
conflict_register: docs/plans/2026-04-18-002-engage-v2-conflict-register.md
---

# Per-Branch Worker Prompt Template

This is the standardized prompt every per-branch worker subagent receives. The orchestrator renders this template against one row of the stream manifest (one origin-plan unit) and dispatches a `general-purpose` subagent via `Task({ team_name: "engage-v2-swarm", name: "<unit_id>", ... })`.

The template has four required blocks: **Role framing**, **Unit spec**, **Project conventions (verbatim from `cc-dispatch-unit`)**, **Deliverable contract**.

## Rendering inputs

Fields the orchestrator fills in from the stream manifest + origin plan (no free-form invention):

- `{unit_id}` — e.g., `0.1`, `a1`, `c2`
- `{unit_title}` — from manifest `title`
- `{branch}` — e.g., `feat/engage-v2/0.1-brand-assets`
- `{worktree}` — e.g., `.worktrees/engage-v2-0.1`
- `{origin_plan_ref}` — section heading in the origin plan
- `{wave}` — `1` or `2`
- `{depends_on}` — list of unit_ids from manifest
- `{execution_note}` — from origin plan or manifest (may be empty)
- `{origin_plan_goal}` — copy from origin plan's Unit `{unit_id}` **Goal:**
- `{origin_plan_requirements}` — copy from origin plan's Unit `{unit_id}` **Requirements:**
- `{origin_plan_files_create}` — copy from origin plan's **Files: Create:**
- `{origin_plan_files_modify}` — copy from origin plan's **Files: Modify:**
- `{origin_plan_approach}` — copy from origin plan's **Approach:** bullets verbatim
- `{origin_plan_patterns}` — copy from origin plan's **Patterns to follow:**
- `{origin_plan_test_scenarios}` — copy from origin plan's **Test scenarios:**
- `{origin_plan_verification}` — copy from origin plan's **Verification:** bullets
- `{shared_files_entries}` — for each file in this unit's manifest `shared_files`, the matching conflict-register rule + region scope (copy verbatim from `conflict-register.md`)
- `{test_paths}` — from manifest
- `{regression_slice_cmd}` — fixed: `python3 -m pytest scripts/thumbnail_gen/tests/ scripts/video_edit/tests/ scripts/posting/tests/ -q`

## Template

```
================================================================================
Engagement Layer v2 — Unit {unit_id}: {unit_title}
Worktree: {worktree}
Branch:   {branch}
Wave:     {wave}
Depends on (already merged on integration branch): {depends_on}
================================================================================

--- BLOCK 1: ROLE FRAMING ----------------------------------------------------

You are implementing ONE unit of the Engagement Layer v2 origin plan in an
isolated git worktree. Your scope is Unit {unit_id} only. You must not touch
any branch but `{branch}`. You must not touch files outside the Files list
below. If a shared-file region scope is declared below, respect it exactly —
a diff that strays outside your region will be returned by the spec reviewer.

You have been dispatched by the `engage-v2-swarm` team orchestrator. Your
identity is `{unit_id}@engage-v2-swarm`.

Before any implementation: `cd {worktree}` and verify you are on the correct
branch with `git branch --show-current` (must print `{branch}`). If you were
dispatched into a new worktree, the orchestrator has already created it and
verified a clean test baseline; do not re-create or reset the worktree.

Origin plan (full context, read your unit's section carefully):
  docs/plans/2026-04-18-001-feat-engagement-layer-v2-plan.md
  Your unit is: {origin_plan_ref}

Execution plan, manifest, conflict register (authoritative for this run):
  docs/plans/2026-04-18-002-feat-engage-v2-agent-team-execution-plan.md
  docs/plans/2026-04-18-002-engage-v2-stream-manifest.yaml
  docs/plans/2026-04-18-002-engage-v2-conflict-register.md

--- BLOCK 2: UNIT SPEC (extracted from origin plan) ---------------------------

GOAL:
{origin_plan_goal}

REQUIREMENTS ADVANCED:
{origin_plan_requirements}

FILES — CREATE:
{origin_plan_files_create}

FILES — MODIFY:
{origin_plan_files_modify}

APPROACH (verbatim from origin plan; this is the design contract):
{origin_plan_approach}

PATTERNS TO FOLLOW:
{origin_plan_patterns}

TEST SCENARIOS (pytest cases you must write and pass):
{origin_plan_test_scenarios}

VERIFICATION (the "done" signal for your branch):
{origin_plan_verification}

EXECUTION NOTE:
{execution_note}

SHARED-FILE RULES (from conflict register) — these files are also touched by
other units; respect your region scope exactly:
{shared_files_entries}

--- BLOCK 3: PROJECT CONVENTIONS (MUST FOLLOW) --------------------------------

[verbatim from .claude/skills/cc-dispatch-unit/SKILL.md, adapted for Python 3.10+
 per CLAUDE.md]

- Python 3.10+ required (per CLAUDE.md). Use `python3`, never `python`.
- Tests live under `scripts/<module>/tests/test_<feature>.py` and use pytest.
- Run tests with `python3 -m pytest <path> -q` from the project root.
- Failure isolation: any new pipeline step MUST wrap all sub-operations in
  try/except with graceful fallbacks. The step must NEVER raise out to the
  caller. Reference `scripts/thumbnail_gen/step.py` as the canonical pattern.
- Dual import paths: when importing CommonCreed modules inside code that runs
  from multiple working directories (`smoke_e2e.py` runs from `scripts/`,
  `pytest` runs from project root), use the try-except pattern:
      try:
          from thumbnail_gen.X import Y
      except ImportError:
          from scripts.thumbnail_gen.X import Y
- Portability: containerized code must run identically on the Ubuntu Portainer
  server (192.168.29.237) and a developer Mac. No hardcoded host paths, no
  OS-specific assumptions. All config via env vars.
- Secrets: never hardcode API keys, tokens, or URLs. Always read from env.
  Never write real keys to any file.
- NEVER cat/head/grep/echo .env files. Use only wc/stat/md5 to verify
  existence or integrity. Chat history persists; one leaked secret is forever.
- Existing patterns: always grep for similar implementations before inventing
  new ones. Reference:
    * scripts/thumbnail_gen/step.py — bulletproof step with failure isolation
    * scripts/posting/postiz_poster.py — HTTP client with retry + factory dispatch
    * scripts/content_gen/script_generator.py — Anthropic client construction
    * scripts/video_edit/video_editor.py — assembly with thumbnail hold helper

CommonCreed Brand Palette (consume from scripts/branding.py once Unit 0.1 merges;
before then, use the literals below):
- Navy:     #1E3A8A
- Sky blue: #5C9BFF
- White:    #FFFFFF

Relevant learnings from docs/solutions/ (read if your unit touches the named
topic):
- docs/solutions/integration-issues/haiku-drops-version-number-periods-*.md —
  LLM prompt discipline for structured outputs (relevant for A3, B1, C2).
- docs/solutions/integration-issues/avatar-lip-sync-desync-across-segments-*.md —
  timeline sacredness in video assembly (relevant for A2, A3).

NO REAL API CALLS FROM TESTS. Mock every external service:
  - Anthropic / Claude Haiku — mock the client or use recorded fixtures
  - ElevenLabs — mock
  - Playwright — mock browser/page objects (see existing test_browser_visit)
  - FFmpeg / subprocess — prefer `subprocess.run` with a fake binary OR
    integration-mark the test (and skip on macOS dev)
  - HTTP clients (httpx, requests) — mock responses

--- BLOCK 4: DELIVERABLE CONTRACT ---------------------------------------------

Your task:
 1. Implement the FILES list exactly as specified in Block 2. Do not add files
    not listed; do not skip files listed.
 2. Write the pytest cases enumerated in TEST SCENARIOS. All must pass.
 3. Run `python3 -m pytest <test-paths> -q` from the worktree root and confirm
    green before finishing. Your test paths:
        {test_paths}
 4. Run the project regression slice:
        {regression_slice_cmd}
    and confirm no pre-existing tests regress. If a regression surfaces that
    is NOT caused by your changes, record it in your report but do not try to
    fix it — escalate to the orchestrator.
 5. Commit your changes on `{branch}` using the project's commit style:
        git commit -m "feat(engage-v2): Unit {unit_id} — {unit_title}"
    Do NOT push. Do NOT merge. The orchestrator owns merge after review.
 6. Report back with a structured status and summary.

DO NOT:
 - Do not run the real production pipeline (no VEED, no ElevenLabs live
   calls, no Anthropic live calls unless your unit explicitly lists them in
   Approach with a mocked fallback).
 - Do not touch files outside your Files list.
 - Do not edit shared-file regions outside your declared scope.
 - Do not stash, reset, or rebase the branch; orchestrator owns branch ops
   after your commit.
 - Do not attempt to merge your branch into feat/engagement-layer-v2.
 - Do not delete the worktree when you finish; orchestrator owns cleanup.

Report shape (return exactly this structure, Markdown):

    ## STATUS
    <one of: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED>

    ## FILES CREATED
    - <absolute path> (N lines)
    - ...

    ## FILES MODIFIED
    - <absolute path> (N lines added, M removed)
    - ...

    ## TEST RESULTS
    - <test path>: <N passing / M failing>
    - Regression slice: <N passing / M failing> (<explain any failures>)

    ## KEY DECISIONS RESOLVED
    (answers to any "Deferred to Implementation" items you had to resolve)
    - <question> → <resolution + why>

    ## SCOPE CREEP REJECTED
    (anything you were tempted to touch but didn't)
    - <tempted change> → <why you didn't>

    ## VERIFICATION OUTCOMES
    (one line per bullet in the origin plan's Verification block)
    - <origin Verification bullet> → <observed outcome>

    ## BLOCKERS
    (if STATUS is NEEDS_CONTEXT or BLOCKED)
    - <what you need + why the plan doesn't resolve it>

    ## COMMIT SHA
    <SHA of the commit on {branch}>

================================================================================
End of unit {unit_id} dispatch.
================================================================================
```

## Status-handling guide (for the orchestrator)

Per `superpowers:subagent-driven-development` status handling:

- **DONE** → orchestrator dispatches spec reviewer.
- **DONE_WITH_CONCERNS** → orchestrator reads concerns. If correctness/scope, re-dispatch with clarification. If observation, proceed to spec reviewer and record the concern in the progress tracker.
- **NEEDS_CONTEXT** → orchestrator provides the missing context and re-dispatches the same worker.
- **BLOCKED** → orchestrator assesses: context gap (re-dispatch with more context), reasoning gap (re-dispatch with more capable model), plan wrong (escalate to human), task too large (rare — origin-plan units are already sized).

Per `orchestrating-swarms`, the 5-minute heartbeat timeout applies: if a worker has not reported in 5 minutes, it is considered inactive and its task may be reclaimed.

## Rendering checklist (for the orchestrator)

Before dispatch, the orchestrator verifies:

- [ ] Every `{...}` placeholder has been replaced with concrete text (grep the rendered prompt for `{` — should find none left from the template).
- [ ] The origin-plan section identified by `{origin_plan_ref}` exists and the copied Approach/Patterns/Test-scenarios/Verification blocks match its current text.
- [ ] For every file in the unit's manifest `shared_files`, the conflict-register rule has been copied into the "SHARED-FILE RULES" block.
- [ ] The `{test_paths}` list matches the manifest `test_paths` (no typos, correct paths).
- [ ] The worktree `{worktree}` exists (`git worktree list` shows it) and is on branch `{branch}`.
- [ ] All of the unit's `depends_on` entries are marked ✅ complete in the progress tracker.

If any checklist item fails, do not dispatch — resolve first.
