---
date: 2026-04-21
topic: vesper-dmca-response
owner: vishalan
status: active
---

# Vesper DMCA / Takedown Response

Fast path when a platform flags a Vesper short — DMCA notice, strike,
legal demand, or owner-initiated quality recall.

**Target SLA: 10 minutes from notice to all-platforms removed.**
The `/takedown` Telegram command hits that target on the happy path.
Manual follow-up is only needed when one platform's API rejects the
delete.

## The `/takedown` command (happy path)

1. **From Telegram** (owner's account, same chat as approval previews):
   ```
   /takedown <job_id> <reason>
   ```
   `<job_id>` is the UUID shown on the approval card for that short
   (scroll up in Telegram to find it). `<reason>` is a short string
   recorded in the analytics `takedown_flags` table (e.g.
   `dmca-nosleep-thread-8472`).

2. **Bot response shape.** Within 10 s the bot replies either:
   * `[Vesper] takedown OK for <job_id>: 3 post(s) removed` — done.
   * `[Vesper] takedown PARTIAL for <job_id>: deleted=[p-ig,p-yt]
      failed=[p-tt]` — see "Partial failure" below.

3. **Confirm via platform UI** for at least one platform within 30 min
   — Postiz delete acknowledgements are usually-but-not-always
   propagated immediately.

## Partial failure

A partial response means one or more `delete_post` calls raised.
Rapid-unpublish never silently claims success, so the bot replies
list exactly which post_ids survived.

1. **Pull the full reason** from `logs/vesper_pipeline_$(date +%Y-%m-%d).log`:
   `grep "rapid_unpublish" logs/vesper_pipeline_*.log | grep <job_id>`.
2. For each `post_id` in the `failed` list, log into that platform's
   admin UI and delete the video manually. Typical causes:
   * **Instagram**: post ID has aged out of Postiz's admin API
     (happens with posts >30 days old). Manual delete via app.
   * **TikTok**: rate limit on delete endpoint. Retry in 60 min:
     ```
     /takedown <job_id> <reason> retry
     ```
     (The `retry` flag is cosmetic — it just produces a fresh log
     entry tagged as a retry.)
   * **YouTube**: content-ID dispute blocks manual delete until
     resolved. Must go through YouTube's dispute flow first.

3. Update the `takedown_flags` row once all platforms are clean. SQL:
   ```sql
   UPDATE takedown_flags
   SET failed_platforms = '[]',
       resolved_at = strftime('%s','now')
   WHERE job_id = '<job_id>';
   ```

## Preventing the takedown from reaching Vesper again

If the takedown was content-based (a platform decided Vesper's story
crossed a line), block the source topic so the pipeline doesn't
regenerate a similar short:

1. Pull the source topic_title from the analytics `posts` row for
   `<job_id>`:
   ```
   sqlite3 data/analytics.db \\
     "SELECT topic_title, source_url FROM posts WHERE job_id='<job_id>'"
   ```
2. Add it to the dedup denylist:
   ```
   sqlite3 data/analytics.db \\
     "INSERT INTO news_items (channel_id, canonical_title, first_seen_at,
      denied_until) VALUES ('vesper', '<canonical>', strftime('%s','now'),
      strftime('%s','now','+365 days'))"
   ```
3. If the archetype itself is the issue, deny it in
   `data/horror_archetypes.json` by setting `"active": false` on that
   archetype's entry (guardrail-scan ignores inactive entries).

## When NOT to use `/takedown`

* **Owner rejected a preview.** The short was never published —
  nothing to take down. The orchestrator already marked the job
  failed at `request_approval`. No action.
* **Publish deferred by rate budget.** Same — the short never
  published. Next day's run will re-attempt if the topic is still
  the top candidate.
* **"I want to edit the caption."** Takedown is destructive and the
  URL is gone forever. Platforms do not re-use post URLs after
  delete. Use the platform's native edit UI instead.

## Audit

The `takedown_flags` table is append-only — every invocation of
`/takedown` leaves a row including partial-failure status. Quarterly
review: query for `reason LIKE 'dmca%'` to count platform strikes
by week; >3/week on any platform is a signal the archetype or
subreddit pool needs pruning before the channel earns a
permanent-strike tier.
