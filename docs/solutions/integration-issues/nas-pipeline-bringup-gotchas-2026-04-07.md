---
title: Eleven gotchas hit while bringing the CommonCreed pipeline up on the NAS
category: integration-issues
date: 2026-04-07
tags: [synology, portainer, sidecar, postiz, telegram, apscheduler, faster-whisper, playwright, fal-ai, anthropic, fastapi, secrets, logging]
module: sidecar
component: cc-deploy-portainer + sidecar runtime
---

# Eleven gotchas hit while bringing the CommonCreed pipeline up on the NAS

## Problem

After the initial 6-gotcha Synology deploy was solved (see `synology-portainer-deploy-gotchas-2026-04-07.md`), the next session moved from "the stack starts" to "the pipeline actually generates a video and sends a Telegram preview". That second leg surfaced 11 more distinct failure modes spread across the sidecar, the pipeline subprocess, APScheduler, the Postiz API, and the Telegram bot lifecycle. Each one cost a debug round-trip; together they would have made the pipeline look "mostly working but mysteriously broken" indefinitely.

## Symptoms

1. **Telegram Conflict on bot startup** — `telegram.error.Conflict: Conflict: terminated by other getUpdates request; make sure that only one bot instance is running`. Polling kept restarting and never settling.
2. **Bot token leaked into chat history** — every successful `getUpdates` call logged `POST https://api.telegram.org/bot<TOKEN>/getUpdates "HTTP/1.1 200 OK"` at INFO via httpx, dragging the full token into container logs (and from there into the conversation when we tailed for debug). Burned one bot token rotating, then re-leaked the new one through the same log line, then burned that one too.
3. **APScheduler scheduler refuses to start with persistence** — `sidecar scheduler failed to start: SQLAlchemyJobStore requires SQLAlchemy installed`. Falls back to in-memory; every restart wipes scheduled jobs.
4. **Pipeline subprocess crashes immediately at import** — `ModuleNotFoundError: No module named 'anthropic.resources.messages.messages'; 'anthropic.resources.messages' is not a package`. Failed before doing any actual work.
5. **`ModuleNotFoundError: No module named 'openai'`** — even though the pipeline only uses Anthropic, `scripts/content_gen/script_generator.py` had a hard top-level `import openai`.
6. **`OSError: [Errno 30] Read-only file system: 'output'`** — every `os.makedirs("output/...")` call inside the pipeline crashed because the sidecar mounts `scripts/` as `:ro` and the subprocess inherited that as its cwd.
7. **`ELEVENLABS_API_KEY` "missing"** — but `grep -c '^ELEVENLABS_API_KEY=' .env` returned 1 with `len=51`, and the typed Settings class loaded it correctly. The subprocess `env` dict simply didn't include it.
8. **Pipeline runtime deps missing one at a time** — `moviepy`, then `faster-whisper`, then `playwright`. Each rebuild surfaced the next one because the original Dockerfile assumed pipeline deps would come from a host-mounted venv that was never set up on the NAS.
9. **B-roll fell back to `headline_burst` text cards** — final video was 240KB of black-on-white headline frames instead of an article screenshot. `browser_visit failed (playwright not installed), trying next...` was the actual cause but wasn't called out clearly.
10. **`pipeline_runner` never auto-triggered the Telegram preview** — runs landed at `status='generated'` with captions written, but no approval row was created and no message reached Telegram. The Unit 6 handoff was missing.
11. **`schedule_publish` jobs were silently dropped after approval** — `Run time of job "publish_action" was missed by 0:00:01.146092` warning, then nothing. Approval row flipped to `approved` but `publish_attempted_at` stayed NULL forever.
12. **`duplicate_guard` self-matched the run being published** — first publish attempt died at `publish_failed_duplicate: exact url match: <the same URL we just tried to publish>` because the candidate set treats `status="generated"` as terminal and the run we're publishing is exactly such a row.

## What didn't work

- **Restarting the sidecar to "fix" the Telegram Conflict** — only worked temporarily because the second polling instance was a *separate* `commoncreed_sidecar` container running on the dev Mac via Colima with the same `TELEGRAM_BOT_TOKEN`. Both fought for `getUpdates` until one of them won.
- **Adding `httpx==0.28.1` to sidecar/requirements.txt** to silence URL logging — did nothing, the issue is httpx's default logging level, not the version.
- **Upgrading `anthropic` in the sidecar's own requirements.txt to 0.86** — would have created its own version conflict because the sidecar code (caption_gen, topic_selector) was written against the 0.39 surface. Worked around by giving the pipeline its own venv with the newer version.
- **Skipping playwright entirely and accepting `headline_burst` fallback** — the user looked at the resulting video and the b-roll was unusable for actual content.
- **Manually triggering `send_approval_preview` from a one-shot exec inside the container** — proved the Telegram leg works, but had to be repeated by hand for every test run, and `app.state.telegram_bot` wasn't reachable from a fresh exec context.
- **Using `app.state.scheduler` from `_get_scheduler` in `sidecar/jobs/publish.py`** — the import succeeds but returns `None` when called from within an APScheduler job context because of import ordering vs the FastAPI lifespan.
- **`misfire_grace_time=None` (the APScheduler "infinite" sentinel)** — APScheduler's `add_job(trigger="date")` rejects `None` as the grace time. Had to pick a finite number.

## Solution

A coordinated set of 12 fixes spread across `sidecar/`, `scripts/`, and the `cc-deploy-portainer` skill. Each fix is anchored to a specific commit in the order they were landed.

### Fix 1: Silence httpx + telegram URL loggers BEFORE startup

```python
# sidecar/app.py — top of module, before any import logs
for _noisy in ("httpx", "httpcore", "telegram.ext.Application", "telegram.request"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
```

This must run BEFORE the Telegram Application boots, otherwise the first `deleteWebhook` call already leaks. Verified by tailing logs after rotation: clean polling, no token strings.

### Fix 2: Stop the parallel local-dev sidecar

The Telegram Conflict was caused by the local Colima dev stack still running alongside the NAS production stack with the same bot token. `docker compose -f deploy/portainer/docker-compose.yml down` on the dev Mac immediately resolved the conflict. **There is no way to share a single bot token across two pollers.** Either tear down one, or use webhooks instead of polling.

### Fix 3: Add SQLAlchemy to sidecar requirements

```
# sidecar/requirements.txt
sqlalchemy==2.*
```

APScheduler uses SQLAlchemy for the persistent jobstore. Without it, the scheduler downgrades silently to in-memory and every container restart wipes scheduled jobs (including any approved publishes that were scheduled in the future).

### Fix 4: Robust anthropic import in smoke_e2e

```python
# scripts/smoke_e2e.py:_install_claude_hooks
try:
    # anthropic >= 0.40 layout: messages is a subpackage
    from anthropic.resources.messages.messages import AsyncMessages, Messages
except ImportError:
    # anthropic <= 0.39 layout: messages is a flat module
    from anthropic.resources.messages import AsyncMessages, Messages
```

The pipeline venv ships 0.86 (where the subpackage exists), but local-dev outside the container often has 0.39, and both have to work.

### Fix 5: Make openai import optional in script_generator

```python
# scripts/content_gen/script_generator.py
import anthropic
try:
    import openai  # only needed when api_provider="openai"
except ImportError:
    openai = None  # type: ignore
```

We don't ship openai in the sidecar pipeline venv (Anthropic-only). The hard top-level import made every smoke run crash before reaching script generation.

### Fix 6: Switch subprocess cwd to a writable volume

```python
# sidecar/pipeline_runner.py
scripts_dir = str(Path(settings.PIPELINE_SCRIPTS_PATH).resolve())  # /app/scripts
scripts_cwd = "/app/output"  # writable named volume
Path(scripts_cwd).mkdir(parents=True, exist_ok=True)
# ...
cmd = ["/opt/pipeline_venv/bin/python3", str(Path(scripts_dir) / "smoke_e2e.py")]
```

Python sets `sys.path[0]` to the directory of the script regardless of cwd, so absolute imports inside the pipeline modules still resolve. The cwd swap only affects relative `output/...` paths used by smoke_e2e and its helpers.

Also add `PYTHONPATH=/app` to the subprocess env so absolute `from scripts.thumbnail_gen.xxx import yyy` style imports resolve.

### Fix 7: Pass the entire .env file through to the subprocess env

```python
# sidecar/pipeline_runner.py:_build_subprocess_env
env = {"PATH": ..., "HOME": ..., "LANG": ..., "PYTHONPATH": "/app"}
env_path = getattr(settings, "SIDECAR_ENV_PATH", None) or "/env/.env"
with open(env_path) as fh:
    for line in fh:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
env["SMOKE_TOPIC"] = run_row.get("topic_title") or ""
env["SMOKE_URL"] = run_row.get("topic_url") or ""
```

The hand-picked env list missed `ELEVENLABS_VOICE_ID`, `FAL_API_KEY`, `SMOKE_USE_VEED`, `VEED_AVATAR_IMAGE_URL`, and would silently miss every future addition. Reading the whole `.env` file is the only way to keep parity. Secrets only enter a child subprocess the sidecar controls; **never echoed to chat or logs**.

### Fix 8: Bake the pipeline venv into the sidecar image

```dockerfile
# sidecar/Dockerfile
COPY pipeline_requirements.txt /app/pipeline_requirements.txt
RUN python3 -m venv /opt/pipeline_venv \
    && /opt/pipeline_venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/pipeline_venv/bin/pip install --no-cache-dir -r /app/pipeline_requirements.txt \
    && /opt/pipeline_venv/bin/playwright install chromium \
    && /opt/pipeline_venv/bin/playwright install-deps chromium || true
```

`pipeline_requirements.txt` is a curated subset of `scripts/requirements.txt`: anthropic 0.86, openai 2.30 (optional via fix 5), elevenlabs 2.40, moviepy, av, Pillow 11, faster-whisper, playwright + chromium, beautifulsoup4, lxml, feedparser, etc. We deliberately exclude runpod, click, rich, pytrends and other CLI/dev-only deps.

The pipeline venv stays strictly separate from `sidecar/requirements.txt` so the two environments can drift independently — the sidecar pins anthropic 0.39 and httpx 0.27 because its own code expects those.

### Fix 9: Use overlay tar instead of `rm -rf` for code uploads

```bash
# DO this — overlay onto existing dir, doesn't break the bind mount
tar czf - --exclude '__pycache__' --exclude '*.pyc' -C scripts . | \
  ssh user@nas 'tar xzf - -C /volume1/docker/commoncreed/scripts'

# DON'T do this — rm -rf invalidates the inode the running container is bound to
ssh user@nas 'rm -rf /volume1/docker/commoncreed/scripts && \
              mkdir -p /volume1/docker/commoncreed/scripts && \
              tar xzf - -C /volume1/docker/commoncreed/scripts'
```

The original cc-deploy-portainer skill used the `rm -rf` form. We hit the bug live: `os.listdir('/app/scripts')` returned `[]` inside the container immediately after a successful upload, because the container was holding the now-orphaned old inode. Restarting the container rebinds the mount, but the cleaner fix is to never wipe the directory in the first place.

### Fix 10: Wire `send_approval_preview` into pipeline_runner success path

```python
# sidecar/pipeline_runner.py — after set_captions
try:
    from . import runtime as _rt
    from .telegram_bot import send_approval_preview
    if _rt.telegram_app is None:
        logger.warning("no telegram app registered; skipping preview for run %s", pipeline_run_id)
    else:
        await send_approval_preview(_rt.telegram_app, pipeline_run_id)
        logger.info("telegram preview sent for run %s", pipeline_run_id)
except Exception as exc:
    logger.exception("send_approval_preview failed for run %s: %s", pipeline_run_id, exc)
```

This is the Unit 6 handoff that was missing. Best-effort: a flaky bot does NOT flip the run back to failed — the video is generated and can be re-delivered later via the dashboard.

### Fix 11: Module-level runtime registry for scheduler-bound handlers

```python
# sidecar/runtime.py — new module
telegram_app: Optional[Any] = None
scheduler: Optional[Any] = None

# sidecar/app.py — populated at startup
from . import runtime as _rt
_rt.telegram_app = tg_app  # after build_application()
_rt.scheduler = sched      # after sched.start()

# sidecar/jobs/publish.py — read from registry
def _get_scheduler():
    try:
        from sidecar import runtime as _rt
        if _rt.scheduler is not None:
            return _rt.scheduler
    except Exception:
        pass
    # fallback for tests
    try:
        from sidecar.app import app as fastapi_app
        return getattr(fastapi_app.state, "scheduler", None)
    except Exception:
        return None
```

Job handlers running under APScheduler's own context can't reach `app.state` because importing `sidecar.app` from a job module pulls the whole FastAPI graph and either circular-imports or returns a stale view. Module-level singletons are the simple, correct seam.

### Fix 12: Bump publish job misfire_grace_time + exclude self in dup guard

```python
# sidecar/jobs/publish.py
sched.add_job(
    publish_action,
    trigger="date",
    run_date=run_at,
    args=[pipeline_run_id],
    id=job_id,
    replace_existing=True,
    # APScheduler default is 1s — too tight when target is "now" and the
    # jobstore round-trip takes >1s. Allow up to 5 minutes.
    misfire_grace_time=300,
)

# sidecar/duplicate_guard.py
def check(conn, topic_url, topic_title, ..., exclude_run_id=None):
    ...
    if exclude_run_id is not None:
        sql += "  AND id != ? "
        params.append(int(exclude_run_id))

# sidecar/jobs/publish.py — call site
dup_result = duplicate_check(
    dup_conn, topic_url, topic_title,
    exclude_run_id=pipeline_run_id,
)
```

The misfire fix unblocks every publish job that targets "now". The exclude_run_id fix unblocks every publish for a run whose URL has never been published before (the first attempt always self-matched).

## Why this works

Each fix addresses a specific contract violation between two layers — sidecar and APScheduler, sidecar and the pipeline subprocess, sidecar and the bind mount, sidecar and Telegram, sidecar and Postiz. The pattern is the same across all of them: **don't trust that a layer's defaults match what you expect.** APScheduler's default misfire grace is 1s. httpx's default log level is INFO. Python's `import` mechanism uses `sys.path[0]` not cwd. Bind mounts hold inode refs. The pipeline subprocess inherits NO env unless you explicitly pass it. Each of these is documented behavior, but only becomes obvious when it bites.

The combination unblocks the full path:
1. ✅ Sidecar boots cleanly with persistent jobstore
2. ✅ Telegram polling stable, no token leaks
3. ✅ pipeline_runner dispatches subprocesses with the right env, cwd, python interpreter, and PYTHONPATH
4. ✅ Pipeline runs through script + thumbnail + voice + b-roll (browser_visit) + whisper captions + moviepy assembly
5. ✅ pipeline_runner auto-fires Telegram preview after generation
6. ✅ Approve via API or Telegram tap → publish job actually runs (doesn't get dropped on misfire)
7. ✅ duplicate_guard doesn't self-match the run being published

What's still broken (deferred to next session): the Postiz `publish_post` body shape. The current sidecar payload was written against an older Postiz contract; the running Postiz wants a two-step `upload` + `posts` flow with `{posts: [{integration: {id}, value: [{content, image: [...]}]}]}` shape and explicit integration IDs. That's a focused rewrite, not another patch.

## Prevention

- **Always run a real end-to-end smoke test through the FULL pipeline against the real production target** (not just a subset against local dev). Each leg between two systems has its own unique failure modes that local Colima testing misses.
- **Mute httpx and other request loggers preemptively in any service that talks to a tokenized API.** Don't wait for the leak to happen.
- **Pin APScheduler `misfire_grace_time` explicitly on every `add_job` call** that targets "now" — never rely on the 1s default.
- **Never `rm -rf` a path that's bind-mounted into a running container.** Use overlay tar for upserts; restart the container after any directory recreate.
- **Hand-picked subprocess env lists drift.** If the parent loads its config from a `.env` file, pass the whole file through to children rather than enumerating the keys.
- **Module-level singletons (`sidecar/runtime.py`) are the right seam between FastAPI app state and APScheduler job handlers.** Trying to import the FastAPI app object from inside a job is a circular-import trap.
- **Treat `status='generated'` as a non-terminal status from the publishing system's perspective**, even if it's terminal from the generator's perspective. duplicate_guard, retention, and any other "look back at history" job needs to know which run is the *current* operation and exclude it.
- **Add an entry log line to every async job handler.** "Did the job run?" should be answerable in 5 seconds, not 30 minutes.
- **When a Postiz (or any third-party) API returns an unexpected error, look at the actual running container source** (`/app/apps/backend/dist/...`) before guessing payload shapes — the docs and the deployed binary can drift.

## Test cases (for the deploy skill)

These should run as smoke checks after every deploy:

```python
# 1. Sidecar can write to /app/output (PIPELINE_OUTPUT_ROOT path)
exec_inside("commoncreed_sidecar", "python -c 'import os; open(\"/app/output/.smoke\",\"w\").write(\"ok\"); os.remove(\"/app/output/.smoke\")'")

# 2. Pipeline venv has all required deps
exec_inside("commoncreed_sidecar", "/opt/pipeline_venv/bin/python3 -c 'import moviepy, av, anthropic, faster_whisper, playwright; print(\"venv ok\")'")

# 3. Bind mounts visible inside container
exec_inside("commoncreed_sidecar", "python -c 'import os; assert os.path.exists(\"/app/scripts/smoke_e2e.py\"); assert os.path.exists(\"/app/assets/logos/owner-portrait-9x16.jpg\"); print(\"mounts ok\")'")

# 4. Sidecar runtime registry populated after startup
exec_inside("commoncreed_sidecar", "python -c 'from sidecar import runtime; assert runtime.scheduler is not None; assert runtime.telegram_app is not None; print(\"runtime ok\")'")

# 5. APScheduler persistent jobstore alive
exec_inside("commoncreed_sidecar", "python -c 'from sidecar import runtime; jobs = runtime.scheduler.get_jobs(); print(f\"{len(jobs)} jobs scheduled\"); assert any(j.id == \"daily_trigger\" for j in jobs)'")

# 6. No httpx token leaks in last 200 log lines
logs = container_logs("commoncreed_sidecar", tail=200)
assert "/bot" not in logs or ":AAA" not in logs, "Telegram token may have leaked into logs"

# 7. Smoke pipeline run completes (only if FAL_API_KEY + ELEVENLABS keys are set)
inject_pending_run("smoke topic", "https://example.com")
wait_for_status("generated", timeout=900)
```
