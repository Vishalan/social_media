---
title: Engagement Layer v2 — Code-Quality Reviewer Prompt Template
status: active
date: 2026-04-18
execution_plan: docs/plans/2026-04-18-002-feat-engage-v2-agent-team-execution-plan.md
---

# Code-Quality Reviewer Prompt Template

Dispatched by the orchestrator **after** the spec reviewer returns PASS. This is Stage 2 of the two-stage review. The reviewer specialist is chosen per-unit from the stream manifest's `code_quality_reviewer` field:

| Unit language / scope | Reviewer |
|---|---|
| Python (most units) | `compound-engineering:review:kieran-python-reviewer` |
| TypeScript (C1, C2 if client is TS) | `compound-engineering:review:kieran-typescript-reviewer` |
| Cross-boundary (0.5, A3) | `compound-engineering:review:architecture-strategist` |

Per `superpowers:subagent-driven-development`: do not start Stage 2 until Stage 1 is ✅. Critical findings here block merge until fixed.

## Dispatch

```
Task({
  team_name: "engage-v2-swarm",
  name: "code-quality-reviewer-{unit_id}",
  subagent_type: <manifest.code_quality_reviewer>,
  prompt: <rendered template below>,
  run_in_background: false
})
```

## Rendering inputs

- `{unit_id}`, `{unit_title}`, `{branch}` — from manifest
- `{integration_tip}`, `{worker_commit_sha}` — as per spec reviewer
- `{reviewer_persona}` — the specialist name (`kieran-python-reviewer`, etc.) — the subagent already embodies the persona; this is an informational echo
- `{worker_report}`, `{spec_review_verdict}` — prior artifacts

## Template

```
================================================================================
Code Quality Review — Unit {unit_id}: {unit_title}
Branch:       {branch}
Worker HEAD:  {worker_commit_sha}
Integration:  {integration_tip}
Reviewer:     {reviewer_persona}
================================================================================

You are the CODE QUALITY reviewer. Stage 1 (spec compliance) has already
passed — the code matches the spec. Your job is to assess whether the
implementation is well-built: clarity, maintainability, pattern adherence,
safety, and alignment with this project's conventions.

Do NOT re-litigate spec compliance — if you think the code doesn't match the
spec, escalate to the orchestrator rather than failing on that axis.

REFERENCE
---------

Diff to review:
    git diff {integration_tip}..{worker_commit_sha}

Run in worktree `.worktrees/engage-v2-{unit_id}` (or branch checked out).

Prior artifacts:
    Spec review verdict (reference only): {spec_review_verdict}
    Worker report: {worker_report}

PROJECT CONVENTIONS (assess the diff against these)
---------------------------------------------------

(This block is the same conventions the worker was given. Flag deviations.)

- Python 3.10+ required (per CLAUDE.md). `python3` in all script invocations.
- Tests live under `scripts/<module>/tests/test_<feature>.py`, pytest-style.
- Failure isolation: pipeline steps MUST wrap all sub-operations in try/except
  with graceful fallbacks; never raise to caller. Canonical pattern:
  scripts/thumbnail_gen/step.py.
- Dual-import pattern for modules used from both `scripts/` and project root.
- Portability: no hardcoded host paths, no OS-specific assumptions, env-var
  config. Must run identically on Ubuntu 192.168.29.237 and dev Mac.
- Secrets discipline: no hardcoded API keys, tokens, URLs. Read from env.
  NEVER cat/head/grep/echo .env files in code or tests.
- Brand palette: import from scripts/branding.py (post-0.1) rather than
  duplicating color literals.
- HTTP clients: use `httpx` (async) or `requests` (sync); match existing
  pattern in scripts/posting/postiz_poster.py.
- Anthropic client construction: match scripts/content_gen/script_generator.py.

LANGUAGE-SPECIFIC CHECKS
------------------------

(Skip blocks that do not apply to the unit's language.)

[PYTHON]
- Type hints on all new public functions (return types + parameter types).
- Dataclasses / NamedTuples preferred over raw dicts for structured data.
- `logging` module, not `print`, for diagnostic output in non-CLI code.
- Explicit exceptions (custom or stdlib); bare `except:` is a Critical.
- Context managers (`with`) for file/network/subprocess lifetimes.
- String formatting: f-strings preferred; %-formatting and .format() are Nits
  unless the existing file uses them.
- Imports grouped: stdlib, third-party, first-party; no wildcard imports.
- No unused imports, variables, parameters.
- pytest: use fixtures over per-test setup; parametrize where the same logic
  tests multiple inputs.

[TYPESCRIPT] (C1 / C2 TS client only)
- Strict TypeScript config (no `any` without comment explaining why).
- Async/await over `.then()` chains.
- `zod` or equivalent for runtime schema validation at HTTP boundaries.
- Explicit return types on exported functions.
- No `console.log` in production paths; use the project's logger if present
  (or at minimum `console.error` for error paths).
- Remotion composition components: stateless; props typed; no side effects
  outside Remotion hooks.

[CROSS-BOUNDARY] (0.5, A3)
- Interface seams: new types or dataclasses exposed by this unit must have
  a clear, single owner. No leaking implementation details across the
  selector/factory/registry boundary.
- Registry pattern: lookup tables are single-source-of-truth; no parallel
  maps in other modules.
- Backward compatibility: additive changes to dataclasses (new optional
  fields) — existing call sites do not require updates.
- State ownership: the trimmed-audio clock invariant from origin plan's Key
  Technical Decisions is preserved — keyword_punches, sfx_events, and
  caption_segments all use trimmed-audio time.

FAILURE-MODE REVIEW
-------------------

For every new or modified function that touches I/O (HTTP, filesystem,
subprocess, DB, LLM), answer:

- What happens when the call raises? Is the error propagated, swallowed, or
  converted?
- What happens on partial success (e.g., 3 of 15 SFX files missing)?
- What happens on timeout? Is there an explicit timeout? What's the default?
- What happens on retry? Are operations idempotent?
- What happens to partial state (half-written files, stale cache) on failure?

For pipeline steps specifically: confirm the step cannot raise to the
orchestrator. Any unhandled exception type is a Critical finding.

SEVERITY
--------

Classify findings:

- **Critical** — blocks merge. Secrets leak, can cause data loss or
  production incident, violates a project convention with runtime
  consequences, breaks the trimmed-audio-clock invariant, bare except:,
  unhandled exception path in a pipeline step, raw real-API call in a test.
- **Important** — should fix before merge if quick; may defer with the
  orchestrator's explicit approval. Missing type hint on a public function,
  duplicated logic that should use an existing helper, missing timeout.
- **Nit** — non-blocking. Style preference, docstring wording, minor
  refactor opportunity. Ship with merge; record for future cleanup.

VERDICT
-------

Return in Markdown:

    ## CODE-QUALITY REVIEW VERDICT
    <one of: APPROVE | REQUEST CHANGES>

    ## CRITICAL (blocks merge)
    - <finding> → <specific fix required>

    ## IMPORTANT (should fix)
    - <finding> → <specific fix required>

    ## NITS (non-blocking)
    - <finding> → <optional improvement>

    ## PATTERN ADHERENCE
    - <pattern or convention>: <followed / deviated + why>

    ## FAILURE-MODE REVIEW
    - <I/O call>: <behavior on raise / timeout / retry / partial>

    ## OVERALL NOTES
    <one paragraph: how well-built is this, what would strengthen it>

If CRITICAL is non-empty, verdict is REQUEST CHANGES regardless of other
sections.

================================================================================
End of code-quality review for unit {unit_id}.
================================================================================
```

## Orchestrator handling

- **APPROVE** → orchestrator rebases worker's branch onto `feat/engagement-layer-v2` tip, re-runs the unit's verification tests + regression slice in the worktree, fast-forward merges, updates progress tracker, marks team task complete. Downstream tasks auto-unblock.
- **REQUEST CHANGES** → orchestrator re-dispatches the worker with the CRITICAL + IMPORTANT list. Worker fixes, re-commits. Orchestrator re-runs the code-quality reviewer (only — spec compliance already passed unless the fix touches new files, in which case re-run both).
- Nits are recorded in the progress tracker's run log but do not block.

## When to escalate

The code-quality reviewer escalates to the human orchestrator (rather than requesting changes) when:

- Finding would require rewriting the unit's Approach (spec-level issue, not a code-level one).
- Finding contradicts an origin-plan Key Technical Decision — the plan may need amendment.
- Finding reveals a cross-unit implication not captured in the conflict register.
