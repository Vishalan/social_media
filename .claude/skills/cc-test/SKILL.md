---
name: cc-test
description: Run CommonCreed project tests with the right pytest paths, working directory, and common-gotcha awareness. Use whenever you need to verify tests after changes.
---

# cc-test

Run the CommonCreed test suite correctly. This project has a few cwd gotchas and a specific test layout — always use this skill instead of running raw pytest commands.

## Usage

```
/cc-test                     # run the full unit-test suite (fast, all modules)
/cc-test <module>            # run one module's tests, e.g. thumbnail_gen, posting, video_edit
/cc-test <path>              # run one specific test file or directory
/cc-test --smoke             # run the smoke pipeline in REUSE mode (no cost — uses cached assets)
/cc-test --smoke-full        # run the full smoke pipeline WITH cost (~$1.96) — prompts for confirmation first
```

## How to run this skill

1. **Always use `python3`, never `python`.** The default `python` on macOS system Python is not wired.

2. **Always run from the project root** (`/Users/vishalan/Documents/Projects/social_media`), not from `scripts/`. Pytest discovers via the `scripts/pytest.ini` config, and import resolution differs between cwds.

3. **The canonical unit-test command** for verifying CommonCreed Python code:
   ```
   python3 -m pytest scripts/thumbnail_gen/tests/ scripts/video_edit/tests/ scripts/posting/tests/ -q
   ```
   This is the full safety net. It should always be 50/50 green (or whatever the current total is) before any commit.

4. **Per-module shortcuts:**
   - `thumbnail_gen` → `python3 -m pytest scripts/thumbnail_gen/tests/ -v`
   - `video_edit` → `python3 -m pytest scripts/video_edit/tests/ -v`
   - `posting` → `python3 -m pytest scripts/posting/tests/ -v`
   - `sidecar` → `python3 -m pytest sidecar/tests/ -v` (only after Unit 2 of Plan 002 lands)

5. **Smoke pipeline (reuse mode — no API cost):**
   ```
   cd scripts && SMOKE_REUSE_AVATAR=1 SMOKE_TOPIC="<topic>" SMOKE_URL="<url>" python3 smoke_e2e.py
   ```
   - Uses cached audio + per-segment avatar clips from `scripts/output/audio/` and `scripts/output/avatar/`
   - Will still spend ~$0.0007 on Haiku for the new thumbnail/caption step
   - **The cost report shows a $1.52 VEED line** — this is a tracker artifact, NOT real spend. Always clarify this to the user.

6. **Full smoke pipeline (real cost ~$1.96):**
   ```
   cd scripts && SMOKE_USE_VEED=1 SMOKE_TOPIC="<topic>" SMOKE_URL="<url>" python3 smoke_e2e.py
   ```
   - Fresh Sonnet script, fresh ElevenLabs voice, 4 parallel VEED calls, fresh b-roll + assembly
   - **NEVER run this without explicit user go-ahead in the same conversation.** The user previously asked to pause costs; always confirm.

## Common gotchas

- **cwd matters**: `smoke_e2e.py` expects to run from `scripts/` (its relative paths like `output/audio/...` are cwd-relative). pytest expects to run from the project root. Don't mix them.
- **Dual import paths**: modules under `scripts/` sometimes need to work with both `from scripts.X` (pytest) and `from X` (when run from `scripts/` cwd). The project uses a try-except pattern for this. If you see `ModuleNotFoundError: No module named 'scripts'` when the smoke runs, the lazy import probably needs the fallback pattern.
- **Haiku cost tracking** is real and appears in test output (~$0.001/call). Sonnet and ElevenLabs only trigger in full smoke mode.
- **VEED cost line in cost reports during reuse runs is fake** — the tracker records cached avatar duration as if billed. Only the Haiku line is real for reuse runs.

## Reporting results

After running tests, always report:
- Total: `X passed, Y failed` with elapsed seconds
- If failures: the first 3 failure headers and a one-line summary each
- If green: "✓ N/N passing" and the exact command that was run (so the user can re-run it)
- For smoke runs: the real cost (discount the tracker artifact for reuse mode), the final video path, and any visible issues noted in the logs
