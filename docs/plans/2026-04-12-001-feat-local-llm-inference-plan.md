---
title: "feat: Local LLM inference via Ollama for scoring and ranking tasks"
type: feat
status: active
date: 2026-04-12
origin: docs/brainstorms/2026-04-12-local-llm-inference-requirements.md
---

# feat: Local LLM inference via Ollama for scoring and ranking tasks

## Overview

Replace Anthropic API calls for classification/scoring tasks with local GPU inference on the Ubuntu server's RTX 2070 Super via Ollama. Meme humor+relevance scoring (currently Haiku) and topic ranking (currently Sonnet) move to Qwen 3 8B locally. Creative writing (captions, scripts) stays on Anthropic API. Each task's model is independently configurable via `.env`, and Ollama hot-swaps models at runtime.

## Problem Frame

The sidecar makes 4+ Anthropic API calls daily for classification tasks (meme scoring 2x/day, topic ranking 1x/day) that don't require frontier-model quality. These are rubric-based classification/ranking where a local 8B model performs within 80-85% of the API. Running locally on the RTX 2070 Super eliminates per-call costs, reduces latency, and removes API dependency for non-creative work. (see origin: `docs/brainstorms/2026-04-12-local-llm-inference-requirements.md`)

## Requirements Trace

- R1. Meme scoring runs on local model via Ollama (origin R1)
- R2. Topic ranking runs on local model via Ollama (origin R2)
- R3. Local model produces valid JSON consistently (origin R3)
- R4. Automatic fallback to Anthropic API on local inference failure (origin R4)
- R5. Caption/script generation stays on Anthropic API (origin R5)
- R6. Ollama runs as a service on the Ubuntu server (origin R6)
- R7. Per-task model configurable via `.env` (origin R7, R8)

## Scope Boundaries

- Caption generation (`caption_gen.py`) — stays on Sonnet, no changes
- Video script writing (pipeline subprocess) — stays on Sonnet, no changes
- ComfyUI / image generation — separate initiative
- Fine-tuning or custom model training — out of scope
- Health ping Anthropic check — stays as-is (trivial cost)

## Context & Research

### Relevant Code and Patterns

- `sidecar/jobs/meme_flow.py:_score_candidates_batch` — direct `httpx.post` to Anthropic API, Haiku model, returns JSON array of `[humor, relevance]` pairs
- `sidecar/topic_selector.py` — uses `anthropic.Anthropic` client, Sonnet model, `_call()` helper for all LLM calls, retry-on-parse-fail pattern
- `sidecar/config.py:Settings` — env var pattern for all config, pydantic-settings
- `deploy/portainer/docker-compose.yml` — 7 services + 2 networks, Ollama would be service #8
- `sidecar/jobs/health_ping.py` — existing health ping pattern for dependency monitoring

### Institutional Learnings

- `docs/solutions/integration-issues/server-migration-synology-to-ubuntu-2026-04-11.md` — server runs Docker with NVIDIA Container Toolkit; Portainer manages the stack

## Key Technical Decisions

- **Ollama as native install, not Docker container**: Ollama needs direct GPU access. While Docker + NVIDIA Container Toolkit works, native install is simpler (one `curl` command), avoids GPU passthrough config, and Ollama already manages its own model storage. The sidecar container accesses Ollama via the host network (`http://host.docker.internal:11434` or the server LAN IP).
- **OpenAI-compatible API**: Ollama exposes `/v1/chat/completions` which matches the OpenAI SDK interface. The sidecar can use a thin wrapper that sends the same prompt shape to either Ollama or Anthropic, switching only the base URL and model name.
- **Per-task model config via env vars**: `MEME_SCORING_MODEL`, `MEME_SCORING_PROVIDER`, `TOPIC_RANKING_MODEL`, `TOPIC_RANKING_PROVIDER`. Provider is `ollama` or `anthropic`. This lets the user swap models per task without code changes.
- **Fallback strategy**: On Ollama error/timeout (connect refused, 5xx, >30s), log a warning and transparently retry against Anthropic API. No user-facing change on fallback — the pipeline completes either way.
- **JSON mode for structured output**: Ollama supports `format: "json"` which constrains output to valid JSON. Combined with explicit JSON instructions in the prompt, this ensures R3 without grammar files.

## Open Questions

### Resolved During Planning

- **Ollama Docker vs native?** → Native install. Simpler GPU access, one-command setup, Ollama manages its own model storage. Sidecar accesses via host network.
- **How does sidecar container reach Ollama on host?** → Docker `extra_hosts: ["host.docker.internal:host-gateway"]` in compose, then `http://host.docker.internal:11434`. Already a proven Docker pattern.
- **Fallback timeout?** → 30 seconds. Ollama cold-start (model loading) takes ~10-15s on first call, inference for 20 items is <5s. 30s covers both.

### Deferred to Implementation

- Exact prompt tuning for Qwen 3 8B — may need adjusted rubric wording or few-shot examples vs Claude prompts
- Whether Ollama `keep_alive` parameter should be tuned to avoid model unload between the 2 trigger runs

## Implementation Units

- [ ] **Unit 1: Install Ollama + pull Qwen 3 8B on server**

**Goal:** Ollama running on the Ubuntu server with Qwen 3 8B available for inference.

**Requirements:** R6

**Dependencies:** None

**Files:**
- Modify: server setup (SSH commands, not repo files)

**Approach:**
- Install Ollama via `curl -fsSL https://ollama.com/install.sh | sh`
- Pull model: `ollama pull qwen3:8b`
- Verify: `curl http://localhost:11434/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"qwen3:8b","messages":[{"role":"user","content":"test"}]}'`
- Enable Ollama systemd service for boot persistence

**Verification:**
- `ollama list` shows `qwen3:8b`
- API responds at `http://localhost:11434/v1/chat/completions`
- `nvidia-smi` shows Ollama process using GPU during inference

---

- [ ] **Unit 2: Add LLM provider abstraction to sidecar**

**Goal:** A thin `llm_client` module that routes LLM calls to either Ollama or Anthropic based on provider config, with automatic fallback.

**Requirements:** R4, R7

**Dependencies:** Unit 1

**Files:**
- Create: `sidecar/llm_client.py`
- Modify: `sidecar/config.py` (new env vars)
- Test: `sidecar/tests/test_llm_client.py`

**Approach:**
- New `llm_client.py` with a single entry point that accepts provider, model, prompt, and returns the response text
- Provider `ollama`: POST to Ollama's OpenAI-compatible endpoint with `format: "json"` when caller requests JSON
- Provider `anthropic`: POST to Anthropic API (existing pattern from `meme_flow.py`)
- Fallback: if primary provider fails (connection error, timeout, 5xx), retry once with the other provider. Log the fallback.
- Config env vars in `Settings`:
  - `OLLAMA_BASE_URL` (default: `http://host.docker.internal:11434`)
  - `MEME_SCORING_PROVIDER` (default: `ollama`)
  - `MEME_SCORING_MODEL` (default: `qwen3:8b`)
  - `TOPIC_RANKING_PROVIDER` (default: `ollama`)
  - `TOPIC_RANKING_MODEL` (default: `qwen3:8b`)

**Patterns to follow:**
- `sidecar/jobs/meme_flow.py:_score_candidates_batch` — existing httpx.post pattern for API calls
- `sidecar/postiz_client.py` — retry/backoff pattern

**Test scenarios:**
- Ollama provider returns valid JSON → parsed correctly
- Ollama provider times out → falls back to Anthropic, logs warning
- Anthropic provider works as before (regression)
- Invalid provider name → raises clear error

**Verification:**
- `llm_client.call(provider="ollama", model="qwen3:8b", prompt="...", json_mode=True)` returns valid JSON
- Fallback triggers on simulated Ollama failure

---

- [ ] **Unit 3: Wire meme scoring to LLM client**

**Goal:** `_score_candidates_batch` in `meme_flow.py` uses the new `llm_client` instead of direct Anthropic httpx calls.

**Requirements:** R1, R3, R4

**Dependencies:** Unit 2

**Files:**
- Modify: `sidecar/jobs/meme_flow.py`
- Test: `sidecar/tests/test_meme_flow.py` (or inline verification)

**Approach:**
- Replace the `httpx.post("https://api.anthropic.com/...")` block in `_score_candidates_batch` with a call to `llm_client.call(provider=settings.MEME_SCORING_PROVIDER, model=settings.MEME_SCORING_MODEL, ...)`
- Keep the same prompt and JSON parsing logic — only the transport layer changes
- Prompt may need minor adjustment for Qwen (add few-shot example of expected output format)

**Patterns to follow:**
- Existing `_score_candidates_batch` structure — preserve the prompt, parsing, and error handling

**Test scenarios:**
- Run meme trigger with `MEME_SCORING_PROVIDER=ollama` → candidates get humor+relevance scores
- Run with `MEME_SCORING_PROVIDER=anthropic` → works as before (regression)
- Ollama returns malformed JSON → fallback to Anthropic, candidates still scored

**Verification:**
- `run_meme_trigger()` returns candidates with `humor_score` and `relevance_score` populated
- Scores are within ±2 of Haiku scores on the same inputs

---

- [ ] **Unit 4: Wire topic ranking to LLM client**

**Goal:** `topic_selector.py` uses the new `llm_client` for its `_call()` helper, configurable per task.

**Requirements:** R2, R3, R4

**Dependencies:** Unit 2

**Files:**
- Modify: `sidecar/topic_selector.py`
- Test: `sidecar/tests/test_topic_selector.py` (or inline verification)

**Approach:**
- Modify `_call()` to accept a provider parameter and route through `llm_client`
- `extract_items()` and `score_topics()` read `TOPIC_RANKING_PROVIDER` and `TOPIC_RANKING_MODEL` from settings
- The `anthropic.Anthropic` client import becomes conditional — only used when provider is `anthropic`
- Retry-on-parse-fail logic stays in `topic_selector.py` (it's business logic, not transport)

**Patterns to follow:**
- Existing `_call()` → `resp.content[0].text` pattern for Anthropic
- New `llm_client.call()` for Ollama

**Test scenarios:**
- `score_topics()` with `TOPIC_RANKING_PROVIDER=ollama` → returns ranked topics with scores
- Same items scored by both providers → top-3 overlap at least 70%
- Ollama unavailable → fallback to Anthropic, topics still ranked

**Verification:**
- Daily trigger at 05:00 selects topics successfully with `TOPIC_RANKING_PROVIDER=ollama`

---

- [ ] **Unit 5: Docker Compose + health ping updates**

**Goal:** Sidecar container can reach Ollama on the host, and health ping monitors Ollama availability.

**Requirements:** R6, R4

**Dependencies:** Units 1-4

**Files:**
- Modify: `deploy/portainer/docker-compose.yml` (add `extra_hosts` to sidecar service)
- Modify: `sidecar/jobs/health_ping.py` (add Ollama ping)
- Modify: `deploy/portainer/.env.example` (document new env vars)

**Approach:**
- Add `extra_hosts: ["host.docker.internal:host-gateway"]` to `commoncreed_sidecar` service in compose
- Add `_ping_ollama()` to health_ping.py — simple GET to `http://host.docker.internal:11434/api/tags` (lists models)
- Add new env vars to `.env.example` with documentation comments

**Patterns to follow:**
- Existing `_ping_postiz()` pattern in `health_ping.py`

**Test scenarios:**
- Sidecar container can reach `http://host.docker.internal:11434` → Ollama responds
- Ollama is down → health ping reports it, does NOT alert on Telegram (optional dependency)

**Verification:**
- `curl http://host.docker.internal:11434/api/tags` from inside sidecar container returns model list
- Health endpoint includes Ollama status

## System-Wide Impact

- **Interaction graph:** `meme_flow.py` and `topic_selector.py` gain a new dependency on Ollama via `llm_client.py`. All other modules unchanged. Caption gen and pipeline subprocess untouched.
- **Error propagation:** Ollama failures are caught by `llm_client` and transparently retried against Anthropic. No error propagates to the scheduler or Telegram bot — the pipeline always completes.
- **State lifecycle risks:** None — LLM calls are stateless. No DB changes, no new tables.
- **API surface parity:** The sidecar REST API and Telegram bot are unaffected. Only the internal scoring/ranking logic changes transport.
- **Integration coverage:** End-to-end test = run `run_meme_trigger()` with `MEME_SCORING_PROVIDER=ollama` and verify candidates are scored.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Qwen 3 8B produces worse scores than Haiku | A/B comparison on same inputs before cutting over. Keep `PROVIDER=anthropic` as instant rollback. |
| Ollama cold-start delays first call after model eviction | Set `keep_alive: "24h"` in Ollama config to keep model resident |
| GPU VRAM contention if ComfyUI is added later | Ollama auto-unloads when VRAM is needed. Future ComfyUI work should account for model swapping latency. |
| Prompt format differences between Claude and Qwen | May need few-shot examples in prompts for Qwen. Deferred to implementation. |

## Documentation / Operational Notes

- New `.env` vars: `OLLAMA_BASE_URL`, `MEME_SCORING_PROVIDER`, `MEME_SCORING_MODEL`, `TOPIC_RANKING_PROVIDER`, `TOPIC_RANKING_MODEL`
- Rollback: set any `*_PROVIDER` back to `anthropic` in `.env` and restart sidecar
- Monitor: health ping will show Ollama status. Check `nvidia-smi` for GPU utilization.
- Model updates: `ollama pull qwen3:8b` on server to get latest quantization. No code change needed.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-12-local-llm-inference-requirements.md](docs/brainstorms/2026-04-12-local-llm-inference-requirements.md)
- Meme scoring: `sidecar/jobs/meme_flow.py:_score_candidates_batch`
- Topic ranking: `sidecar/topic_selector.py`
- Config: `sidecar/config.py:Settings`
- Docker compose: `deploy/portainer/docker-compose.yml`
- Health ping: `sidecar/jobs/health_ping.py`
