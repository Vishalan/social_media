---
title: "fix: Meme quality overhaul — strict scoring, cross-run dedup, reduced surface"
type: fix
status: completed
completed_at: 2026-04-19
completion_evidence: "Merged to main via commit 4953a9b; all 4 units implemented with 13 tests passing in sidecar/tests/test_meme_quality_overhaul.py. Shipped via agent-team execution pattern."
date: 2026-04-16
origin: docs/brainstorms/2026-04-16-meme-quality-overhaul-requirements.md
---

# fix: Meme quality overhaul — strict scoring, cross-run dedup, reduced surface

## Overview

Fix low-quality meme surfacing by: (1) reverting scoring to Haiku API for nuanced humor/relevance ratings, (2) raising thresholds to >= 7, (3) adding 48-hour cross-run dedup, (4) reducing surface limits. The pipeline surfaces too much mediocre and duplicate content.

## Requirements Trace

- R1. Humor + relevance thresholds >= 7/10 (origin R1)
- R2. Meme scoring uses Anthropic Haiku (origin R2)
- R3. Surface limits: 2 images + 2 videos per run (origin R3)
- R4. Cross-run dedup: 48h lookback, 0.7 Jaccard (origin R4)
- R5. Ollama stays for topic ranking (origin R5)
- R6. Add more Reddit sources to widen funnel (origin R6)

## Scope Boundaries

- Not changing publish/Postiz flow
- Not adding non-Reddit sources beyond what exists
- Autopilot targets unchanged (1 img + 2 vid/day)

## Implementation Units

- [x] **Unit 1: Revert meme scoring to Haiku + raise thresholds**

**Goal:** `_score_candidates_batch` uses Anthropic Haiku directly (not llm_client), and filter thresholds raised to >= 7.

**Files:**
- Modify: `sidecar/jobs/meme_flow.py`
- Modify: `sidecar/config.py`

**Approach:**
- In `_score_candidates_batch`: set `provider="anthropic"` and `model="claude-haiku-4-5-20251001"` hardcoded (not configurable — this is a quality-critical path where Haiku's nuanced scoring is required)
- Raise filter in `run_meme_trigger` from `>= 3.0` to `>= 7.0` for both humor and relevance
- Add config vars: `MEME_MIN_HUMOR_SCORE: int = 7`, `MEME_MIN_RELEVANCE_SCORE: int = 7`
- Keep `MEME_SCORING_PROVIDER` env var but default it to `anthropic`

**Verification:**
- Trigger produces candidates with gradient scores (3, 5, 7, 8, 9 — not just 10 or 5)
- Only candidates with both scores >= 7 are surfaced

---

- [x] **Unit 2: Reduce surface limits**

**Goal:** Fewer, higher-quality previews per trigger run.

**Files:**
- Modify: `sidecar/config.py`

**Approach:**
- `MEME_DAILY_SURFACE_LIMIT: int = 2` (was 5)
- `MEME_VIDEO_DAILY_SURFACE_LIMIT: int = 2` (was 4)

**Verification:**
- Max 4 Telegram previews per trigger run (2 img + 2 vid)

---

- [x] **Unit 3: Cross-run dedup before surfacing**

**Goal:** Don't send a Telegram preview if a similar candidate was surfaced in the last 48 hours.

**Files:**
- Modify: `sidecar/jobs/meme_flow.py`

**Approach:**
- Before surfacing a candidate to Telegram, query `meme_candidates` for rows with `telegram_message_id IS NOT NULL` and `created_at >= datetime('now', '-2 days')`
- Compute Jaccard similarity of the new candidate's title against each recently surfaced title
- Skip if any match >= 0.7
- Log skipped candidates for debugging

**Patterns to follow:**
- Existing Jaccard logic in `sidecar/db.py:insert_meme_candidate`

**Verification:**
- Same meme posted by different users across runs doesn't surface twice
- Thematically similar memes ("debugging at 3am" variants) are deduped

---

- [x] **Unit 4: Add more Reddit sources**

**Goal:** Widen the top-of-funnel so strict filtering still yields enough candidates.

**Files:**
- Modify: `sidecar/config.py`
- Modify: `sidecar/meme_sources/reddit_memes.py`
- Modify: `sidecar/meme_sources/__init__.py`

**Approach:**
- Add: r/cscareerquestions (dev culture), r/webdev (web dev humor), r/DataIsBeautiful (data/viz humor), r/homelab (tech builds), r/MechanicalKeyboards (tech culture)
- These are tech-on-brand subs that increase candidate volume before the strict humor+relevance filter

**Verification:**
- More candidates fetched per run (30+)
- After >= 7 filtering, still enough survivors to fill the 2+2 surface slots

## Sources & References

- **Origin:** [docs/brainstorms/2026-04-16-meme-quality-overhaul-requirements.md](docs/brainstorms/2026-04-16-meme-quality-overhaul-requirements.md)
- Scoring: `sidecar/jobs/meme_flow.py:_score_candidates_batch`
- Config: `sidecar/config.py`
- Dedup: `sidecar/db.py:insert_meme_candidate`
