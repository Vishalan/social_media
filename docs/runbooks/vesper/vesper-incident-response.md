---
date: 2026-04-21
topic: vesper-incident-response
owner: vishalan
status: active
---

# Vesper Incident Response

Failure-mode playbook. Match the symptom, follow the branch, don't
improvise the first time — each branch is shaped by a concrete
failure mode documented in plan System-Wide Impact or Risks.

## Triage decision tree

```
Vesper run ended with failures? ──────►
  │
  ├── chatterbox sidecar_down (RuntimeError raised)
  │     → see "Sidecar down (both pipelines)" below
  │
  ├── chatterbox ref_missing (Vesper only failed at voice_preflight)
  │     → see "Vesper ref missing"
  │
  ├── Flux fallback rate >10%
  │     → see vesper-gpu-contention.md
  │
  ├── Postiz rate budget deferred (failure_reason contains "rate_budget_deferred")
  │     → see vesper-rate-budget-breach.md
  │
  ├── Owner rejected short (failure_stage=request_approval, failure_reason="owner rejected")
  │     → NOT an incident — normal mod flow. Nothing to do.
  │
  ├── Cost ledger over ceiling (failure_stage=assemble_video)
  │     → see "Cost ceiling breach"
  │
  └── Unknown stage failure
        → see "Unknown failure" at bottom
```

## Sidecar down (both pipelines)

**Symptom.** Pipeline logs show:
`RuntimeError: chatterbox sidecar unreachable — aborting run`.
Both CommonCreed and Vesper fail this morning.

**Response.**
1. SSH to Ubuntu server: `ssh 192.168.29.237`.
2. Inspect chatterbox container:
   `docker compose -f deploy/portainer/docker-compose.yml ps chatterbox`.
3. If stopped:
   `docker compose -f deploy/portainer/docker-compose.yml restart chatterbox`.
   Wait 30 s then curl `/health`.
4. If container runs but health fails, check GPU state:
   `nvidia-smi` on the server. If another process is pinning the GPU,
   `docker compose restart chatterbox` again after killing the
   offender.
5. If the GPU is the problem, re-read the `vesper-gpu-contention.md`
   runbook.
6. Once healthy, re-trigger today's runs manually:
   `bash deploy/run_pipeline.sh` then `bash deploy/run_vesper_pipeline.sh`.

## Vesper ref missing

**Symptom.** Only Vesper fails — CommonCreed ran fine. Vesper log:
`stage=voice_preflight reason=chatterbox preflight failed: state=ref_missing`.

**Cause.** `assets/vesper/refs/archivist.wav` isn't mounted into the
chatterbox container, was deleted, or the bind-mount path broke after
a compose restart.

**Response.**
1. On the server:
   `docker compose exec chatterbox ls /app/refs/` — should list
   `archivist.wav`. If missing:
2. Confirm the volume bind in `deploy/portainer/docker-compose.yml`
   line ~XX points to `/home/vishalan/social_media/assets/vesper/refs`.
3. Re-copy the clip into the mount directory on the host. Confirm
   mode 0600 + correct owner.
4. Restart chatterbox: `docker compose restart chatterbox`.
5. Re-trigger Vesper run; CommonCreed is unaffected and doesn't need
   re-running.

## Cost ceiling breach

**Symptom.** Pipeline log:
`stage=assemble_video reason=cost ledger over ceiling 0.75 before
assembly (accumulated 0.XX)`.

**Cause.** Something pushed LLM + Flux fallback costs above the
per-short ceiling. This should be rare post-GPU-consolidation — most
likely cause is Flux fallback >50% (local GPU pegged + fal.ai picking
up every image at $0.04/MP).

**Response.**
1. `grep "flux fallback" logs/vesper_pipeline_$(date +%Y-%m-%d).log`
   — count fallback invocations.
2. If fallback is the culprit: inspect the GPU mutex — was chatterbox
   holding it abnormally long? `docker compose logs chatterbox | tail`
   shows per-request durations. Expected is 90-120 s per short.
3. If it's a retry storm (same LLM call fired repeatedly): check for
   shape-retry loops in `archivist_writer` or `timeline_planner` logs.
   `grep "retry=" logs/vesper_pipeline_*.log`.
4. If infrastructure is healthy and the ceiling is legitimately too
   tight, tune `VesperPipelineConfig.cost_ceiling_usd` up (via env or
   config file) **for the next run** — do not rerun today's failures
   over-budget.

## Unknown failure

**Symptom.** A job has `failure_stage` / `failure_reason` set but
doesn't match any branch above.

**Response.**
1. Grab the `failure_reason` — it's a human string.
2. `grep -A 10 "$JOB_ID" logs/vesper_pipeline_$(date +%Y-%m-%d).log`
   gives full context around the failure.
3. If the failure looks one-off (network blip, transient API error),
   re-queue the topic manually the next day by setting
   `VESPER_FORCE_TOPIC="<topic_title>"` env and running the pipeline.
4. If the failure repeats across runs, open a `docs/solutions/`
   entry and escalate to the plan — a repeating failure is evidence
   the orchestrator's error handling missed a case.

## SQLite corruption / lost analytics

**Symptom.** `sqlite3.DatabaseError` on any AnalyticsTracker call.

**Response.**
1. Stop both LaunchAgents immediately:
   `launchctl unload ~/Library/LaunchAgents/com.vesper.pipeline.plist`
   `launchctl unload ~/Library/LaunchAgents/com.commoncreed.pipeline.plist`
2. Move the live DB aside:
   `mv data/analytics.db data/analytics.db.corrupt-$(date +%s)`
3. Restore from the most recent clean backup:
   `cp data/backups/analytics_<latest>.db data/analytics.db && chmod 0600 data/analytics.db`
4. Rebuild the WAL sidecar files by opening a connection:
   `python3 -c "import sqlite3; sqlite3.connect('data/analytics.db').execute('PRAGMA integrity_check').fetchall()"`.
   Expected output: `('ok',)`.
5. Re-enable LaunchAgents.
6. Posts that published during the corrupt window are still live;
   their post_ids aren't in the DB until the next manual
   reconciliation — see the "Post-reconciliation" block below.

### Post-reconciliation (when restoring loses some logged posts)

The Postiz platform side is authoritative. Query Postiz:
`curl -H "Authorization: $POSTIZ_API_KEY" $POSTIZ_URL/api/public/v1/posts?profile=vesper&after=<cutoff>`
and insert any missing rows into `posts` manually. Skipping this
means future cost reports under-report that day's spend; it does NOT
affect future publishing.
