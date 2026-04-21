---
date: 2026-04-21
topic: vesper-rate-budget
owner: vishalan
status: active
---

# Vesper Postiz Rate Budget Breach

Symptom: one or more Vesper shorts log
`failure_stage=publish, failure_reason=rate_budget_deferred`.
The short was approved but Postiz's org-wide 30-requests/hour
ceiling wouldn't accept another 3 calls (IG + YT + TT).

## Is this actually a breach?

Deferral is a feature, not a failure. The plan explicitly routes
"insufficient rate budget" to `approved-but-unposted` state rather
than burning the post ID on a partial publish.

* If **one** short deferred on a day both pipelines ran: normal
  collision near the top of the hour. Will publish on the next run.
  No action.
* If **multiple** shorts deferred across multiple days: something is
  eating the 30-req budget that isn't the pipeline. Investigate.

## Inspect current budget state

```bash
cd /Users/vishalan/Documents/Projects/social_media
wc -l data/postiz_rate_budget.jsonl   # rows count
python3 -c "
from sidecar.postiz_rate_ledger import PostizRateLedger
from pathlib import Path
ledger = PostizRateLedger(Path('data/postiz_rate_budget.jsonl'))
print(f'last-hour count: {ledger.count_last_hour()}')
print(f'remaining:        {ledger.remaining()}')
for ch in ['vesper', 'commoncreed']:
    print(f'  {ch}: {ledger.count_last_hour(channel_id=ch)}')
"
```

Expected on a normal day mid-morning: ≤6 calls total (2 shorts × 3
platforms each from a single pipeline; both pipelines = ≤12).

## If remaining is 0 on a fresh hour

The ledger isn't rotating. The ledger trims entries older than 1 hour
on every read, but if the file was written with a wonky timestamp,
entries can be mis-keyed as "future" and never expire.

Force a rotate + inspect:

```bash
python3 -c "
from sidecar.postiz_rate_ledger import PostizRateLedger
from pathlib import Path
ledger = PostizRateLedger(Path('data/postiz_rate_budget.jsonl'))
trimmed = ledger.rotate()
print(f'trimmed {trimmed} stale entries')
print(f'remaining: {ledger.remaining()}')
"
```

If `trimmed` is >0 and remaining jumps back up, the issue was
accumulated stale entries from a prior crash. Nothing else to do.

## If remaining is 0 AND rotate trimmed 0

Something genuinely used 30+ Postiz calls in this hour. Possibilities:

1. **Retry storm.** A failing publish keeps retrying with fresh
   `assert_available` checks. Check the pipeline log for repeated
   `Postiz 5xx` entries; if present, the Postiz server itself is
   degraded — back off for 1 hour.

2. **Manual operator post.** Someone used Postiz's UI to schedule
   posts directly. Those count against the same 30-req budget.
   Check Postiz's own admin logs.

3. **Bulk `get_account_tokens` polling.** `sidecar/postiz_client.py`
   periodically reads account tokens; normally 1 call but a loop bug
   can spam this. Tail the sidecar log:
   `docker compose logs sidecar | grep integrations | tail -20`.

4. **Another pipeline invoked outside the LaunchAgents.** Did you
   run a manual `bash deploy/run_vesper_pipeline.sh` earlier in the
   same hour? That stacks against the hourly cap too.

## Recovery path (when a short is stuck deferred)

Deferred shorts don't lose their content — the rendered MP4 and
thumbnail are still on disk under `output/vesper/assembled/` and
`output/vesper/thumbnails/`, keyed by `job_id`. Manual republish:

```bash
JOB_ID=<uuid from failure_reason>
python3 -m scripts.ops.republish_deferred --job-id $JOB_ID
# (to be added in a follow-up; for now — use Postiz UI directly
#  uploading the output/vesper/assembled/$JOB_ID.mp4 file)
```

Time-window check first — don't republish if Postiz is still budget-
exhausted; you'll just defer again. Run the inspect block at the top
of this runbook before invoking republish.

## Preventive tuning

If rate-budget deferrals happen >1/week on average, the 30/hr ceiling
is the actual bottleneck. Options (descending preference):

1. **Drop one platform.** Vesper v1 posts IG + YT + TT. If owner
   decides TikTok isn't pulling retention, drop `tt_profile` from
   the pipeline config — saves 1/3 of calls per short.

2. **Stagger morning runs further.** CommonCreed at 08:00 and
   Vesper at 09:30 already accounts for the typical 90-min tail on
   CommonCreed. If Postiz clocks run on UTC and both pipelines land
   in the same UTC hour, bump Vesper to 10:00 to cross the hour
   boundary.

3. **Request a higher Postiz tier.** Self-hosted Postiz has no
   hard cap; the 30/hr is a conservative ledger we chose. Once
   confident in the shape, raise `POSTIZ_HOURLY_LIMIT` in
   `sidecar/postiz_rate_ledger.py` (currently 30).

Option 3 changes the cap for everyone; do it only after option 1 or
2 demonstrates bottleneck isn't a bug.
