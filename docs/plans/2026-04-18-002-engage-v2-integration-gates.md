---
title: Engagement Layer v2 — Integration-Branch Gate Checklist
status: active
date: 2026-04-18
execution_plan: docs/plans/2026-04-18-002-feat-engage-v2-agent-team-execution-plan.md
---

# Integration-Branch Gate Checklist

Machine-readable gates the integration branch `feat/engagement-layer-v2` must pass between waves and before rollup. Every gate item is a concrete, runnable check — not a vibe. Orchestrator records results in the Gate sections of the progress tracker.

## Gate 1 — post-Wave-1 (unlocks Wave 2)

Run after all six Wave-1 tasks (0.1–0.6) are merged into `feat/engagement-layer-v2`.

| # | Check | Command / observation | Owner | Pass when |
|---|-------|----------------------|-------|-----------|
| 1.1 | Wave-1 unit tests green | `python3 -m pytest scripts/tests/test_branding.py scripts/broll_gen/tests/test_headline_burst.py scripts/video_edit/tests/test_caption_render_smoke.py scripts/audio/tests/test_sfx.py scripts/topic_intel/tests/test_article_extractor.py scripts/broll_gen/tests/test_selector_extension.py scripts/broll_gen/tests/test_registration_consistency.py -q` | orchestrator | Exit 0, all green |
| 1.2 | Project regression slice | `python3 -m pytest scripts/thumbnail_gen/tests/ scripts/video_edit/tests/ scripts/posting/tests/ -q` | orchestrator | Exit 0, no new failures vs pre-Wave-1 baseline |
| 1.3 | Sidecar container build: libass present | `docker build --target check-libass sidecar/` (or full build: `docker build -t commoncreed_sidecar:wave1 sidecar/`) | orchestrator | Build succeeds; Dockerfile's `ffmpeg -filters \| grep -qE "^ . ass "` assertion runs |
| 1.4 | Sidecar container build: Inter font registered | same build; look for `fc-list \| grep -qi "Inter"` stage passing | orchestrator | Build succeeds |
| 1.5 | Three-file registration linter | `python3 -m pytest scripts/broll_gen/tests/test_registration_consistency.py -q` | orchestrator | Exit 0 — `_VALID_TYPES == factory if-chain == schema.primary == schema.fallback == BROLL_REGISTRY` |
| 1.6 | `commoncreed_pipeline.py` smoke — progresses past topic step | run the pipeline in dry-run / no-API mode (use the existing mocking infra in `scripts/smoke_e2e.py`'s test fixtures) | orchestrator | Pipeline log shows `extracted_article: N paragraphs` line for a mocked article URL |
| 1.7 | `smoke_e2e.py` stdout contract additive-only | diff the final `print(...)` block in `smoke_e2e.py` (HEAD) vs its state at `feat/engagement-layer-v2~6` (before Unit 0.4). Every pre-existing key must still appear; new keys are appended. | orchestrator | `diff` shows only additions, no deletions or reorderings |
| 1.8 | `.worktrees/` directory remains gitignored | `git check-ignore -v .worktrees/anything` | orchestrator | Match on line 54 of `.gitignore` |
| 1.9 | No secrets in diff | `git diff main..feat/engagement-layer-v2 \| grep -iE "(api[-_]?key\|sk-\|ak_\|token\|password\|secret)" \| grep -v "# "` (ignore comments) | orchestrator | No matches — any match triggers escalation |
| 1.10 | SFX files under size budget | `find assets/sfx -name '*.wav' -size +50k` | orchestrator | No output (all 15 files ≤ 50 KB per origin-plan Unit 0.3) |

**All 10 must pass before Wave 2 dispatches.** Red on any item halts the run until resolved.

## Gate 2 — post-Wave-2 (unlocks rollup prep)

Run after all eight Wave-2 tasks (A1, A2, A3, B1, B2, B3, C1, C2) are merged.

| # | Check | Command / observation | Owner | Pass when |
|---|-------|----------------------|-------|-----------|
| 2.1 | All Wave-2 unit tests green | `python3 -m pytest scripts/broll_gen/tests/test_phone_highlight.py scripts/video_edit/tests/test_ass_captions_word_level.py scripts/content_gen/tests/test_keyword_extractor.py scripts/broll_gen/tests/test_tweet_reveal.py scripts/broll_gen/tests/test_split_screen.py scripts/broll_gen/tests/test_timeline_rhythm.py scripts/broll_gen/tests/test_cinematic_chart.py -q` | orchestrator | Exit 0 |
| 2.2 | No Wave-1 regression | re-run Gate 1 checks 1.1, 1.2, 1.5 | orchestrator | All still green |
| 2.3 | Phone-highlight render smoke | produce a 30–60 s short with `phone_highlight` as a b-roll type; inspect visually that the active phrase tracks the voiceover at phrase level (per origin plan Unit A1 Verification) | human + orchestrator | Output MP4 exists; inspection passes |
| 2.4 | Word-captions render smoke | extract a frame at t=2.5s of an A2-enabled short; confirm active word is visually distinct (per Unit A2 Verification) | human + orchestrator | Frame extracted; OCR or visual check passes |
| 2.5 | Zoom-punch + SFX render smoke | produce a 60 s short; confirm 4–7 zoom-punch moments, audible SFX, render time delta ≤ 90 s (per Unit A3 Verification) | human + orchestrator | All three conditions met |
| 2.6 | Tweet-reveal render smoke | produce a tweet-reveal short; visual inspection of card + counter animation (per Unit B1 Verification) | human + orchestrator | Clean card, counter animates, brand colors |
| 2.7 | Split-screen render smoke | produce a side-by-side `browser_visit` × 2; confirm no overlap, divider visible; plus `stats_card` × 2 at 540 px (per Unit B2 Verification) | human + orchestrator | Both smokes pass |
| 2.8 | Remotion container build | `docker build -t commoncreed_remotion:wave2 deploy/remotion/` | orchestrator | Build succeeds; `docker images \| grep commoncreed_remotion` shows ≤ 1.8 GB |
| 2.9 | Remotion container `/healthz` | `docker run --rm -p 3030:3030 commoncreed_remotion:wave2` then `curl -f http://localhost:3030/healthz` | orchestrator | `{"ok": true}` returned |
| 2.10 | cinematic_chart render smoke | end-to-end run on a benchmark topic with `CINEMATIC_CHART_ENABLED=true`; confirm chart MP4 renders and integrates; render delta ≤ 60 s (per Unit C2 Verification) | human + orchestrator | Conditions met |
| 2.11 | `phone_highlight` match-rate | sample 3 mocked phone_highlight renders; confirm phrase-to-paragraph match rate ≥ 60% (warning threshold from origin plan Unit A1) | orchestrator | 3/3 ≥ 60% |
| 2.12 | Stdout contract still additive-only | re-run Gate 1 check 1.7 | orchestrator | Same — no deletions or reorderings since Wave 1 |

## Gate 3 — rollup readiness

Run before opening the PR to `main`.

| # | Check | Command / observation | Owner | Pass when |
|---|-------|----------------------|-------|-----------|
| 3.1 | All 14 origin-plan unit rows in tracker marked merged | read `docs/plans/2026-04-18-002-engage-v2-progress.md` | orchestrator | All 14 rows have `✅ merged` + timestamp |
| 3.2 | All 8 scaffolding unit rows marked completed | same tracker | orchestrator | All 8 rows `✅ completed` |
| 3.3 | Linear history on integration branch | `git log --oneline --graph main..feat/engagement-layer-v2` | orchestrator | No merge commits with multiple parents (only fast-forwards) |
| 3.4 | No pending uncommitted changes on integration branch | `git status` | orchestrator | `nothing to commit, working tree clean` |
| 3.5 | No per-unit branches with unmerged commits | `git branch --no-merged feat/engagement-layer-v2 \| grep 'feat/engage-v2'` | orchestrator | Empty output |
| 3.6 | Secrets sweep on full diff | `git diff main..feat/engagement-layer-v2 \| grep -iE "(sk-\|ak_[a-zA-Z0-9]{10,}\|api[-_]?key[[:space:]]*[=:][[:space:]]*['\"][a-zA-Z0-9]{20,})"` | orchestrator | Empty |
| 3.7 | CHANGELOG entry drafted | inspect `CHANGELOG.md` for an `Engagement Layer v2` section covering R1–R8 | human | Entry present, covers all 8 requirements |
| 3.8 | Origin plan reconciled | diff origin-plan frontmatter `status:` — if still `active`, update to `completed` in the rollup commit | human | `status: completed` after rollup merge |
| 3.9 | PR body drafted | links to: origin plan, execution plan, manifest, progress tracker, Gate 1/2 evidence, rollup runbook | human | All 6 links present |

**All gates must pass before merging to main.** The rollup runbook (Unit 8) is the instrument that executes the rollup itself.

## Evidence capture

For each gate run, the orchestrator captures evidence in the progress tracker's run log:

```
| 2026-04-22 14:30 | Gate 1 — 10/10 passing. Regression slice: 47/47 tests green (baseline: 47/47). Container build 2m18s. Pipeline smoke: `extracted_article: 5 paragraphs, lead 142 chars`. |
```

Evidence rows go into the "Run log" table at the bottom of `docs/plans/2026-04-18-002-engage-v2-progress.md`.

## When a gate fails

- Identify the failing item, determine which unit(s) caused it.
- If a single unit is responsible, revert the merge of that unit:
  ```bash
  git revert -m 1 <merge-sha>     # not applicable for fast-forward; use git reset
  # For ff-only merges:
  git reset --hard <commit before the bad unit>
  ```
  **Confirm with human before any destructive reset.** Prefer `git revert` on a per-unit commit if possible.
- Re-dispatch the responsible unit's worker with the failure context.
- Re-run the gate.

## Rerunning a gate

Gates are idempotent. Rerunning after a fix should produce the same pass/fail for every unchanged item; only the items touched by the fix should flip.
