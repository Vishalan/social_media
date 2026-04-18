---
title: Engagement Layer v2 — Rollout and Cleanup Runbook
status: active
date: 2026-04-18
execution_plan: docs/plans/2026-04-18-002-feat-engage-v2-agent-team-execution-plan.md
---

# Rollout and Cleanup Runbook

After Gate 3 is green (see `integration-gates.md`), the integration branch `feat/engagement-layer-v2` is ready to roll up into `main` and the team/worktree state can be torn down. This runbook is the single source of truth for those operations.

**Human-in-the-loop checkpoint:** the PR merge is a human-owned decision. The orchestrator prepares, proposes, and cleans up — but never merges to `main` without explicit approval.

## Phase 1 — Rollup PR

### 1.1 Confirm Gate 3

Open `docs/plans/2026-04-18-002-engage-v2-progress.md`. All scaffolding + all Wave-1 + all Wave-2 rows must show ✅. Gate 3 checklist must be green end-to-end. If any row is not ✅, stop here and go back to the orchestrator runbook.

### 1.2 Push the integration branch

From the main working tree (not a worktree):

```bash
cd /Users/vishalan/Documents/Projects/social_media
git checkout feat/engagement-layer-v2
git pull --ff-only origin feat/engagement-layer-v2 2>/dev/null || true   # ok if no remote
git push -u origin feat/engagement-layer-v2
```

Confirm the remote tracks the expected SHA:

```bash
git log -1 --format='%H %s'
git ls-remote origin feat/engagement-layer-v2
```

Both should print the same SHA.

### 1.3 Open the PR

Use `compound-engineering:git-commit-push-pr` or `gh pr create` directly.

```bash
gh pr create \
  --base main \
  --head feat/engagement-layer-v2 \
  --title "feat(engage-v2): Engagement Layer v2 — synced phone-highlight, animated captions, tweet/A-B reveals, cinematic charts" \
  --body "$(cat <<'EOF'
## Summary

This PR delivers **Engagement Layer v2** across three coordinated tiers, built in parallel on feature branches via the `engage-v2-swarm` agent team:

- **Tier A (engagement floor)** — phone-mockup synced article highlight, animated per-word burned-in captions, zoom-punch on keywords with an in-repo SFX library auto-placed at every cut.
- **Tier B (differentiator formats)** — tweet/X-post reveal, A/B split-screen comparison, denser editing-rhythm rules in the Haiku timeline planner.
- **Tier C (cinematic data viz)** — Remotion sidecar container + `cinematic_chart` b-roll type for animated bar charts, number tickers, and line charts.

All work grounded in the origin plan's 12 implementation units (Tier 0 substrate → Tier A/B/C). Execution topology: 14 feature branches + 14 worktrees + `engage-v2-swarm` team of teammates, with two-stage review (spec compliance + code quality) per branch before merge.

## Plan artifacts

- **Origin plan (WHAT):** [`docs/plans/2026-04-18-001-feat-engagement-layer-v2-plan.md`](docs/plans/2026-04-18-001-feat-engagement-layer-v2-plan.md)
- **Execution plan (HOW):** [`docs/plans/2026-04-18-002-feat-engage-v2-agent-team-execution-plan.md`](docs/plans/2026-04-18-002-feat-engage-v2-agent-team-execution-plan.md)
- **Stream manifest:** [`docs/plans/2026-04-18-002-engage-v2-stream-manifest.yaml`](docs/plans/2026-04-18-002-engage-v2-stream-manifest.yaml)
- **Conflict register:** [`docs/plans/2026-04-18-002-engage-v2-conflict-register.md`](docs/plans/2026-04-18-002-engage-v2-conflict-register.md)
- **Progress tracker:** [`docs/plans/2026-04-18-002-engage-v2-progress.md`](docs/plans/2026-04-18-002-engage-v2-progress.md)
- **Integration gates:** [`docs/plans/2026-04-18-002-engage-v2-integration-gates.md`](docs/plans/2026-04-18-002-engage-v2-integration-gates.md)

## Requirements satisfied

R1 Phone-highlight (Unit A1) | R2 Word captions (A2) | R3 Zoom-punch (A3) | R4 SFX library (0.3 + A3) | R5 Tweet reveal (B1) | R6 A/B split (B2) | R7 Rhythm rules (B3) | R8 Remotion + cinematic_chart (C1 + C2)

## Gates

- **Gate 1 (post-Wave-1):** ✅ all 10 items green — see tracker run log.
- **Gate 2 (post-Wave-2):** ✅ all 12 items green — render smokes attached.
- **Gate 3 (rollup readiness):** ✅ all 9 items green — history linear, no secrets, CHANGELOG drafted.

## Testing

- Unit tests: new pytest cases per origin-plan unit (all green).
- Regression: `scripts/thumbnail_gen/tests/` + `scripts/video_edit/tests/` + `scripts/posting/tests/` (no regressions).
- Container builds: sidecar (libass + Inter assertions), Remotion (≤ 1.8 GB, `/healthz` passes).
- Render smokes: phone_highlight, word-captions, zoom-punch + SFX, tweet_reveal, split_screen × 2 configurations, cinematic_chart — all produced playable MP4s and passed visual inspection.

## Post-Deploy Monitoring & Validation

**What to monitor/search**
- Logs: sidecar `commoncreed_pipeline.py` output for `keyword_punches`, `extracted_article`, and `sfx_events` lines.
- Remotion: `docker logs commoncreed_remotion` for render failures.
- Per-short render time: compare pre/post Wave-A rollout (target: ≤ 90 s delta per Tier A, ≤ 60 s per Tier C).

**Validation checks**
- `curl -f http://commoncreed_remotion:3030/healthz` → `{"ok": true}`
- `python3 -m pytest scripts/` → all green on production host
- Manual: one production short per tier inspected in Telegram review before public posting.

**Expected healthy behavior**
- Phone-highlight phrase tracks voiceover at phrase level.
- Word captions visibly animate per-word.
- Zoom-punch fires on 4–7 keyword moments; SFX audible but not dominant.
- Remotion `/healthz` returns within 500 ms.

**Failure signal(s) / rollback trigger**
- Any rendered short without captions, no zoom-punch, or broken audio mix → flip env flags `ENGAGEMENT_*_ENABLED=false` (see origin plan's Rollback paths).
- Remotion container restart loop → set `CINEMATIC_CHART_ENABLED=false`.
- First-3-second drop-off regresses > 5% vs baseline → emergency rollback via Portainer (revert to pre-merge image).

**Validation window & owner**
- Tier A: 14-day A/B vs baseline; owner: Vishalan.
- Tier B: 1-week opt-in, then full; owner: Vishalan.
- Tier C: 2-week opt-in, then full; owner: Vishalan.

**If no operational impact**
- N/A — this change reshapes the entire short-form rendering pipeline.

## Review notes

- 14 feature branches merged fast-forward — `git log --graph` on the integration branch is linear.
- Every commit passed two-stage review (spec + code quality) before merge. Critical findings blocked merge until fixed.
- Conflict register ensured no shared-file overlaps; region-scoped edits verified by spec reviewer on every branch.

---

[![Compound Engineering v2.54.1](https://img.shields.io/badge/Compound_Engineering-v2.54.1-6366f1)](https://github.com/EveryInc/compound-engineering-plugin)
🤖 Generated with Claude Opus 4.7 (1M context) via [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Display the PR URL after creation.

### 1.4 Handoff to human

The orchestrator stops here. A human:

1. Reads the PR.
2. Confirms render smokes (inspects the MP4s in Gate 2 evidence).
3. Confirms the origin plan's production-rollout gates are ready (Tier A 3-day canary, Tier B opt-in, Tier C opt-in — all documented in the origin plan's *Verification Strategy & Rollout* section).
4. Merges the PR to `main`.

The orchestrator may watch the PR for CI signals (if any) but does not merge.

## Phase 2 — Post-merge cleanup

After the human merges the PR to `main`:

### 2.1 Sync local main

```bash
cd /Users/vishalan/Documents/Projects/social_media
git checkout main
git pull --ff-only origin main
```

Confirm the merge commit is visible:

```bash
git log --oneline -5
```

### 2.2 Remove per-unit worktrees

```bash
for id in 0.1 0.2 0.3 0.4 0.5 0.6 a1 a2 a3 b1 b2 b3 c1 c2; do
  git worktree remove .worktrees/engage-v2-$id
done
```

Confirm:

```bash
git worktree list
# Should show only the main working tree now.
```

If any worktree has uncommitted changes and refuses removal, inspect first — it may indicate a worker's state that was never reviewed. Do not force-remove without checking.

### 2.3 Prune merged branches

```bash
skill: compound-engineering:git-clean-gone-branches
# Alternatively, direct:
git branch --merged main | grep 'feat/engage-v2/' | xargs -r git branch -d
git push origin --delete feat/engagement-layer-v2   # optional: also delete integration branch
git remote prune origin
```

Confirm:

```bash
git branch | grep engage-v2
# Should output nothing.
```

### 2.4 Tear down the team

Per `compound-engineering:orchestrating-swarms` graceful shutdown:

```javascript
// 1. Request shutdown for all teammates (if any are still alive)
for (const name of ["0.1","0.2","0.3","0.4","0.5","0.6","a1","a2","a3","b1","b2","b3","c1","c2"]) {
  Teammate({
    operation: "requestShutdown",
    target_agent_id: name,
    reason: "Engagement Layer v2 rollup complete; cleaning up team."
  })
}

// 2. Wait for shutdown_approved messages in team-lead.json
// 3. Only then:
Teammate({ operation: "cleanup" })
```

Confirm:

```bash
ls ~/.claude/teams/engage-v2-swarm/ 2>&1
# Should output: No such file or directory
```

### 2.5 Archive progress tracker

Edit `docs/plans/2026-04-18-002-engage-v2-progress.md` frontmatter:

```yaml
status: active  →  status: archived
archived_at: 2026-MM-DD
rollup_commit: <merge SHA on main>
```

Add a final entry to the Run log:

```
| <timestamp> | Rollup merged to main as <SHA>. All worktrees removed. Team torn down. Tracker archived. |
```

Commit this change on `main`:

```bash
git add docs/plans/2026-04-18-002-engage-v2-progress.md
git commit -m "chore(engage-v2): archive execution progress tracker post-rollup

Rollup PR merged as <SHA>. All 14 streams delivered. Team engage-v2-swarm
cleaned up. Per-unit worktrees and branches removed.

🤖 Generated with Claude Opus 4.7 (1M context) via [Claude Code](https://claude.com/claude-code) + Compound Engineering v2.54.1

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
"
git push origin main
```

### 2.6 Update origin plan status

```yaml
# docs/plans/2026-04-18-001-feat-engagement-layer-v2-plan.md frontmatter:
status: planned  →  status: completed
completed_at: 2026-MM-DD
```

Commit as part of the archive commit (or a follow-on commit on main):

```bash
git add docs/plans/2026-04-18-001-feat-engagement-layer-v2-plan.md
git commit -m "docs(engage-v2): mark origin plan as completed"
git push origin main
```

## Phase 3 — Production rollout handoff

At this point, code is on `main`. Production rollout follows the origin plan's *Verification Strategy & Rollout* section:

- **Tier A canary** — 1 video/day for 3 days; manual review per-video.
- **Tier A production** — full A/B vs baseline for 14 days.
- **Tier B opt-in** — 1 week via topic-flag.
- **Tier B production** — selector becomes automatic.
- **Tier C opt-in** — 2 weeks via `CINEMATIC_CHART_ENABLED=true`.
- **Tier C production** — flag removed, selector automatic.

These production gates are **out of scope for this execution plan**; they live in the origin plan and are driven by the normal deployment workflow (`cc-deploy-portainer` skill, Portainer stack update).

## Rollback (if Gate 3 passes but production surfaces issues)

If a post-merge production regression appears:

### Env-flag rollback (preferred)

Per origin plan's Rollback paths:

```bash
# On production Ubuntu host (192.168.29.237), via Portainer:
ENGAGEMENT_PHONE_HIGHLIGHT_ENABLED=false
ENGAGEMENT_WORD_CAPTIONS_ENABLED=false
ENGAGEMENT_ZOOM_PUNCH_ENABLED=false
# Or for Tier C specifically:
CINEMATIC_CHART_ENABLED=false
```

Reverts runtime behavior without code rollback. Ship a hot restart.

### Code rollback (if env flags cannot revert)

```bash
git checkout main
git revert <rollup-PR-merge-SHA> -m 1
git push origin main
# Redeploy via cc-deploy-portainer.
```

Post-revert, the `feat/engagement-layer-v2` branch can be resurrected from git history to continue fixing; worktrees would need to be re-created if restarting the run.

## Success criteria for this rollout runbook

When Phase 2 is complete:

- [ ] `git worktree list` shows only the main working tree.
- [ ] `git branch | grep engage-v2` outputs nothing.
- [ ] `~/.claude/teams/engage-v2-swarm/` does not exist.
- [ ] `docs/plans/2026-04-18-002-engage-v2-progress.md` has `status: archived`.
- [ ] `docs/plans/2026-04-18-001-feat-engagement-layer-v2-plan.md` has `status: completed`.
- [ ] Production rollout is running per the origin plan (canary started or full-enable scheduled).
