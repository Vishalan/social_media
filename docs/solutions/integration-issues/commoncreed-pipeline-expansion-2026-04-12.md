---
title: "CommonCreed pipeline expansion: local LLM, video memes, meme sources, Postiz media fix"
date: 2026-04-12
category: integration-issues
module: sidecar-pipeline
problem_type: integration_issue
component: tooling
symptoms:
  - "Meme scoring relied entirely on paid Anthropic API calls"
  - "Zero video content from tech-only Reddit subreddits"
  - "Postiz Instagram/YouTube publish failing with ETIMEDOUT on Tailscale IP from Docker"
  - "Gmail health ping spamming Telegram hourly with 'service unreachable'"
root_cause: incomplete_setup
resolution_type: environment_setup
severity: high
tags:
  - ollama
  - local-llm
  - meme-sources
  - video-curation
  - postiz
  - tailscale
  - docker-networking
---

# CommonCreed pipeline expansion: local LLM, video memes, meme sources, Postiz media fix

## Problem

Multiple pipeline gaps after server migration: (1) all LLM scoring calls went to paid Anthropic API, (2) meme sources were mostly off-brand general viral content with no video, (3) Postiz couldn't publish to Instagram/YouTube because Docker containers couldn't reach media files via the Tailscale Funnel URL, (4) Gmail health ping called a nonexistent `get_profile()` method.

## Symptoms

- Anthropic API costs for every meme trigger (2x/day, 20+ candidates each)
- Only 2 video candidates per trigger run from general subs that got 80%+ filtered
- Postiz errors: `connect ETIMEDOUT 100.72.251.52:443` and `Media fetch failed`
- Telegram spam: "service gmail unreachable (last_success: never)" every hour

## Solution

### 1. Local LLM via Ollama (Qwen 3 8B)

Created `sidecar/llm_client.py` — thin provider abstraction routing calls to Ollama or Anthropic with automatic fallback. Meme humor+relevance scoring now runs on local Qwen 3 8B via Ollama. Per-task provider/model configurable via `.env` (`MEME_SCORING_PROVIDER`, `MEME_SCORING_MODEL`, `OLLAMA_BASE_URL`).

Key finding: Qwen 3's `/no_think` prefix needed to disable chain-of-thought for direct JSON output. Also `json_mode=False` required for batch scoring (Qwen produces malformed JSON with `format: "json"` on 20+ items).

### 2. Meme source expansion

Replaced 3 off-brand subs (r/Unexpected, r/BetterEveryLoop, r/nextfuckinglevel) with 10 on-brand tech subs: r/linuxmemes, r/SoftwareGore, r/iiiiiiitttttttttttt, r/ProgrammingHorror, r/RecruitingHell, r/shittyrobots, r/arduino, r/robotics, r/3Dprinting, r/pcmasterrace. Added Mastodon as new source (fosstodon.org + hachyderm.io, `#programmerhumor` `#devhumor` `#techmemes`).

Switched Reddit scraper from `httpx` to `requests` — Reddit returns 403 to httpx's TLS fingerprint from Docker containers. Added 2s delay between source fetches to avoid rate limiting across 12 subs. Lowered `REDDIT_MEME_MIN_SCORE` from 500 to 100 for niche subs where video content has lower engagement.

Added content-level dedup: Jaccard title similarity (≥0.8) within 7-day lookback prevents same meme reposted by different users or across subreddits.

### 3. Postiz Docker↔Tailscale media fix

Root cause: Postiz stores media URLs with `MAIN_URL` prefix (`https://commoncreed-server.tail47ec78.ts.net`). The orchestrator inside Docker tries to fetch these URLs but can't reach the Tailscale interface. Instagram Graph API also needs to fetch from a public URL.

Fix: host nginx reverse proxy on Docker bridge IPs (172.17.0.1, 172.19.0.1) port 443 with self-signed TLS → proxies to localhost:5000 (Postiz nginx). Postiz container gets `extra_hosts: commoncreed-server.tail47ec78.ts.net:host-gateway` + `NODE_TLS_REJECT_UNAUTHORIZED=0`. External traffic (Meta/Google) still reaches via Tailscale Funnel.

### 4. Gmail health ping fix

`GmailClient` had no `get_profile()` method. Changed health ping to check `client._service is not None` (validates credentials without API call).

## Why This Works

- Ollama provides OpenAI-compatible API locally, Qwen 3 8B fits in 5.5 GB VRAM leaving room for other GPU workloads
- On-brand subreddits + video-heavy maker subs (shittyrobots, arduino, robotics) yield 7+ videos per trigger vs 0-2 before
- Host nginx bridges the Docker↔Tailscale gap without modifying the Postiz container image
- Fallback to Anthropic API ensures pipeline never fails even if Ollama is down

## Prevention

- When adding Docker services that need to reach Tailscale endpoints, use `extra_hosts` + host nginx proxy pattern
- Use `requests` not `httpx` for Reddit scraping from Docker (TLS fingerprint issue)
- Test LLM JSON output with real batch sizes before deploying — small test batches may work but 20+ items can break `json_mode`
- Always check if methods exist before calling them in health checks

## Related Issues

- Server migration: `docs/solutions/integration-issues/server-migration-synology-to-ubuntu-2026-04-11.md`
- Plan: `docs/plans/2026-04-12-001-feat-local-llm-inference-plan.md`
- Plan: `docs/plans/2026-04-13-001-feat-meme-sources-expansion-plan.md`
- Brainstorm: `docs/brainstorms/2026-04-15-local-avatar-generation-requirements.md`
