---
name: cc-dispatch-unit
description: Dispatch a specific implementation unit from any CommonCreed plan file to a focused subagent, carrying project conventions and success criteria. Use when you want to execute one unit of a plan autonomously without context bleed.
---

# cc-dispatch-unit

Dispatch one implementation unit from a CommonCreed plan to a subagent. The subagent gets the plan file, the specific unit's goal/files/approach/tests, the project conventions, and clear verification criteria. It returns a structured report on what it did.

## Usage

```
/cc-dispatch-unit <plan-path> <unit-number>
/cc-dispatch-unit <plan-path> <unit-number> --isolation=worktree
```

Examples:
- `/cc-dispatch-unit docs/plans/2026-04-06-002-feat-end-to-end-pipeline-plan.md 2`
- `/cc-dispatch-unit docs/plans/2026-04-06-002-feat-end-to-end-pipeline-plan.md 3 --isolation=worktree`

## How to run this skill

1. **Read the plan file** passed as first arg. Locate the implementation unit matching the second arg (the `N` in `**Unit N:**`). Extract: Goal, Requirements, Dependencies, Files, Approach, Execution note, Patterns to follow, Test scenarios, Verification.

2. **Check dependencies before dispatching.** If the unit lists `Dependencies: Unit X` where X is not yet marked `[x]` in the plan, STOP and report "blocked: unit N depends on unit X which is not complete". Do not dispatch.

3. **Check the progress tracker** if one exists (e.g., `docs/plans/<same-prefix>-progress.md`). If another subagent is currently marked "in_progress" on this unit, STOP and report "already in progress".

4. **Update the progress tracker** (if present) to mark this unit "in_progress" with a timestamp and the name of the dispatched subagent.

5. **Dispatch via the Agent tool** with subagent_type=general-purpose. Pass the following prompt template (fill in the unit-specific fields):

   ```
   You are implementing ONE unit of a CommonCreed plan.

   Plan file: <absolute plan path>
   Unit number: <N>

   Read the plan file first to understand the full context. Then execute ONLY Unit <N>.

   Unit <N> spec (extracted):
   - Goal: <Goal>
   - Requirements: <Requirements>
   - Files to create/modify/test: <Files list>
   - Approach: <Approach bullets>
   - Execution note: <if present>
   - Patterns to follow: <patterns>
   - Test scenarios: <scenarios>
   - Verification: <outcomes>

   Project conventions (MUST follow):
   - Python 3.9 compatible (macOS system Python). Use `python3`, never `python`.
   - Tests live under `scripts/<module>/tests/test_<feature>.py` and use pytest.
   - Run tests with `python3 -m pytest <path> -q` from the project root.
   - Failure isolation: any new pipeline step MUST wrap all sub-operations in try/except with graceful fallbacks. The step must NEVER raise out to the caller. Reference `scripts/thumbnail_gen/step.py` as the canonical pattern.
   - Dual import paths: when importing CommonCreed modules inside code that runs from multiple working directories (`smoke_e2e.py` runs from `scripts/`, `pytest` runs from project root), use the try-except pattern:
     ```
     try:
         from thumbnail_gen.X import Y
     except ImportError:
         from scripts.thumbnail_gen.X import Y
     ```
   - Portability: containerized code must run identically on Synology DS1520+ (8 GB RAM, Celeron J4125) and a developer Mac. No hardcoded host paths, no OS-specific assumptions. All config via env vars.
   - Secrets: never hardcode API keys, tokens, or URLs. Always read from env. Never write real keys to any file.
   - Existing patterns: always grep for similar implementations before inventing new ones. Reference:
     * `scripts/thumbnail_gen/step.py` — bulletproof step with failure isolation
     * `scripts/posting/postiz_poster.py` — HTTP client with retry + factory dispatch
     * `scripts/content_gen/script_generator.py` — Anthropic client construction
     * `scripts/video_edit/video_editor.py` — assembly with thumbnail hold helper

   Relevant learnings from `docs/solutions/`:
   - `docs/solutions/integration-issues/haiku-drops-version-number-periods-2026-04-06.md` — LLM prompt discipline for structured outputs
   - `docs/solutions/integration-issues/avatar-lip-sync-desync-across-segments-2026-04-05.md` — timeline sacredness in video assembly

   Your task:
   1. Implement the unit's Files list exactly as specified in the plan
   2. Write the tests enumerated in Test scenarios (all must pass)
   3. Run `python3 -m pytest <test-file> -q` and confirm green before finishing
   4. Run `python3 -m pytest scripts/thumbnail_gen/tests/ scripts/video_edit/tests/ scripts/posting/tests/ -q` to confirm no regressions in existing tests
   5. Do NOT run the real pipeline (no VEED, no ElevenLabs, no Sonnet live calls unless explicitly listed in the unit). Mock external services in tests.
   6. Do NOT commit. The orchestrator will commit after verifying.

   Report back (structured):
   - Files created (list with absolute paths)
   - Files modified (list with line ranges if possible)
   - Test results (X/Y passing, any failures)
   - Key decisions made when the plan left ambiguity (and which deferred question you resolved)
   - Any scope creep you had to reject
   - Verification outcome (one line per Verification bullet from the plan)
   - Blockers, if any, that prevent marking the unit complete
   ```

6. **When the agent returns**, verify the report:
   - All listed files exist
   - Full test suite still green (run it yourself in the orchestrator, don't trust the report)
   - No unintended modifications to files outside the unit's file list

7. **Update the plan file**: mark the unit checkbox `- [x]` if verification passed, leave `- [ ]` and log the blocker in the progress tracker if not.

8. **Update the progress tracker**: mark the unit as "complete" (with commit-pending state if applicable) or "blocked" with the blocker text.

9. **Report to the user**: compact summary of what changed, what's now unblocked for parallel dispatch, and what should happen next.

## Rules

- **Never dispatch a unit whose dependencies are not complete.** Check the dependency graph first.
- **Never dispatch two subagents to the same unit simultaneously.** Progress tracker is the lock.
- **Never commit the subagent's work automatically.** The orchestrator runs final verification and the user owns the commit decision.
- **Always use isolation=worktree when the unit touches files already touched by another in-progress unit.** Otherwise default isolation is fine.
- **Prefer parallel dispatch via multiple Agent tool calls in one message** when units are genuinely independent (different file scopes, no shared imports).
- **If the plan file has a `deepened:` frontmatter field**, treat the deepened sections as authoritative over any conflicting earlier content.

## When NOT to use this skill

- When the task is a quick fix that doesn't touch multiple files
- When you're exploring/debugging rather than executing a defined spec
- When the plan is still in draft and hasn't been through `ce:plan` review
- When the user wants to drive the implementation themselves and is just asking questions
