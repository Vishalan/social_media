# feat: Vesper horror channel v1 (13 units, 209 tests)

## Summary

Ships Vesper as CommonCreed's sibling channel per `docs/plans/2026-04-21-001-feat-vesper-horror-channel-plan.md`. 13 implementation units across channel-profile scaffold, analytics migration, engage-v2 parameterization, topic signal, Archivist writer, chatterbox preflight, Flux + anti-slop timeline, server GPU mutex, local Flux + fal.ai fallback, orchestrator, timeline planner, `/takedown` command, Postiz TikTok+AI-disclosure+rate-ledger, and ops.

- **209 unit tests green** across `scripts/` (`python3 -m unittest discover -s scripts -p 'test_*.py'`).
- **Plan posture**: shorts-first (longs gated on retention), research-pivot to Reddit-signal-only (no Reddit content ingestion), thin channel-profile factory (no multi-tenant framework until channel #3), all GPU workflow on the server 3090 (flipped from fal.ai primary mid-PR after user correction).

## What's in vs what's deferred

| Shipped in this PR | Deferred (hardware-side) |
|---|---|
| Channel profile + CPM rates + SFX pack registration | ComfyUI `flux_still.json` workflow on the server |
| AnalyticsTracker `channel_id` migration + Phase-A shim | Wan2.2-class I2V benchmark + ComfyUI workflow |
| Postiz TikTok routing + AI-disclosure + rate ledger + `delete_post` | Parallax ComfyUI wrapper (DepthAnythingV2+DepthFlow) |
| Archivist writer + prompt-injection guardrail + mod filter | Archivist voice reference recording (`archivist.wav`) |
| Chatterbox preflight + `/refs/list` endpoint | Vesper SFX pack `.wav` sourcing |
| Flux client (fal.ai) + LocalFluxClient + flux_router | `assembler` + `thumbnails` Protocol adapters |
| GPU mutex (Redis semaphore, FakeBackend-testable) | |
| Anti-slop timeline lint | |
| Timeline planner (Haiku/Sonnet) + orchestrator wiring | |
| `/takedown` rapid-unpublish (owner-gated) | |
| LaunchAgent + daily SQLite backup + 5 runbooks | |

The deferred items have `_NotYetWired*` stubs in `scripts/vesper_pipeline/__main__.py` that raise `NotImplementedError` at the exact stage boundary — first real run fails loudly with a specific message rather than silently producing a broken short.

## Key architectural decisions

1. **Sibling pipelines, not inheritance.** `scripts/vesper_pipeline/` is a package alongside `commoncreed_pipeline.py`. Shared primitives (channel profile, analytics, Postiz client, chatterbox) are imported; no base class.
2. **GPU plane is a quad-consumer queue** (chatterbox → parallax → Flux → I2V) on the server 3090. Redis semaphore coordinates; per-acquisition timeout 10 min; double-timeout degrades the stage (Flux → fal.ai fallback, I2V → still_parallax).
3. **Local Flux primary, fal.ai fallback.** `flux_router` tries local first, routes to fal.ai on `GpuMutexAcquireTimeout` or ComfyUI error. Telemetry counts fallback rate — >10% triggers ops attention.
4. **Protocol-driven orchestrator.** Every collaborator is a `Protocol`; `scripts/vesper_pipeline/__main__.py` wires concretes from env. Tests inject fakes for hermetic runs.
5. **Cost ledger gates two decisions.** Skip I2V when adding it would breach the ceiling; abort before MoviePy assembly when already over. Default $0.75 (post-GPU-consolidation).
6. **Per-job UUID in Telegram callback_data.** Stray callbacks from other channels' concurrent previews are discarded (System-Wide Impact #3).

## Testing

- 209 unit tests green — 0 new test failures, 0 pre-existing green tests broken.
- Hermetic — no real network, no GPU, no LLM. Stubbed collaborators everywhere the orchestrator takes a Protocol.
- Integration tests intentionally out of scope here: live `c2patool` POC, real ComfyUI run, real Postiz delete round-trip. Runbook at `docs/runbooks/vesper/vesper-launch-runbook.md` covers manual pre-launch verification.

## Post-Deploy Monitoring & Validation

- **What to monitor/search**
  - Logs: `logs/vesper_pipeline_<date>.log` (per-day), `logs/vesper_launchd_stderr.log` (launchd-level), `logs/sqlite_backup_stderr.log`.
  - Counters: `FluxRouter.telemetry.fallback_rate()` (should stay <10%), Postiz rate ledger count per hour (should stay ≤12 on a two-pipeline day), per-short `CostLedger.total()` (should stay ≤$0.75).
- **Validation checks**
  - First live run dry-run: `VESPER_MAX_SHORTS_PER_RUN=1 bash deploy/run_vesper_pipeline.sh` and verify the approval card in Telegram + three `postIds` returned + analytics row with `channel_id="vesper"`.
  - GPU mutex clean state: `docker compose exec commoncreed_redis redis-cli GET gpu:plane:mutex` should be nil between runs.
  - Backup present: `ls -la data/backups/analytics_$(date +%Y-%m-%d)*.db` — exactly one file, mode 0600.
  - C2PA POC: `python -m still_gen.c2pa_poc` — recommendation `pass` or `re_sign`.
- **Expected healthy behavior**
  - ≤2 shorts/day published with 3 `postIds` each (IG + YT + TT).
  - Per-short wall-clock <8 min end-to-end (approval included).
  - Fallback rate <10%, cost <$0.75.
- **Failure signal(s) / rollback trigger**
  - Fallback rate >20% for 3+ days → `docs/runbooks/vesper/vesper-gpu-contention.md`.
  - Limited-ads >10% across first 3 posts → pause LaunchAgent + review per Key Decision #15.
  - `rate_budget_deferred` failures on multiple days → `docs/runbooks/vesper/vesper-rate-budget-breach.md`.
  - Any `RuntimeError: chatterbox sidecar unreachable` → both pipelines down; `docs/runbooks/vesper/vesper-incident-response.md`.
  - Rollback: `launchctl unload ~/Library/LaunchAgents/com.vesper.pipeline.plist`; CommonCreed keeps running unaffected.
- **Validation window & owner**
  - Window: first 10 published shorts (≈5 days at 2/day).
  - Owner: @vishalan.

## Figma Design

N/A — faceless channel; thumbnail palette defined in `channels/vesper.py::PALETTE` (near-black / bone / oxidized blood / graphite per memory `project_vesper_brand_palette.md`).

---

[![Compound Engineering v2.54.1](https://img.shields.io/badge/Compound_Engineering-v2.54.1-6366f1)](https://github.com/EveryInc/compound-engineering-plugin)
🤖 Generated with Claude Opus 4.7 (1M context, extended thinking) via [Claude Code](https://claude.com/claude-code)
