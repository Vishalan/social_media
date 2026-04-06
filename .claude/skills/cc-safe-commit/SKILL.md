---
name: cc-safe-commit
description: Safely commit CommonCreed changes with explicit secret scanning, runtime-output verification, and a full test gate. Use instead of raw `git commit` for any commit touching more than a trivial fix.
---

# cc-safe-commit

Commit CommonCreed changes without accidentally leaking API keys, real secrets, or large generated assets. Replaces raw `git add .` / `git commit` — enforces explicit file staging and a pre-commit audit.

## Usage

```
/cc-safe-commit                          # interactive mode: show diff, let user confirm staging
/cc-safe-commit "<commit message>"       # non-interactive: stage whatever the user already staged, audit, commit
```

## How to run this skill

1. **Refuse `git add .` or `git add -A`.** Stage files explicitly by name. If the user asks for "stage everything", convert it to an explicit file list they can review.

2. **Run the full secret scan** on all staged files before committing. Scan for these patterns (regex):
   - `sk-ant-[A-Za-z0-9_-]{30,}` — Anthropic keys
   - `sk_live_[A-Za-z0-9]{20,}` — Stripe live keys
   - `sk_test_[A-Za-z0-9]{20,}` — Stripe test keys
   - `AIza[A-Za-z0-9_-]{35}` — Google API keys
   - `ghp_[A-Za-z0-9]{30,}` — GitHub personal access tokens
   - `github_pat_[A-Za-z0-9_]{80,}` — GitHub fine-grained tokens
   - `xai-[A-Za-z0-9]{40,}` — xAI/Grok keys
   - `fal-[A-Za-z0-9_-]{30,}` — fal.ai keys
   - `eleven_[A-Za-z0-9_-]{30,}` — ElevenLabs keys
   - The owner's current `PEXELS_API_KEY` value (read from `.env` at scan time, NOT stored in this file). Match any substring of length ≥ 12 that appears in `.env` as the value of `PEXELS_API_KEY` and also appears in any staged file outside `.env`.
   - Any string matching `API[_-]?KEY\s*=\s*["'][A-Za-z0-9+/=_-]{30,}["']` that isn't `.env.example`

   If ANY match is found in staged changes, STOP and report the match with file + line. Do not commit until the user acknowledges.

3. **Verify `.gitignore` coverage** for these path patterns (they should NOT appear in staged files):
   - `**/.env` (without `.example`)
   - `output/` (runtime artifacts)
   - `scripts/output/` (runtime artifacts)
   - `*.mp3`, `*.mp4`, `*.wav` (large media; exceptions for `assets/logos/` and `assets/fonts/`)
   - `.u2net/` (rembg model cache)
   - `node_modules/`, `.venv/`, `venv/`

   Use `git check-ignore -v <path>` to confirm any borderline cases.

4. **Run the full test suite** before committing. If ANY test fails, STOP. Do not commit failing tests.
   ```
   python3 -m pytest scripts/thumbnail_gen/tests/ scripts/video_edit/tests/ scripts/posting/tests/ -q
   ```

5. **Show the diff summary to the user** before committing:
   - Files: `git diff --cached --stat`
   - Line count delta: `git diff --cached --shortstat`
   - Any new binary files (flag them — binaries in git are bad unless explicitly allowed like fonts/logos)

6. **Compose a commit message** in conventional format:
   - Type: `feat` / `fix` / `refactor` / `docs` / `test` / `chore`
   - Scope: module name (`thumbnail_gen`, `posting`, `video_edit`, `sidecar`, `pipeline`, multiple comma-separated)
   - Subject: imperative, ≤72 chars
   - Body: what changed and WHY (not how). Reference plan files and solution docs when relevant.
   - Footer: `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`
   - Always use HEREDOC for the commit message — never inline multi-line strings in shell

7. **Commit** only after all checks pass. Never use `--no-verify`. If a pre-commit hook fails, fix the underlying issue and create a NEW commit (don't `--amend` unless explicitly asked).

8. **After commit**, show `git log -1 --oneline` and `git status` to confirm clean tree.

9. **Never push automatically.** Always wait for the user to explicitly ask for `git push`.

## Rules

- **The owner's real Pexels key lives in `.env`** (the actual value, never in any committed file). Treat the value read from `.env` at scan time as a committed-secret tripwire — any substring of it (≥ 12 chars) appearing in a staged file outside `.env` is a hard fail.
- **`.env.example` is allowed to contain placeholder-shaped strings** like `sk-ant-...`, `your_key_here`, etc. Flag only if a string has the full length + entropy of a real key.
- **Fonts (`assets/fonts/*.ttf`) and logos (`assets/logos/*.png`, `assets/brand_logos/*.png`) are allowed binaries.** Videos and audio are not.
- **If staging any file larger than 5 MB**, flag and ask for confirmation. CommonCreed has no LFS setup; large binaries should be rebuilt, not committed.
- **If the repo is not a git repo** (some temp checkouts aren't), fall back to reporting what WOULD have been committed instead of erroring.

## Anti-patterns to reject

- `git add .` or `git add -A` (explicit file staging only)
- `git commit --no-verify` (never skip hooks)
- `git commit --amend` to an already-pushed commit (creates a new commit instead)
- `git push --force` to `main` (never)
- Committing while a subagent is still running (race conditions on file state)
