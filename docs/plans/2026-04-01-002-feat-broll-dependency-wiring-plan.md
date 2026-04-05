---
title: "feat: Wire b-roll system dependencies for production"
type: feat
status: completed
date: 2026-04-01
origin: docs/brainstorms/2026-03-29-rich-broll-engagement-requirements.md
---

# feat: Wire b-roll system dependencies for production

## Overview

The `broll_gen` module is fully implemented and all 22 unit tests pass. This plan closes the gap between
the written code and a runnable system: `browser_visit.py` hard-imports `playwright.async_api` at module
load (immediate `ImportError` on a fresh install), and `requirements.txt` is the original project scaffold
that is missing every dependency added since initial setup. No code changes are required — only dependency
wiring and validation.

## Problem Frame

The type-driven b-roll system was built and tested against a manually-configured venv. On a fresh install
(or CI), `pip install -r requirements.txt` installs none of the packages the code actually uses:
`Pillow`, `pygments`, `httpx`, `moviepy`, `faster-whisper`, `python-dotenv`, and `playwright` are all
absent from `requirements.txt`. Additionally, `playwright` requires a second step (`playwright install
chromium`) to download the ~150MB Chromium binary — no browser binary means `BrowserVisitGenerator`
fails even when the Python package is installed.

## Requirements Trace

- R2 (`browser_visit`) — `playwright` + Chromium binary must be available on the pipeline host.
- R3 (fallback chain) — every CPU generator must be importable; a missing package at import time breaks
  the entire fallback chain, not just one generator.
- R7 (CPU-only for Phase 1 generators) — confirmed by existing code; no changes needed.
- R9 (no VideoEditor contract changes) — already satisfied; `broll_path` field in `VideoJob` is in place.
- R10 (optional API keys degrade gracefully) — already satisfied; `.env.example` and config dict entries
  for `PEXELS_API_KEY` and `BING_SEARCH_API_KEY` are already present.

## Scope Boundaries

- No changes to `broll_gen/` generator code — all five generators are complete.
- No changes to `commoncreed_pipeline.py` b-roll integration — already wired (`_run_cpu_broll`, Phase 2
  gate, `VideoJob.broll_path`, `VideoJob.needs_gpu_broll`).
- No changes to `VideoEditor` — contract is unchanged (see origin: docs/brainstorms/2026-03-29-rich-broll-engagement-requirements.md).
- No UI or social-posting changes.

## Context & Research

### Relevant Code and Patterns

- `scripts/broll_gen/` — all five generators + selector + factory + base, fully implemented and tested.
- `scripts/broll_gen/browser_visit.py:18` — top-level `from playwright.async_api import async_playwright`.
  This import runs at module load via `make_broll_generator()` in the factory. Any call path that imports
  `broll_gen` will fail immediately on a system without Playwright installed.
- `scripts/requirements.txt` — original scaffold; lists only `anthropic`, `openai`, `requests`, `aiohttp`,
  `websockets`, `click`, `rich`, `python-dateutil`, `boto3`, `google-cloud-storage`, and dev tools.
- `scripts/commoncreed_pipeline.py` line ~385 — `gen_kwargs` already passes `pexels_api_key` and
  `bing_api_key` to generators; config dict already reads `PEXELS_API_KEY` / `BING_SEARCH_API_KEY` from env.
- `scripts/video_edit/video_editor.py` — `assemble()` contract unchanged; broll_path consumed by MoviePy.

### Institutional Learnings

- Playwright Chromium installation is a two-step process: `pip install playwright` then
  `playwright install chromium`. The package alone is not sufficient.
- `browser_visit.py` implements paywall detection via word count (< 200 words → raise `BrollError`),
  Cloudflare/anti-bot fallback (NavigationError → raise `BrollError`), and max screenshot height crop
  (3× viewport). All edge cases are already handled in code.
- Pexels API auth: raw key in `Authorization` header — no `Bearer` prefix (see
  `docs/solutions/workflow-issues/intelligent-broll-type-selection-gpu-phase-gating-2026-03-29.md`).
- FFmpeg `setpts=PTS-STARTPTS` is required after `zoompan` in Ken Burns filter — already present in
  `image_montage.py`. Not a new concern for this plan.

## Key Technical Decisions

- **Freeze venv versions into requirements.txt**: The venv is the authority — `pip freeze` it into
  `requirements.txt` rather than guessing version ranges. This eliminates the drift between what tests
  pass against and what a fresh install produces. Rationale: the project is a single-machine pipeline,
  not a distributed library; reproducibility beats flexibility here.
- **Keep Playwright as a hard dependency, not optional**: Making it a lazy import (try/except ImportError)
  would silently skip `browser_visit` and let the pipeline run without the most engaging b-roll type.
  Since the host machine is under our control, the right fix is to install it, not to soften the import.
  Rationale: consistent with R3 (fallback chain works only if generators are importable).
- **One requirements.txt at root vs. scripts/**: The venv is rooted at the project root. Use
  `scripts/requirements.txt` for script-specific deps (matches current convention and CLAUDE.md layout).

## Open Questions

### Resolved During Planning

- **Should `browser_visit` be a soft/optional dependency?** No — the host machine is controlled, and
  silently degrading b-roll quality is worse than a clear install error. Hard dependency is correct.
- **Which Playwright browser to install?** Chromium only — smallest download, sufficient for news article
  screenshots. Firefox and WebKit not required.
- **Should requirements.txt pin exact versions or use ranges?** Exact versions frozen from the venv.
  The pipeline runs on a controlled host; reproducibility wins.

### Deferred to Implementation

- Exact list of packages in the venv (obtained at implementation time via `pip freeze`).
- Whether `mutagen` is needed in requirements.txt — the pipeline uses a `try/except ImportError` fallback
  for it, so absence doesn't break anything, but including it eliminates the fallback path and gives more
  accurate audio duration. Check venv at implementation time.

## Implementation Units

- [ ] **Unit 1: Update requirements.txt to reflect venv reality**

**Goal:** Replace the stale scaffold `requirements.txt` with the actual packages the pipeline depends on,
so `pip install -r requirements.txt` on a fresh machine produces a working environment.

**Requirements:** R3 (all generators importable), R2 (playwright available)

**Dependencies:** None

**Files:**
- Modify: `scripts/requirements.txt`

**Approach:**
- Run `pip freeze` in the project venv to capture installed packages and versions.
- Replace the file contents with the freeze output, grouped by logical section (AI APIs, video, audio,
  b-roll, utilities, dev tools).
- Include `playwright` in the b-roll section with a comment noting the two-step install requirement.
- Include `mutagen` for reliable audio duration measurement.
- Remove packages that are not used in this pipeline (boto3, google-cloud-storage, aiohttp — check venv
  for actual use before removing).

**Patterns to follow:**
- Existing `requirements.txt` section comment style.
- `scripts/broll_gen/image_montage.py` — `httpx` async pattern confirms httpx must be included.

**Test scenarios:**
- On a fresh venv: `pip install -r requirements.txt` then `python -c "import broll_gen"` succeeds without
  ImportError.
- `playwright` package is listed and the install note is visible.

**Verification:**
- `python -c "from broll_gen import make_broll_generator"` exits with code 0 after a clean install.
- All 49 existing tests still pass (`python -m pytest -v`).

---

- [ ] **Unit 2: Install Playwright Chromium browser binary + smoke-validate**

**Goal:** Confirm Playwright is installed, install the Chromium binary, and run a minimal live test of
`BrowserVisitGenerator` against a known-open article URL to verify the full screenshot → FFmpeg path works
on the pipeline host.

**Requirements:** R2 (`browser_visit` must produce a valid clip), R8 (paywall detection works)

**Dependencies:** Unit 1 (playwright package must be in requirements.txt and installed)

**Files:**
- Create: `scripts/smoke_broll.py` — minimal smoke test (one CPU generator, one GPU path skipped)

**Approach:**
- `playwright install chromium` installs the Chromium binary to Playwright's internal cache (not the venv);
  this step is host-level and must be documented for any new machine setup.
- Smoke test `smoke_broll.py` accepts `--type` flag (default: `browser_visit`) and a `--url` arg, runs
  the specified generator against a real URL, and saves output to `output/broll/smoke_<type>.mp4`.
- For `browser_visit`, use a known open-access article (e.g. a Wikipedia article or an open tech blog) to
  avoid Cloudflare interference during smoke testing.
- The smoke script should NOT require a running pipeline or VideoJob — construct a minimal stub dict for
  the `job` argument.

**Patterns to follow:**
- `scripts/smoke_avatar.py` — same step-by-step output format (`[N. Title]`, `✓`/`✗` markers,
  elapsed time, output path).
- `scripts/broll_gen/base.py` — `BrollBase.generate()` signature.

**Test scenarios:**
- `browser_visit` with an open Wikipedia URL → produces a valid MP4 at `output/broll/smoke_browser_visit.mp4`.
- `browser_visit` with a YouTube URL → `BrollError` raised cleanly (non-article URL check).
- `image_montage` with no API keys → falls back to Google News OG thumbnails or raises `BrollError` cleanly.

**Verification:**
- `python smoke_broll.py --type browser_visit --url https://en.wikipedia.org/wiki/Large_language_model`
  exits 0 and produces a non-empty MP4 file.
- `python smoke_broll.py --type browser_visit --url https://youtube.com/watch?v=xxx` exits non-zero with
  a clear error message.

## System-Wide Impact

- **Interaction graph:** `make_broll_generator()` in `broll_gen/factory.py` is called from
  `commoncreed_pipeline._run_cpu_broll()` (Phase 1). A missing Playwright import would currently surface
  as an `ImportError` at factory call time, not at pipeline startup — making it hard to diagnose without
  reading tracebacks. After this plan, the package is present so the factory call succeeds.
- **Error propagation:** Generators raise `BrollError`; pipeline catches it and advances the fallback
  chain. No changes needed.
- **State lifecycle risks:** None — this plan has no database, cache, or persistent state changes.
- **API surface parity:** None — no public API changes.
- **Integration coverage:** The smoke test (`smoke_broll.py`) provides the first live end-to-end proof
  that the FFmpeg scroll filter and Playwright screenshot path work together on the actual host OS. Unit
  tests mock these out.

## Risks & Dependencies

- **Playwright Chromium binary size (~150MB):** Must be downloaded once per machine. On a RunPod GPU pod,
  this is re-installed each run unless a network volume caches `~/.cache/ms-playwright`. Low risk for the
  development machine; document for production.
- **Playwright on macOS ARM:** Chromium via Playwright works on Apple Silicon. No special flags needed.
- **Open-access URLs for smoke test:** Wikipedia and similar CC-licensed sites are reliable for smoke
  testing. Avoid tech news sites (TechCrunch, Wired) in the smoke test URL — they have soft paywalls that
  may produce < 200 words on cold visits.
- **`requirements.txt` version pinning:** Pinning exact versions means occasional manual bumps. Acceptable
  trade-off for a single-machine pipeline that values reproducibility over library freshness.

## Sources & References

- **Origin document:** [docs/brainstorms/2026-03-29-rich-broll-engagement-requirements.md](../brainstorms/2026-03-29-rich-broll-engagement-requirements.md)
- Institutional learning: `docs/solutions/workflow-issues/intelligent-broll-type-selection-gpu-phase-gating-2026-03-29.md`
- Related code: `scripts/broll_gen/` (all generators), `scripts/commoncreed_pipeline.py` (`_run_cpu_broll`, Phase 2 gate)
- Pattern reference: `scripts/smoke_avatar.py` (smoke test structure)
