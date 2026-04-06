---
date: 2026-04-06
topic: end-to-end-pipeline
---

# End-to-End Self-Hosted CommonCreed Pipeline

## Problem Frame

CommonCreed's video pipeline is running locally as a one-off smoke script. To reach the $5K/month revenue target it has to run unattended every day — scanning incoming newsletters, picking the best topics, generating videos, pushing them through the Telegram review loop, and posting to IG/YouTube from multiple collaborating accounts. The owner has a Synology DS1520+ with Portainer at home and no public IP; the whole system needs to live there, be approachable from LAN (+ optional VPN), and keep the owner in control without demanding daily attention.

## Requirements

- R1. **Self-hosted pipeline stack** runs on the Synology DS1520+ via Portainer using standard Docker Compose. The containerized stack must be portable — able to run on any Docker host (Mac, VPS, cloud) without modification.
- R2. **Daily Gmail trigger** scans `reachcommoncreed@gmail.com` each morning at 05:00 local time for the most recent TLDR AI newsletter from `dan@tldrnewsletter.com` received in the last 24 hours. Because TLDR AI arrives in the evening (~18:57), "the most recent newsletter" for any given morning run is the one that arrived the **previous evening**. If no newsletter is found within the last 24 hours, the sidecar retries hourly until noon and then notifies via Telegram that the day's pipeline is skipped.
- R3. **LLM-scored topic selection** reads the day's TLDR AI email and uses Claude Sonnet to score each item on virality, relevance to AI & tech news, and thought-provocation. Selects the top 2 items as the day's posts.
- R4. **Automated video generation** runs the existing pipeline (script → thumbnail → voice → avatar → b-roll → captions → assemble) for each selected topic. Produces final 1080×1920 MP4 + thumbnail PNG per video.
- R5. **2 posts per day, fixed slots**: 09:00 and 19:00 local time. A single pipeline run at 05:00 produces **both** videos from the previous evening's TLDR AI newsletter, giving the owner 4+ hours of review time before the 09:00 slot and 14+ hours before the 19:00 slot.
- R6. **Telegram approval loop**: When each video is ready, the bot sends the thumbnail, a ~10-second MP4 preview, the headline, and the caption to the owner. Approve, Reject, and Reschedule are inline-button actions handled directly in the chat. Edit Caption uses Telegram's force-reply flow — the bot prompts "Reply to this message with the new caption" and the owner types a reply. No dashboard trip required for routine approvals.
- R7. **Auto-approve with timeout**: If the owner has not acted on a pending video by T-30 minutes before its scheduled post slot, the system auto-publishes it. The timeout and fallback behavior are configurable per post type in the dashboard.
- R8. **Admin dashboard = extended Postiz** running on the Synology. Postiz handles all social posting, scheduling, account management, and media library natively. A small CommonCreed sidecar adds: pipeline run history, approval queue status, Gmail trigger logs, and a Settings page for API keys and configuration. LAN-only by default; Postiz's built-in auth gates it.
- R9. **Secrets editable from the dashboard**: All API keys, tokens, and runtime configuration (Anthropic, ElevenLabs, VEED/fal.ai, Pexels, Gmail credentials, Postiz API key, Telegram bot token, schedule times, cutoff durations, retention policy) can be viewed and edited from the dashboard. Changes take effect on the next pipeline run; service restarts happen automatically if required.
- R10. **Caption + hashtag engine**: For each generated video, an LLM call produces a platform-aware caption (IG ~125 chars, YT Shorts title + description) with 5-10 relevant hashtags. The caption is shown in the Telegram approval preview and can be edited inline before posting.
- R11. **Instagram multi-account posting**: Primary account is `@commoncreed`; `@vishalan.ai` is added as a collaborator via Instagram's native Collab API so the post appears on both feeds and both sets of followers see it. If Postiz does not expose the Collab tag field in its API, the sidecar falls back to calling the Instagram Graph API directly using the OAuth tokens already stored in Postiz for the `@commoncreed` account — R11 must ship regardless of Postiz's field coverage.
- R12. **YouTube multi-account posting**: Primary channel is `@common_creed`; `@vishalangharat` is credited in the description and pinned comment (YouTube has no native collab primitive, so credit + cross-promotion is the substitute).
- R13. **Telegram notification pipeline preserved**: All existing notifications (errors, cost reports, pipeline health) continue. New notifications (approval previews, auto-publish events, post success/failure) integrate cleanly with the existing bot.
- R14. **Pipeline run history and observability**: The dashboard shows the last N pipeline runs with status (success/failure/approved/rejected/auto-published), timestamps, cost breakdown, and links to the generated video + thumbnail. Errors surface in Telegram AND the dashboard.
- R15. **Failure isolation**: If any step fails for a given video, the pipeline must continue with the other video of the day, notify via Telegram with the error context, and mark the failed run clearly in the dashboard. A failed video never blocks a successful one from publishing.

## Success Criteria

- The owner goes 7 consecutive days without touching the pipeline manually, and videos still post twice daily from both collaborating accounts
- Approval via Telegram inline button takes under 30 seconds per video
- The stack restarts cleanly after a NAS reboot with zero manual intervention
- New API keys can be rotated via the dashboard without editing files or restarting Portainer stacks manually
- End-to-end per-video runtime on the DS1520+ stays under 8 minutes so both videos finish before the review cutoff
- Cost per video remains within the current ~$1.88 budget
- Zero duplicate posts and zero missed days across a 30-day rolling window

## Scope Boundaries

- NOT building a custom admin UI from scratch — Postiz + a small sidecar is the dashboard
- NOT running video generation on cloud GPU — CPU on the NAS is the default; moving to Mac/cloud is a deferred fallback
- NOT replacing the existing video pipeline code — this work wraps and schedules it
- NOT building public internet exposure for the dashboard — LAN-only by default; Tailscale is the optional path for remote access, out of scope for the initial build
- NOT adding AI-optimized dynamic scheduling — fixed 09:00 / 19:00 slots only
- NOT building analytics/feedback loops yet — engagement-driven scheduling and content optimization are future work
- NOT supporting additional newsletters beyond TLDR AI in this phase
- NOT supporting platforms beyond IG and YouTube in this phase (TikTok, X, LinkedIn deferred)
- NOT replacing the Telegram bot — extending the existing notification pipeline

## Key Decisions

- **Dashboard = Postiz + sidecar**: Postiz is already the posting layer; extending it instead of building a custom dashboard cuts the build scope roughly in half. The sidecar is small and owns only CommonCreed-specific concerns.
- **Everything on DS1520+**: The NAS can handle sequential video generation (~3-5 min/video) for 2 videos/day comfortably. Memory is tight (8 GB) so jobs run strictly sequentially with Docker memory limits. Portable Docker Compose means moving to Mac or VPS later is a one-command migration.
- **Auto-approve with T-30 cutoff**: Biases toward publication so a missed day never happens. The owner is the exception handler, not the gatekeeper.
- **Fixed slots, no dynamic scheduling**: 09:00 + 19:00 cover morning commute and evening scroll peaks. Simpler to reason about, easier to debug, and AI-optimized timing is premature until engagement data exists.
- **LLM topic selection over keyword filtering**: TLDR AI newsletters have enough noise that a keyword filter routinely misses the most thought-provoking story. Sonnet is cheap enough per run (~$0.01) that the quality improvement is worth it.
- **LAN-only with Postiz auth**: Simplest possible security model for a single-user home setup. Tailscale is a one-command add-on later if remote access becomes important — no architecture changes needed.
- **IG Collab API for Instagram, credit-only for YouTube**: Match each platform's real primitives rather than forcing symmetry.
- **Sidecar talks to Postiz via its public REST API**: Keeps Postiz upgradeable and the CommonCreed code decoupled from Postiz internals.
- **Secrets in Portainer env vars, editable via sidecar UI**: Portable, standard, and no new infra. A Settings page in the sidecar reads/writes the stack env and triggers a service restart via Docker API when a restart is needed.

## Dependencies / Assumptions

- Postiz runs cleanly on DS1520+ (Postiz + Postgres + Redis, ~1.5 GB RAM baseline — fits within 8 GB)
- Postiz supports Instagram Collab via the IG Graph API, Postiz API exposes the collab tag field (verify at planning time)
- `reachcommoncreed@gmail.com` uses Gmail, and an app password or OAuth token can be provisioned for pull-based read access
- TLDR AI newsletters continue to arrive daily from `dan@tldrnewsletter.com` — if format or sender changes, topic extraction breaks
- Playwright Chromium runs on x86_64 Docker on Synology (verified feasible in planning)
- The existing Telegram bot infrastructure is extensible to handle inline-button callbacks
- The owner has `@commoncreed` and `@vishalan.ai` IG business accounts linked to a FB page (required for Graph API access) and `@common_creed` + `@vishalangharat` YouTube channels with API access enabled
- **Sidecar privilege surface**: The sidecar container mounts the Docker socket and the stack `.env` file read-write, giving it privileged access to the host (effectively root via Docker socket). This is acceptable because the deployment is LAN-only and single-user. Any future public exposure (Cloudflare Tunnel, port forward, ngrok) must re-evaluate this trust boundary and likely move secrets behind a proper secrets manager and restarts behind a narrow signing endpoint.

## Outstanding Questions

### Deferred to Planning

- [Affects R1][Technical] Exact Docker Compose stack layout — one stack per service (Postiz, sidecar, worker, postgres, redis) vs one combined stack. Resource limits and restart policies per service.
- [Affects R2][Technical] Gmail access method — app password + IMAP vs Gmail API + OAuth. App password is simpler but deprecated for new accounts; Gmail API is more work but more durable.
- [Affects R2][Needs research] What's the best cron/scheduler — Portainer's built-in, a lightweight scheduler like Ofelia, or Postiz's native scheduling where applicable.
- [Affects R3][Technical] Sonnet prompt shape for topic scoring and the JSON output schema the sidecar consumes.
- [Affects R4][Technical] How the sidecar invokes the video pipeline — direct Python subprocess in the worker container, or a job queue (Redis + RQ / Celery) for future parallelism.
- [Affects R6][Technical] Telegram bot framework — extend the existing integration or add `python-telegram-bot` for the inline-button callbacks.
- [Affects R8][Needs research] Verify Postiz's plugin/extension mechanism — can the sidecar embed CommonCreed views inside Postiz's UI, or does it need to be a separate web app served on a different port?
- [Affects R9][Technical] How "restart service" works from the sidecar — Docker socket mounted into the sidecar, or a companion agent that restarts services on a signal.
- [Affects R11][Needs research] Verify Postiz IG Collab tagging — the API field name and whether the target account must approve the collab invite before posting.
- [Affects R15][Technical] Retention policy — how many days of generated video assets to keep on the NAS, and where to store cold archives if anything.
- [Affects Dependencies][Operational] Confirm DS1520+ RAM is the stock 8 GB or upgraded; if 16 GB is available, memory pressure concerns drop significantly.
- [Affects R10][Technical] Platform-specific caption length limits and hashtag placement rules — one caption-gen prompt per platform vs a single prompt with variants.

## Next Steps

→ `/ce:plan` for structured implementation planning
