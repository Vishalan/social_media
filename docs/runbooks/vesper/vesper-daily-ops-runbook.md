---
date: 2026-04-21
topic: vesper-daily-ops
owner: vishalan
status: active
---

# Vesper Daily Operations

Day-to-day procedures for the Vesper pipeline. CommonCreed runs at
08:00, Vesper at 09:30 — this 90-min stagger (Key Decision #12) keeps
the shared GPU plane from overlapping on peak stages.

## Morning (10:00, after Vesper run completes)

1. **Check LaunchAgent exit status.**
   `tail -n 30 logs/vesper_launchd_stderr.log`. Non-empty stderr is a
   launchd-level failure (shell / python missing). A clean run prints
   only stage INFO to `logs/vesper_pipeline_<date>.log`.

2. **Confirm Postiz publish.**
   `grep "published:" logs/vesper_pipeline_$(date +%Y-%m-%d).log`.
   Each short shows a `job <uuid> published: [<postIds>]` line — three
   IDs per short (IG + YT + TT). If any short shows
   `published: []`, the publish stage deferred — see
   `vesper-rate-budget-breach.md`.

3. **Snapshot cost telemetry.**
   The analytics tracker records per-run `CostLedger.breakdown()`.
   Run `python -m analytics.tracker report --channel vesper
   --period day` and confirm each short is under the $0.75 ceiling
   (Key Decision #7 post-GPU-consolidation).

4. **Fallback rate sanity.**
   `FluxRouter.telemetry.fallback_rate()` is snapshotted alongside
   cost. If any run shows >10% fallback, tail the GPU mutex log
   (`docker compose logs commoncreed_redis | grep gpu:plane:mutex`)
   to see if chatterbox or I2V is hogging the plane — see
   `vesper-gpu-contention.md`.

## Evening (21:00, before bed)

1. **Backup present?**
   `ls -la data/backups/analytics_$(date +%Y-%m-%d)*.db` must show
   one file today, mode 0600. If missing, the 04:30 LaunchAgent job
   failed — check `logs/sqlite_backup_stderr.log`.

2. **Disk check.**
   `output/vesper/` grows ~100-200 MB/day (stills + assembled MP4s).
   Weekly rule: if `du -sh output/vesper` >2 GB, purge assets older
   than 7 days.

## Weekly (Sunday)

1. **Takedown rate.** Query `takedown_flags` in analytics for the
   past 7 days scoped to `channel_id="vesper"`. Any takedown with
   `failed_platforms != []` needs manual cleanup in that platform's
   admin UI — see `vesper-dmca-response.md`.

2. **Archetype rotation review.** `data/horror_archetypes.json`
   entries aren't drawn uniformly (subreddit hints bias selection).
   If an archetype hasn't fired in 14 days, check its guardrail-scan
   status — it may have been rejected at load. `grep "archetype .*
   rejected" logs/vesper_pipeline_*.log` surfaces these.

3. **Concurrent-run simulation** (manual, quarterly): Fire both
   pipelines within a 5-min window against a test DB. Verify the GPU
   mutex queue order holds (chatterbox → parallax → Flux → I2V per
   Key Decision #6) and neither pipeline fails the rate ledger.

## Log retention

* `logs/vesper_pipeline_*.log` — 30 days (manual purge; add to weekly
  cleanup if footprint grows).
* `logs/vesper_launchd_*.log` — overwritten each run, no rotation needed.
* `data/backups/analytics_*.db` — 30 days (daily backup script trims
  in-place).
* `data/postiz_rate_budget.jsonl` — rotated by the ledger itself
  (entries older than 1 hour drop on every read; call
  `PostizRateLedger.rotate()` weekly to reclaim disk).
