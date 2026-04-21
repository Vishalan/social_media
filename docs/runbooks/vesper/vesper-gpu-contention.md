---
date: 2026-04-21
topic: vesper-gpu-contention
owner: vishalan
status: active
---

# Vesper GPU Plane Contention

Symptom: one of these shows up in daily logs:
* `Flux local → fal.ai fallback (mutex timeout)` in `logs/vesper_pipeline_*.log`
* `FluxRouter.telemetry.fallback_rate()` >10% in the daily report
* Chatterbox TTS requests hanging past 3 min wall-clock
* Parallax stage taking 60+ seconds per beat

## Background

The Ubuntu server has ONE RTX 3090 (24 GB VRAM). Four consumers queue
on it via a Redis semaphore (`gpu:plane:mutex` — see
`scripts/video_gen/gpu_mutex.py`):

1. chatterbox TTS
2. parallax (Depth Anything V2 + DepthFlow)
3. Flux stills (local primary)
4. Wan2.2 I2V hero shots

Priority is chatterbox > parallax > Flux > I2V (plan Key Decision #6).
Per-acquisition timeout is 10 min; double-timeout degrades the stage
per `vesper-incident-response.md`.

## Triage

### 1. Is the mutex stuck with a stale token?

```bash
ssh 192.168.29.237
docker compose exec commoncreed_redis redis-cli GET gpu:plane:mutex
```

If this returns a token but no pipeline is actually running (check
`docker compose ps` — pipeline containers stopped, but token present),
the holder crashed before release. Clean it:

```bash
docker compose exec commoncreed_redis redis-cli DEL gpu:plane:mutex
```

The 15-min TTL would self-heal this eventually, but clearing now
unblocks the next queued caller.

### 2. Is a specific stage holding the plane abnormally long?

Check per-stage wall-clock in the pipeline log:

```bash
grep "gpu_mutex acquired\|gpu_mutex released" logs/vesper_pipeline_$(date +%Y-%m-%d).log
```

Each pair shows caller + held-for duration. Expected:

| Stage     | Expected held duration |
|-----------|------------------------|
| chatterbox| 90-120 s               |
| parallax  | 10-30 s per beat       |
| Flux      | 5-20 s per image       |
| I2V       | 60-120 s per clip      |

If one stage consistently exceeds its budget, that's where to dig.

### 3. Is CommonCreed on a long run?

CommonCreed uses the same plane (chatterbox on the same 3090).
`grep "gpu_mutex acquired caller=commoncreed" logs/vesper_pipeline_*.log`
shows cross-pipeline contention. Not a failure — the staggered schedule
(08:00 vs 09:30) usually prevents overlap, but CommonCreed runs long
on first-of-month batches. Expected during those windows; do not
intervene.

### 4. Is fal.ai fallback firing harmlessly?

Fallback rate <10% is fine — the router exists specifically for this.
Cost impact is bounded at ~$0.04/image × ~25 images × 10% = ~$0.10
per short. Only investigate when fallback rate climbs past 20% AND
the local GPU shows capacity (no chatterbox / I2V in flight).

## Remediation

### Short-term (today)

* If the mutex is stale → DEL it (above).
* If chatterbox is hanging → restart the chatterbox container:
  `docker compose restart chatterbox`. Any in-flight Vesper TTS call
  will fail; the orchestrator degrades that run (abort, next day's
  run re-picks the topic).
* If Flux is consistently timing out → in `.env`, temporarily flip
  `VESPER_FLUX_PREFER_LOCAL=false` to route all Flux calls to fal.ai.
  Costs $1/short for the day; buys time to fix local.

### Medium-term (this week)

* If fallback rate >20% for 3+ days running, revisit queue batching.
  Per plan Unit 11, parallax beats *should* batch into one mutex
  acquisition rather than per-beat. If they're per-beat in the
  running code, add batching before the next week's releases.
* If I2V is the bottleneck, downshift the model: Wan2.2 14B →
  5B-class or HunyuanVideo distilled per Unit 10 contingency.
  `VESPER_I2V_MODEL=<path>` env var. Smaller models are 2-3x faster.

### Long-term (v2 planning input)

If contention is a chronic problem even after queue tuning, the
right move is a second GPU host — not heavier queue logic. Document
the contention pattern in a `docs/solutions/` entry so when that
brainstorm happens, the evidence is ready.

## What NOT to do

* **Never bypass the mutex.** Setting `VESPER_GPU_MUTEX=off` in .env
  feels tempting during a contention storm but it will corrupt either
  chatterbox's output (model swap mid-request) or Flux's output
  (VRAM OOM). The fallback to fal.ai exists for exactly this case.
* **Never increase the acquire-timeout above 10 min.** Longer waits
  starve other pipelines; short-circuit to fallback is correct
  behavior.
* **Never delete the Redis mutex key while a stage is running.**
  Check `docker compose ps` first — if a pipeline container is up
  and you DEL the key, two callers will now think they have the
  plane. Chatterbox + Flux co-residency = VRAM OOM = both fail.
