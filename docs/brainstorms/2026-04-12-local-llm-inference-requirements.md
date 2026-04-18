---
date: 2026-04-12
topic: local-llm-inference
---

# Local LLM Inference — Replace API Calls with On-Server GPU Inference

## Problem Frame

The CommonCreed pipeline makes multiple Anthropic API calls daily for classification/scoring tasks (meme humor+relevance rating, topic ranking). These tasks don't require frontier-model quality — they're rubric-based classification where an 8B open model performs within 80-85% of the API. Running them locally on the RTX 2070 Super (8GB VRAM) eliminates per-call costs, reduces latency, and removes API dependency for non-creative tasks.

## Requirements

- R1. Meme humor + relevance scoring (`meme_flow.py:_score_candidates_batch`) runs on a local model via Ollama instead of Claude Haiku API
- R2. Topic ranking/selection (`topic_selector.py`) runs on a local model instead of Claude Sonnet API
- R3. Local model produces valid JSON arrays consistently (constrained decoding)
- R4. Fallback to Anthropic API if local inference fails (Ollama down, OOM, timeout)
- R5. Caption generation and video script writing remain on Claude Sonnet API (audience-facing creative quality)
- R6. Ollama runs as a Docker container on the Ubuntu server alongside the existing stack
- R7. Model selection configurable per-task via `.env` (e.g., `MEME_SCORING_MODEL=qwen3:8b`, `TOPIC_RANKING_MODEL=qwen3:8b`) — Ollama hot-swaps models at runtime, so different tasks can use different models without restart
- R8. Adding new models is a single `ollama pull <model>` + `.env` change — no code changes required

## Success Criteria

- Meme scoring produces humor+relevance scores within ±2 points of Haiku on the same inputs
- Topic ranking selects the same top-3 topics as Sonnet at least 70% of the time
- Zero increase in pipeline failures from local inference issues (fallback catches failures)
- Anthropic API spend drops by 60%+ for classification/scoring calls

## Scope Boundaries

- **In scope:** Ollama setup, model deployment, sidecar integration for scoring + ranking, fallback logic
- **Out of scope:** Caption generation — stays on Sonnet
- **Out of scope:** Video script writing — stays on Sonnet
- **Out of scope:** ComfyUI / image generation / avatar pipeline — separate initiative
- **Out of scope:** Fine-tuning or training custom models

## Key Decisions

- **Model: Qwen 3 8B (Q4_K_M)** — Best all-around for classification at this VRAM budget. Strong JSON output, good general reasoning, 4.6 GB VRAM leaves room for KV cache. Gemma 4 E4B is a secondary option.
- **Inference server: Ollama** — One-command setup, OpenAI-compatible API, handles model loading/unloading, JSON mode built-in. No need for vLLM/TGI overhead on a single-GPU server.
- **Quantization: Q4_K_M** — Consensus sweet spot: 95-99% quality retention, ~50% VRAM of FP16.
- **Fallback strategy: automatic** — If Ollama returns error/timeout, retry once, then fall back to Anthropic API transparently. Log the fallback for monitoring.
- **Runtime model swapping** — Ollama loads/unloads models on demand per request. The sidecar sends `model: "qwen3:8b"` for scoring and could send `model: "gemma4:e4b"` for a different task in the next request — no restart needed. This makes the system future-proof: pull a new model, update one `.env` var, done.
- **Creative tasks stay on API** — Local 8B models operate at 65-75% of Sonnet quality for creative writing. Not acceptable for audience-facing content.

## Dependencies / Assumptions

- Ubuntu server has NVIDIA Container Toolkit already installed (confirmed)
- Ollama GPU container can coexist with the existing 7-container stack (RTX 2070 Super has enough VRAM headroom since no other container uses GPU)
- Server has stable internet for initial model download (~5 GB for Qwen 3 8B Q4)

## Outstanding Questions

### Deferred to Planning

- [Affects R1, R2][Technical] Exact prompt engineering for Qwen 3 8B — may need different system prompts vs Claude (rubric-based, few-shot examples)
- [Affects R6][Technical] Whether Ollama runs as a Docker container or native install — Docker is cleaner but native has lower overhead
- [Affects R4][Technical] Fallback timeout threshold — how long to wait before switching to API (5s? 10s? 30s?)
- [Affects R7][Technical] Config structure — single `LLM_PROVIDER=ollama|anthropic` toggle vs per-task provider selection

## Next Steps

→ `/ce:plan` for structured implementation planning
