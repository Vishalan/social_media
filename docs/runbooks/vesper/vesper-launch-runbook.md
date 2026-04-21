---
date: 2026-04-21
topic: vesper-launch-runbook
owner: vishalan
status: active
---

# Vesper Launch Runbook

Pre-launch checklist. Do not post publicly until every box is checked.
Items map back to plan units + Security Posture IDs so if something
fails, you can trace it to the commit that introduced the guard.

## T-7 days — accounts & handles

- [ ] `@vesper` claimed on Instagram, YouTube, TikTok, X, Threads,
      Pinterest, Bluesky. Verify via namechk.com snapshot.
- [ ] `vesper.tv` domain registered (DNS + DNSSEC). Brand survives
      handle fallback to `@vesper.tv` if any platform squat lands.
- [ ] Postiz org has `vesper` profile wired for IG + YT + TT.
      Sanity-check with `curl -H "Authorization: $POSTIZ_API_KEY"
      $POSTIZ_URL/api/public/v1/integrations | jq '.[] | select(.profile=="vesper")'`.
- [ ] YouTube AI-disclosure default-on set on the channel page (UI).
      Belt-and-braces — the pipeline sends `containsSyntheticMedia=true`
      per-upload, but channel-level default catches accidental direct
      uploads.

## T-3 days — biometric + visual assets

- [ ] Owner records 3 candidate chatterbox reference clips (whispered
      Archivist register, 8-15 s each). Blind-rate each against 2026
      reference horror channels. Pick winner → copy into
      `assets/vesper/refs/archivist.wav` (Security Posture S3; file
      is gitignored per `.gitignore` biometric blocklist).
- [ ] Vesper SFX pack `.wav` files sourced into
      `assets/vesper/sfx/{cut,punch,reveal,tick}.wav`. Each is
      CC0-licensed + documented in the repo's per-pack README.
- [ ] CormorantGaramond-Bold font at
      `assets/fonts/CormorantGaramond-Bold.ttf`. Thumbnail compositor
      will fall back to Inter-Black if missing, but the wedge
      typography is the ID — don't launch without it.
- [ ] Vesper overlay pack (`grain.mp4`, `dust.mp4`, `flicker.mp4`,
      `fog.mp4`) in `assets/vesper/overlays/`. Pack adds the aged
      film-stock texture the plan's anti-slop mitigation mandates.

## T-1 day — infra probes

- [ ] **Chatterbox preflight** returns `{ok: true}` against the server:
      `curl $CHATTERBOX_URL/health && curl $CHATTERBOX_URL/refs/list`.
      `archivist.wav` must appear in the refs list. (Unit 8.)
- [ ] **GPU mutex** — restart Redis semaphore to clear any stale
      tokens: `docker compose exec commoncreed_redis redis-cli DEL
      gpu:plane:mutex`.
- [ ] **Postiz rate ledger** — confirm the file exists at
      `data/postiz_rate_budget.jsonl` with mode 0600:
      `stat -f "%Lp" data/postiz_rate_budget.jsonl` → `600`.
      (Security Posture S7 / Unit 12.)
- [ ] **C2PA POC** — run `python -m still_gen.c2pa_poc` and verify
      the report recommendation is `pass` or `re_sign`. If it's
      `manual_only`, document that IG AI-label must be set via
      the Instagram UI post-upload.
- [ ] **SQLite backup** — manually trigger the backup job:
      `cd scripts && python -m ops.daily_sqlite_backup --verbose`.
      Confirm `data/backups/analytics_*.db` lands and is mode 0600.

## T-0 — dry-run + enable LaunchAgent

- [ ] Dry-run one full short: set `MAX_SHORTS_PER_RUN=1` in
      `.env`, run `bash deploy/run_vesper_pipeline.sh` manually.
      Owner approves the preview via Telegram; Postiz confirms
      publish across all three platforms; analytics records the
      post with `channel_id="vesper"`.
- [ ] Load the LaunchAgents:
      `launchctl load -w ~/Library/LaunchAgents/com.vesper.pipeline.plist`
      `launchctl load -w ~/Library/LaunchAgents/com.vesper.sqlite_backup.plist`
- [ ] Confirm schedule is registered:
      `launchctl list | grep com.vesper`
- [ ] First 3 live posts: monitor YouTube monetization status
      within 24 h. Limited-ads >10% across three posts → pause
      LaunchAgent and review titles + thumbnails before resuming
      (per plan Key Decision #15 variance clause).

## Rollback

Disable the LaunchAgent:
`launchctl unload ~/Library/LaunchAgents/com.vesper.pipeline.plist`.
In-flight shorts already approved in Telegram will still publish
when their Postiz schedule fires — use `/takedown <job_id>` to pull
them (see `vesper-dmca-response.md`).
