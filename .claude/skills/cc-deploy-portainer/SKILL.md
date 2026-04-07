---
name: cc-deploy-portainer
description: End-to-end deploy of the CommonCreed stack to the Synology DS1520+ Portainer instance. Handles preflight, SSH-based code+secrets upload, Portainer REST API stack create/update, container health verification, and rollback on failure. Use whenever you need to push the stack to production.
---

# cc-deploy-portainer

Deploy or update the CommonCreed `docker-compose.yml` stack on the owner's Synology DS1520+ via Portainer's REST API. No browser interaction required — Portainer is fully API-driven.

## Usage

```
/cc-deploy-portainer                       # full fresh deploy (creates new stack)
/cc-deploy-portainer --update              # in-place update of existing stack (PUT, not DELETE+POST)
                                           # use this whenever the compose file or .env changed
/cc-deploy-portainer --update --restart=postiz,sidecar
                                           # update + restart specific containers afterward (for env-only changes)
/cc-deploy-portainer --dry-run             # preflight + show what would happen, no changes
/cc-deploy-portainer --rollback            # restore the previous stack version
/cc-deploy-portainer --logs <svc>          # tail the last 200 lines of a single service
/cc-deploy-portainer --logs <svc> --follow # stream logs in real time
/cc-deploy-portainer --logs --all          # last 50 lines from every service in the stack
/cc-deploy-portainer --status              # quick health check of all 7 containers, no deploy
/cc-deploy-portainer --restart <svc>       # restart a single container (no deploy, no compose change)
/cc-deploy-portainer --shell <svc>         # open an interactive bash shell inside a container via Portainer's exec API
```

## Connection details

These come from project memory `project_synology_portainer.md` — read it first to confirm the target hasn't moved:

| Field | Value | Source |
|---|---|---|
| Portainer URL | `http://192.168.29.211:9000` | memory |
| Portainer username | `vishalan` | memory |
| Portainer password | (Keychain) | `security find-generic-password -a vishalan -s commoncreed-portainer -w` |
| NAS host | `192.168.29.211` | memory |
| NAS deploy dir | `/volume1/docker/commoncreed/` | memory |
| Portainer endpoint id | `3` (verified 2026-04-07; do NOT hardcode in code, query at runtime) | API |
| Stack name in Portainer | `commoncreed` | constant |
| Postiz host port | `5100` (NOT 5000 — DSM uses 5000 for its own web UI) | NAS .env `POSTIZ_HOST_PORT` |
| Sidecar host port | `5050` | NAS .env |

## ⚠ Gotchas this skill MUST handle (each one bit us during real deploys)

These are baked into the phases below. Do NOT skip any.

### Original 6 (first deploy, 2026-04-07)

1. **DSM owns port 5000** on Synology — Postiz cannot bind to it. Use 5100 (or any non-DSM port). Synology DSM web UI at `http://<nas>:5000` is non-negotiable; you can't move it.
2. **Portainer container is sandboxed** — `build:` directives in compose fail because Portainer can't see `/volume1/docker/commoncreed/sidecar` from inside its own container. **Pre-build the sidecar image via Portainer's image-build API**, then reference by `image:` tag in the deployed compose. The build context is uploaded as a tar to `POST /api/endpoints/{id}/docker/build?t=<tag>`.
3. **Portainer's create-stack API does NOT auto-load `.env`** from the host — `${VAR}` references in the compose resolve to empty strings unless you pass `env: [{"name":"K","value":"V"}, ...]` in the request body. Read the NAS `.env` over SSH (silently, no chat echo), parse, and pass.
4. **Synology's PAM blocks rsync's `--server` protocol** over SSH for non-interactive sessions. Plain `ssh user@host 'command'` works; `rsync` does not. Use **`tar czf - -C src . | ssh user@host 'tar xzf - -C dst'`** for all code uploads. SCP/SFTP also fail (subsystem disabled). Test transport during preflight before doing real uploads.
5. **Temporal's `auto-setup` script races on first boot.** It tries to register search attributes via the frontend before the frontend is fully serving, then completes successfully but the actual `temporal-server` may not transition cleanly. **After the stack starts, restart the temporal container once.** On the second boot, the Postgres+ES schema is already initialized so it boots cleanly in <30s.
6. **Postiz crash-loops on the initial Temporal connection** — its NestJS backend exits on `ECONNREFUSED 7233` and the container's supervisor keeps restarting it, but it caches the failure between attempts. **After Temporal is restarted (gotcha #5) and fully serving, restart the postiz container once** so it gets a fresh attempt with a working Temporal. The deploy is not complete until BOTH temporal and postiz have been restarted at least once each.

### Pipeline bring-up gotchas (2026-04-07 evening)

7. **NEVER `rm -rf` a bind-mounted directory on the host** — that destroys the inode the running container has bound, leaving the container with an empty mount even though the host dir was recreated. Always use **overlay tar**: `tar czf - -C src . | ssh host 'tar xzf - -C dst'` (no `rm -rf` first). If you absolutely must wipe a dir, restart the container afterwards to rebind the mount.
8. **Pipeline runtime needs its own venv inside the sidecar image** — moviepy, av, faster-whisper, playwright, newer anthropic etc. would conflict with the sidecar's own pinned deps. Bake `/opt/pipeline_venv` from `sidecar/pipeline_requirements.txt`, and have `pipeline_runner` exec `/opt/pipeline_venv/bin/python3` for the smoke subprocess.
9. **`/app/scripts` is mounted `:ro` but smoke_e2e writes `output/...` relative paths** — set the subprocess `cwd=/app/output` (a writable named volume), pass smoke_e2e.py as an absolute path, and add `PYTHONPATH=/app` so `from scripts.thumbnail_gen.xxx import` style absolute imports resolve.
10. **The hand-picked subprocess env list will silently miss new vars** (ELEVENLABS_VOICE_ID, FAL_API_KEY, SMOKE_USE_VEED, ...) as the pipeline grows. `pipeline_runner._build_subprocess_env` reads the entire `.env` file at the path the sidecar is configured for and passes every KEY=VALUE through. Secrets only enter a child process the sidecar controls; never echoed.
11. **httpx + python-telegram-bot log full request URLs at INFO** — that means every Telegram `getUpdates` call dumps the bot token in plaintext into container logs (and from there into chat history when tailing for debug). Mute `httpx`, `httpcore`, `telegram.ext.Application`, and `telegram.request` to WARNING in `sidecar/app.py` *before* any of them logs anything.
12. **APScheduler default `misfire_grace_time` is 1 second.** Any one-shot `date` job scheduled at "now" that takes longer than 1s of jobstore round-trip + event loop latency gets silently dropped with a misfire warning. For real-world publish jobs always pass `misfire_grace_time=300` (or higher).
13. **Persistent APScheduler jobstore needs SQLAlchemy.** Without it the scheduler logs "SQLAlchemyJobStore requires SQLAlchemy installed" and silently downgrades to in-memory — every restart wipes scheduled jobs. Pin `sqlalchemy==2.*` in `sidecar/requirements.txt`.
14. **`anthropic.resources.messages.messages` only exists in anthropic >= 0.40** (it was a flat module in 0.39). Anything that monkey-patches `Messages` / `AsyncMessages` must try the subpackage path first and fall back to the flat module on `ImportError`.
15. **`duplicate_guard.check` self-matches the run being published** because `status="generated"` is in `TERMINAL_STATUSES` and the run we're about to publish is exactly such a row. Always pass `exclude_run_id=pipeline_run_id` from `publish_action`.
16. **Postiz public API is mounted at `/api/public/v1/*`, not `/public/v1/*`.** The `/api` segment is the global backend prefix. Hitting the wrong path returns a Next.js 404 with `"Server action not found"` — easy to misread as "endpoint missing".
17. **Job handlers running under APScheduler can't reach `app.state`** — importing `sidecar.app` from a job module pulls the whole FastAPI graph and either circular-imports or returns a stale view. Use the module-level `sidecar/runtime.py` registry that `app.py` populates at startup (`runtime.scheduler`, `runtime.telegram_app`).

These are documented in `docs/solutions/integration-issues/synology-portainer-deploy-gotchas-2026-04-07.md` and `docs/solutions/integration-issues/nas-pipeline-bringup-gotchas-2026-04-07.md`.

**Never write the password to a file or echo it in chat.** Always read it from Keychain at the moment of use, store it in a shell variable for the duration of the API calls, then unset it.

---

## End-to-end deploy cycle

The skill executes 8 phases. Each phase has a clear pass/fail gate. Failure in any phase blocks the next and either rolls back or surfaces a precise error.

### Phase 0 — Preflight (local Mac)

Run BEFORE any network call to the NAS. All checks must pass.

1. **Branch + working tree clean**
   ```bash
   git status --porcelain
   ```
   Must be empty. If not, refuse to deploy and tell the user to commit or stash.

2. **Tests green**
   Invoke the `cc-test` skill or run directly:
   ```bash
   python3 -m pytest sidecar/tests/ scripts/thumbnail_gen/tests/ scripts/video_edit/tests/ scripts/posting/tests/ -q
   ```
   Must show `211 passed` (or whatever the current total is). Any failure → refuse deploy.

3. **Compose file portability check**
   Read `deploy/portainer/docker-compose.yml` and grep for relative bind mount paths. Look for any `volumes:` entry whose host side starts with `./` or `../`. If found, the deploy script must rewrite them to absolute NAS paths in the compose payload sent to Portainer (do NOT modify the on-disk file — generate a transient version).

   Specifically transform on the way out:
   - `../../scripts:/app/scripts:ro` → `/volume1/docker/commoncreed/scripts:/app/scripts:ro`
   - `../../.env:/env/.env:ro` → `/volume1/docker/commoncreed/.env:/env/.env:ro`
   - `./temporal-dynamicconfig:/etc/temporal/config/dynamicconfig` → `/volume1/docker/commoncreed/deploy/portainer/temporal-dynamicconfig:/etc/temporal/config/dynamicconfig`
   - `./postgres-init:...` → same pattern (if still present)
   - The sidecar build context `../../sidecar` → for Portainer it must be `/volume1/docker/commoncreed/sidecar`

4. **Drop the macOS-only port remap for Synology**
   Synology has no AirPlay Receiver competing for port 5000. The compose currently maps `${POSTIZ_HOST_PORT:-5100}:5000`. For the Synology payload, keep the env-var pattern but expect `POSTIZ_HOST_PORT=5000` in the NAS `.env` (don't hardcode — let the env file decide).

5. **Validate `.env` has every required key**
   Read `deploy/portainer/.env.example` for the canonical list. The Synology `.env` (uploaded in Phase 2) must contain at minimum:
   - `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`
   - `POSTIZ_JWT_SECRET`, `POSTIZ_MAIN_URL`, `POSTIZ_FRONTEND_URL`, `DATABASE_URL`, `REDIS_URL`
   - `POSTIZ_API_KEY` (placeholder OK on first deploy; gets replaced after Postiz admin creates one)
   - `ANTHROPIC_API_KEY`, `SIDECAR_ADMIN_PASSWORD`
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GMAIL_OAUTH_PATH`
   - All `PIPELINE_*` tunables

   The Synology `POSTIZ_MAIN_URL` and `POSTIZ_FRONTEND_URL` must reference the NAS hostname/IP, NOT `localhost`. Default: `http://192.168.29.211:5000` or `http://your-nas.local:5000`.

6. **Check the temporal-dynamicconfig file exists**
   `deploy/portainer/temporal-dynamicconfig/development-sql.yaml` — fetched from the official Postiz repo. Must be present.

7. **Confirm SSH access to the NAS**
   ```bash
   ssh -o ConnectTimeout=5 -o BatchMode=yes vishalan@192.168.29.211 'echo ok' 2>&1
   ```
   If batch-mode SSH fails (no key set up), prompt the user once interactively to enable SSH key auth on the NAS, OR fall back to interactive password auth via `sshpass` (less ideal — install on first run if needed).

If any preflight check fails, STOP and report the failure with actionable next steps.

### Phase 1 — Snapshot the existing stack (rollback safety)

1. Read Portainer password from Keychain into a shell variable:
   ```bash
   PORTAINER_PASSWORD=$(security find-generic-password -a vishalan -s commoncreed-portainer -w)
   ```

2. Authenticate against Portainer:
   ```bash
   PORTAINER_JWT=$(curl -sf -X POST http://192.168.29.211:9000/api/auth \
     -H "Content-Type: application/json" \
     -d "{\"username\":\"vishalan\",\"password\":\"$PORTAINER_PASSWORD\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["jwt"])')
   unset PORTAINER_PASSWORD
   ```
   `unset` immediately after use. Never persist the password variable beyond the auth call.

3. Discover the Docker endpoint ID:
   ```bash
   ENDPOINT_ID=$(curl -sf -H "Authorization: Bearer $PORTAINER_JWT" \
     http://192.168.29.211:9000/api/endpoints | python3 -c 'import json,sys; e=json.load(sys.stdin); print([x["Id"] for x in e if x["Type"]==1][0])')
   ```
   Type 1 = local Docker endpoint. There's almost always exactly one on a single-NAS Portainer install. **As of the smoke test on 2026-04-07, the endpoint ID on this Synology is `3`** (Portainer increments IDs as endpoints come and go; do not hardcode).

4. Find the existing `commoncreed` stack if present:
   ```bash
   EXISTING_STACK_ID=$(curl -sf -H "Authorization: Bearer $PORTAINER_JWT" \
     "http://192.168.29.211:9000/api/stacks?filters=%7B%22EndpointId%22%3A$ENDPOINT_ID%7D" | python3 -c 'import json,sys; ss=json.load(sys.stdin); print(next((s["Id"] for s in ss if s["Name"]=="commoncreed"), ""))')
   ```

5. If the stack exists, fetch its current compose content + env vars and save to a local rollback file:
   ```bash
   mkdir -p .deploy-rollback
   curl -sf -H "Authorization: Bearer $PORTAINER_JWT" \
     "http://192.168.29.211:9000/api/stacks/$EXISTING_STACK_ID/file" > .deploy-rollback/$(date +%Y%m%d-%H%M%S)-stack-file.json
   ```

6. Capture the running container state for diff after deploy:
   ```bash
   curl -sf -H "Authorization: Bearer $PORTAINER_JWT" \
     "http://192.168.29.211:9000/api/endpoints/$ENDPOINT_ID/docker/containers/json?all=true&filters=%7B%22label%22%3A%5B%22com.docker.compose.project%3Dcommoncreed%22%5D%7D" \
     > .deploy-rollback/$(date +%Y%m%d-%H%M%S)-containers-before.json
   ```

If this is a fresh deploy (no existing stack), skip the snapshot but still create `.deploy-rollback/` so the directory exists.

### Phase 2 — Upload code and secrets to the NAS via tar-over-SSH

**Do NOT use `rsync`** — Synology's PAM auth chain (`pam_syno_support.so`) blocks rsync's `--server` invocation over SSH for non-interactive sessions, even with key auth working. SCP also fails because the SFTP subsystem is disabled. The transport that works is `tar | ssh ... 'tar x'`.

```bash
# 0. Ensure deploy dir exists with secrets/ subdir (mode 700)
ssh -o BatchMode=yes vishalan@192.168.29.211 \
  'mkdir -p /volume1/docker/commoncreed/secrets && chmod 700 /volume1/docker/commoncreed/secrets'

# 1. Pipeline code (scripts/) — full replace via tar pipe
tar czf - --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'output' --exclude 'tmp*' --exclude '.pytest_cache' \
  -C scripts . | \
  ssh -o BatchMode=yes vishalan@192.168.29.211 \
  'rm -rf /volume1/docker/commoncreed/scripts && mkdir -p /volume1/docker/commoncreed/scripts && tar xzf - -C /volume1/docker/commoncreed/scripts'

# 2. Sidecar source
tar czf - --exclude '__pycache__' --exclude '*.pyc' --exclude '.pytest_cache' \
  -C sidecar . | \
  ssh -o BatchMode=yes vishalan@192.168.29.211 \
  'rm -rf /volume1/docker/commoncreed/sidecar && mkdir -p /volume1/docker/commoncreed/sidecar && tar xzf - -C /volume1/docker/commoncreed/sidecar'

# 3. Temporal dynamicconfig
tar czf - -C deploy/portainer/temporal-dynamicconfig . | \
  ssh -o BatchMode=yes vishalan@192.168.29.211 \
  'mkdir -p /volume1/docker/commoncreed/deploy/portainer/temporal-dynamicconfig && tar xzf - -C /volume1/docker/commoncreed/deploy/portainer/temporal-dynamicconfig'
```

**`.env` handling rule:** NEVER push the local `.env` directly. The skill checks whether `/volume1/docker/commoncreed/.env` exists on the NAS via SSH:
- If absent (first deploy): generate a production `.env` from the local one in a tmpfile, substitute `localhost` URLs with the NAS IP, set `POSTIZ_HOST_PORT=5100` (NOT 5000), upload via tar pipe, set mode 600, **immediately delete the local tmpfile**, never echo its contents to chat.
- If present (subsequent deploys): leave the NAS `.env` alone — it's production state owned by the operator (or eventually by the sidecar Settings page).

**`gmail_oauth.json`** uploaded the same way:
```bash
if [ -f secrets/gmail_oauth.json ]; then
  tar czf - -C secrets gmail_oauth.json | \
    ssh -o BatchMode=yes vishalan@192.168.29.211 \
    'tar xzf - -C /volume1/docker/commoncreed/secrets && chmod 600 /volume1/docker/commoncreed/secrets/gmail_oauth.json'
fi
```

**Verify uploads** with file COUNTS only — never `cat`/`head`/`tail` on `.env` or any secrets file (see `feedback_never_cat_dotenv` memory):
```bash
ssh vishalan@192.168.29.211 \
  'echo scripts: $(find /volume1/docker/commoncreed/scripts -type f | wc -l) files;
   echo sidecar: $(find /volume1/docker/commoncreed/sidecar -type f | wc -l) files;
   ls /volume1/docker/commoncreed/scripts/smoke_e2e.py /volume1/docker/commoncreed/sidecar/app.py /volume1/docker/commoncreed/sidecar/Dockerfile /volume1/docker/commoncreed/deploy/portainer/temporal-dynamicconfig/development-sql.yaml 2>&1;
   stat -c "%n size=%s mode=%a" /volume1/docker/commoncreed/.env'
```

### Phase 2.5 — Build the sidecar image on the NAS Docker daemon

Portainer's compose runner can't see `/volume1/` from inside its container, so a `build:` directive against a NAS path fails with `unable to prepare context`. The fix: build the image directly on the NAS Docker daemon via Portainer's image-build API, then reference it by tag in the deployed compose.

```bash
# Package the sidecar build context into a tar.gz
tar czf /tmp/cc_sidecar_build_ctx.tar.gz \
  --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '.pytest_cache' --exclude 'tests' \
  -C sidecar .

# POST the tar to Portainer's image-build endpoint
curl -sf -X POST \
  -H "Authorization: Bearer $PORTAINER_JWT" \
  -H "Content-Type: application/x-tar" \
  --data-binary @/tmp/cc_sidecar_build_ctx.tar.gz \
  "http://192.168.29.211:9000/api/endpoints/$ENDPOINT_ID/docker/build?t=commoncreed/sidecar:0.1.0&dockerfile=Dockerfile"
```

The response is a streaming JSON log of the docker build process. Parse it for the final `"Successfully built ..."` line. On any error during build, abort the deploy.

Subsequent deploys can reuse the cached layers — only changed source files cause rebuilds.

After build, **strip the `build:` block from the compose payload before sending it to Portainer**:
```python
import re
out = re.sub(
    r'  commoncreed_sidecar:\n    build:\n      context: [^\n]+\n      dockerfile: [^\n]+\n',
    '  commoncreed_sidecar:\n',
    compose_text,
)
```
The compose still has `image: commoncreed/sidecar:0.1.0` further down the service block, so removing only the `build:` lines is enough — Docker pulls the local image by tag.

### Phase 3 — Generate the deployable compose payload

Read `deploy/portainer/docker-compose.yml` from disk, transform relative paths to absolute NAS paths (Phase 0 step 3), and produce a single string ready for the Portainer API.

```python
# Pseudocode — implemented inline by the orchestrator
compose_text = open('deploy/portainer/docker-compose.yml').read()
replacements = {
  '../../scripts': '/volume1/docker/commoncreed/scripts',
  '../../sidecar': '/volume1/docker/commoncreed/sidecar',
  '../../.env': '/volume1/docker/commoncreed/.env',
  './temporal-dynamicconfig': '/volume1/docker/commoncreed/deploy/portainer/temporal-dynamicconfig',
  './postgres-init': '/volume1/docker/commoncreed/deploy/portainer/postgres-init',
}
for src, dst in replacements.items():
    compose_text = compose_text.replace(src, dst)
```

**Validate the result** by parsing it as YAML and confirming no `./` or `../` paths remain in any `volumes:` entry.

Also fetch the NAS `.env` content (via SSH) and pass it to Portainer alongside the compose. Portainer's stack create API accepts both as part of the payload.

### Phase 4 — Create or update the Portainer stack

If `EXISTING_STACK_ID` from Phase 1 is empty → CREATE:
```bash
curl -sf -X POST "http://192.168.29.211:9000/api/stacks/create/standalone/string?endpointId=$ENDPOINT_ID" \
  -H "Authorization: Bearer $PORTAINER_JWT" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg name 'commoncreed' \
    --arg compose "$COMPOSE_CONTENT" \
    --arg env "$ENV_FILE_CONTENT" \
    '{Name:$name, StackFileContent:$compose, Env:[]}')" \
  > .deploy-rollback/$(date +%Y%m%d-%H%M%S)-create-response.json
```

If it exists → UPDATE:
```bash
curl -sf -X PUT "http://192.168.29.211:9000/api/stacks/$EXISTING_STACK_ID?endpointId=$ENDPOINT_ID" \
  -H "Authorization: Bearer $PORTAINER_JWT" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg compose "$COMPOSE_CONTENT" \
    '{StackFileContent:$compose, Env:[], Prune:true}')" \
  > .deploy-rollback/$(date +%Y%m%d-%H%M%S)-update-response.json
```

Note: Portainer's update API does NOT pull updated images by default. To force a re-pull (e.g., after `latest` tag rotated), add `?pullImage=true` to the URL.

The API call is synchronous from Portainer's perspective but the underlying `docker compose up` continues asynchronously. Phase 5 polls for completion.

### Phase 5 — Wait for healthy

Poll the container list every 10 seconds until either:
- All 7 expected containers (`postgres`, `redis`, `temporal-postgres`, `temporal-elasticsearch`, `temporal`, `postiz`, `commoncreed_sidecar`) report `State.Status == "running"` AND `State.Health.Status == "healthy"`
- 6-minute timeout (Postiz alone has a 120s start_period; Elasticsearch ~60s; Temporal needs both before it boots)

```bash
deadline=$(($(date +%s) + 360))
while [ $(date +%s) -lt $deadline ]; do
  containers=$(curl -sf -H "Authorization: Bearer $PORTAINER_JWT" \
    "http://192.168.29.211:9000/api/endpoints/$ENDPOINT_ID/docker/containers/json?filters=%7B%22label%22%3A%5B%22com.docker.compose.project%3Dcommoncreed%22%5D%7D")
  unhealthy=$(echo "$containers" | python3 -c '
import json,sys
data=json.load(sys.stdin)
need={"commoncreed_postgres","commoncreed_redis","commoncreed_temporal_postgres","commoncreed_temporal_elasticsearch","commoncreed_temporal","commoncreed_postiz","commoncreed_sidecar"}
seen={c["Names"][0].lstrip("/"): (c.get("State","unknown"), (c.get("Status","") or "")) for c in data}
missing=need - set(seen.keys())
unhealthy=[n for n,(s,st) in seen.items() if "healthy" not in st and "Up" in st]
not_up=[n for n,(s,st) in seen.items() if "Up" not in st]
if missing: print(f"missing:{','.join(sorted(missing))}")
elif not_up: print(f"not_up:{','.join(sorted(not_up))}")
elif unhealthy: print(f"starting:{','.join(sorted(unhealthy))}")
else: print("ALL_HEALTHY")
')
  case "$unhealthy" in
    ALL_HEALTHY) echo "✓ all 7 containers healthy"; break ;;
    *) echo "  $(date +%H:%M:%S)  $unhealthy" ; sleep 10 ;;
  esac
done
```

If timeout fires, jump to Phase 7 (rollback).

### Phase 5.5 — Mandatory Temporal + Postiz restart dance

Even when all containers report healthy/running after Phase 5, Postiz's backend is almost certainly in a crash-restart loop because of gotcha #5+#6 (Temporal auto-setup races, Postiz cached the failed connection). You will see HTTP 502 from `POST /api/auth/register` with logs showing `ECONNREFUSED 7233` in the postiz container.

**This is not optional — every fresh deploy needs both restarts.**

```bash
# 1. Restart Temporal first so it transitions cleanly from auto-setup to server
TEMPORAL_CID=$(curl -sf -H "Authorization: Bearer $JWT" \
  "http://192.168.29.211:9000/api/endpoints/$ENDPOINT_ID/docker/containers/json?filters=%7B%22name%22%3A%5B%22commoncreed_temporal%22%5D%7D" \
  | python3 -c 'import json,sys; cc=json.load(sys.stdin); print([c for c in cc if c["Names"][0]=="/commoncreed_temporal"][0]["Id"])')

curl -sf -X POST -H "Authorization: Bearer $JWT" \
  "http://192.168.29.211:9000/api/endpoints/$ENDPOINT_ID/docker/containers/$TEMPORAL_CID/restart?t=10"

sleep 60  # Temporal needs ~30-60s to be fully serving on port 7233

# 2. Restart Postiz so its backend retries against the now-serving Temporal
POSTIZ_CID=$(curl -sf -H "Authorization: Bearer $JWT" \
  "http://192.168.29.211:9000/api/endpoints/$ENDPOINT_ID/docker/containers/json?filters=%7B%22name%22%3A%5B%22commoncreed_postiz%22%5D%7D" \
  | python3 -c 'import json,sys; cc=json.load(sys.stdin); print([c for c in cc if c["Names"][0]=="/commoncreed_postiz"][0]["Id"])')

curl -sf -X POST -H "Authorization: Bearer $JWT" \
  "http://192.168.29.211:9000/api/endpoints/$ENDPOINT_ID/docker/containers/$POSTIZ_CID/restart?t=10"

# 3. Poll the API until it returns 400 (validation error = backend up) instead of 502
for i in 1 2 3 4 5 6 7 8 9 10; do
  sleep 15
  code=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    http://192.168.29.211:5100/api/auth/register \
    -H "Content-Type: application/json" -d '{}')
  echo "  t+$((i*15))s: HTTP $code"
  [ "$code" = "400" ] || [ "$code" = "200" ] && { echo "✓ Postiz backend ready"; break; }
done
```

If after 150 seconds the API still returns 502, escalate: Temporal is genuinely broken. Look at temporal container logs for crashes after the search-attribute warnings, and check if `temporal-elasticsearch` is healthy.

### Phase 6 — Smoke verification

Once all containers are healthy, prove the actual application paths work:

```bash
# 1. Postiz frontend reachable
curl -sf -o /dev/null -w "Postiz auth page: HTTP %{http_code}\n" http://192.168.29.211:5000/auth

# 2. Postiz API responds (will be 400 because of missing fields, NOT 502)
curl -sf -o /tmp/r.json -w "Postiz register API: HTTP %{http_code}\n" \
  -X POST http://192.168.29.211:5000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{}' || true
grep -q "company\|email" /tmp/r.json && echo "  ✓ backend reachable (got validation error, not 502)"

# 3. Sidecar /health all flags green
curl -sf http://192.168.29.211:5050/health | python3 -m json.tool
```

All three must return non-error responses (Postiz API may legitimately return 400 with a validation error — that's a healthy backend). Sidecar `/health` must return 200 with all 5 flags `true`.

### Phase 7 — Rollback (only if Phase 5 or 6 fails)

If health verification or smoke test fails:

1. Print the failing service's last 100 log lines for diagnosis:
   ```bash
   curl -sf -H "Authorization: Bearer $PORTAINER_JWT" \
     "http://192.168.29.211:9000/api/endpoints/$ENDPOINT_ID/docker/containers/<container_id>/logs?stdout=true&stderr=true&tail=100"
   ```

2. If we have a rollback file from Phase 1, restore it:
   ```bash
   curl -sf -X PUT "http://192.168.29.211:9000/api/stacks/$EXISTING_STACK_ID?endpointId=$ENDPOINT_ID" \
     -H "Authorization: Bearer $PORTAINER_JWT" \
     -H "Content-Type: application/json" \
     -d "$(jq -n --arg compose "$(cat .deploy-rollback/<latest>-stack-file.json | jq -r '.StackFileContent')" '{StackFileContent:$compose, Env:[], Prune:true}')"
   ```

3. If no previous version (fresh deploy that failed), DOWN the stack so it doesn't sit in a half-broken state:
   ```bash
   curl -sf -X POST "http://192.168.29.211:9000/api/stacks/$NEW_STACK_ID/stop?endpointId=$ENDPOINT_ID" \
     -H "Authorization: Bearer $PORTAINER_JWT"
   ```

4. Report the failure with:
   - Which container failed
   - Log excerpt
   - Rollback status (success/no prior version/manual cleanup needed)
   - Suggested next debug step

### Phase 8 — Final report

On success, print a structured report:

```
✓ CommonCreed stack deployed to http://192.168.29.211:9000

Stack:           commoncreed (id: <id>, version: <n>)
Containers:      7/7 healthy
Postiz UI:       http://192.168.29.211:5000
Sidecar dashboard: http://192.168.29.211:5050
Sidecar admin password: (in Keychain — `security find-generic-password -a sidecar -s commoncreed-sidecar-admin -w`)

Next steps if first deploy:
  1. Open http://192.168.29.211:5000/auth and register the Postiz admin user
  2. Set DISABLE_REGISTRATION=true on the NAS .env, restart postiz container
  3. Connect IG/YT accounts via Postiz UI (each platform requires a Google Cloud / Meta Developer App — see docs/social-oauth-setup.md)
  4. Generate Postiz API key, paste into NAS .env as POSTIZ_API_KEY, restart commoncreed_sidecar
  5. Open http://192.168.29.211:5050 and log in to the sidecar dashboard
  6. Send a test message via the Telegram bot to confirm bot ↔ owner wiring

Logs:
  Tail any service:    /cc-deploy-portainer --logs <service>
  Quick status check:  /cc-deploy-portainer --status
  Roll back:           /cc-deploy-portainer --rollback
```

---

## Subcommand: `--update`

When the stack is already deployed and you need to push a fix (compose change, .env change, sidecar code change), use `--update` instead of a full deploy. This calls Portainer's PUT stack endpoint, which is faster and preserves named volumes / running state for unchanged services.

```python
# Pseudocode flow (real implementation: /tmp/cc_update_stack.py from the
# 2026-04-07 deploy session — copy into the skill's helpers/ on integration)
jwt = portainer_auth()
stack_id = find_stack_by_name(jwt, "commoncreed")
if stack_id is None:
    fail("no commoncreed stack — use full /cc-deploy-portainer instead")

# 1. If sidecar source changed, rebuild the sidecar image first via Phase 2.5
if sidecar_source_changed():
    rebuild_sidecar_image(jwt)

# 2. If pipeline code changed, re-tar+upload via Phase 2's tar-pipe pattern
if scripts_or_sidecar_changed():
    tar_upload_to_nas("scripts")
    tar_upload_to_nas("sidecar")

# 3. Regenerate prod compose payload (Phase 3 — strip ../../  to absolute paths,
#    strip the build: block from sidecar so it references the prebuilt image)
compose = regen_prod_compose("deploy/portainer/docker-compose.yml")

# 4. Fetch latest .env from NAS (silent, no echo)
env = ssh_read_env_silently()

# 5. PUT the updated stack
PUT /api/stacks/{stack_id}?endpointId=3
  body: {"stackFileContent": compose, "env": env, "prune": true}

# 6. If --restart=<services> was passed OR env vars changed, restart those
#    containers individually (env changes don't always trigger Portainer's
#    container recreate — explicit restart is the only reliable trigger)
for svc in args.restart_services:
    restart_container(jwt, svc)

# 7. Poll smoke test (Postiz API → 400, Sidecar /health → 200)
poll_until_healthy()
```

**When --update needs an explicit container restart:** any time you change an env var that's already in the compose `environment:` block, Portainer's stack PUT will update the env file on disk but the running container is not always recreated. Use `--restart` to force it. Examples:
- Added `NOT_SECURED=true` → restart `postiz`
- Rotated `ANTHROPIC_API_KEY` → restart `commoncreed_sidecar`
- Changed `POSTIZ_HOST_PORT` → must `--update` + recreate (port changes need a full container recreate, not just restart)

## Subcommand: `--logs`

Pull container logs through Portainer's REST API. This works even when SSH to the NAS is offline (e.g., when debugging from a different network via Tailscale).

```bash
# Single service, last 200 lines
SERVICE="commoncreed_postiz"
CID=$(curl -sf -H "Authorization: Bearer $JWT" \
  "http://192.168.29.211:9000/api/endpoints/3/docker/containers/json?all=true&filters=%7B%22name%22%3A%5B%22$SERVICE%22%5D%7D" \
  | python3 -c 'import json,sys; cc=json.load(sys.stdin); print([c for c in cc if c["Names"][0]==f"/$SERVICE"][0]["Id"])')

curl -sf -H "Authorization: Bearer $JWT" \
  "http://192.168.29.211:9000/api/endpoints/3/docker/containers/$CID/logs?stdout=true&stderr=true&tail=200&timestamps=true" \
  | strings | tail -100  # `strings` strips Docker's framed-stream multiplex bytes
```

The Docker logs API uses an 8-byte header per stream chunk (1 byte stream id, 3 reserved, 4 bytes length). `strings` strips them for human reading. For programmatic log parsing, use `python3 -c` with the Docker SDK's stream-frame parser.

**`--logs --all`** loops through every container with the `commoncreed` project label and prints the last 50 lines of each. Useful right after a deploy fails to surface ALL relevant errors at once.

**`--logs --follow`** uses the Portainer logs endpoint with `follow=true&stdout=true&stderr=true` to stream in real time. Only works for one service at a time. Ctrl-C to stop.

**Common log greps when debugging:**
```bash
# postiz: backend startup status
... | grep -iE "backend.*started|listening|port 3000|ECONN|temporal|Backend failed"

# postiz: cookie configuration (NOT_SECURED issue)
... | grep -iE "cookie|secure|not_secured"

# temporal: bootstrap completion
... | grep -iE "search attribute|frontend|listen|exit"

# sidecar: pipeline subprocess invocations
... | grep -iE "pipeline|subprocess|smoke_e2e|cost"

# any service: out-of-memory
... | grep -iE "OOM|killed|memory|signal"
```

## Debug → fix → redeploy loop

The most common workflow after the first deploy is "something broken in production, fix locally, push the fix, validate". The skill makes this a tight loop:

```bash
# 1. See the symptom in the browser (e.g., "Sign Up does nothing")
# 2. Pull the relevant logs
/cc-deploy-portainer --logs commoncreed_postiz

# 3. Find the root cause (e.g., cookie has Secure flag on HTTP)
# 4. Make the fix locally — edit deploy/portainer/docker-compose.yml or .env
# 5. Test the fix on Colima first if it's in compose
docker compose --env-file ../../.env up -d --force-recreate postiz

# 6. Once verified locally, push to NAS
/cc-deploy-portainer --update --restart=postiz

# 7. Verify the fix landed
/cc-deploy-portainer --logs commoncreed_postiz
# OR test the symptom in the browser
```

**Don't skip the local test in step 5.** Each round-trip to the NAS costs 1-3 minutes; iterating on Colima is 5-15 seconds. Use the NAS for VALIDATION, not for ITERATION.

## Helper script: `portainer_smoke.py`

The skill ships with `portainer_smoke.py` next to this `SKILL.md`. Run it any time you need a fast 4-check sanity test of the Portainer connection without doing a real deploy:

```
python3 .claude/skills/cc-deploy-portainer/portainer_smoke.py
```

Checks: Keychain auth → endpoint discovery → stack listing → container listing. All 4 must show ✓ before any real deploy attempt. This is a good first-thing-to-run after any network change, NAS reboot, or password rotation.

## Subcommand: `--dry-run`

Run Phase 0 only. Print what would be deployed. Show the diff between the local compose and the live NAS compose (if any). Do not touch the NAS or Portainer.

## Subcommand: `--rollback`

Auth → find current stack → load latest `.deploy-rollback/<ts>-stack-file.json` → PUT it back to Portainer → wait healthy → report.

## Subcommand: `--status`

Auth → list containers with the `commoncreed` project label → print a table with Name / State / Health / Uptime / Memory. No deploy actions.

## Subcommand: `--logs <svc>`

Auth → find container by name → fetch last 100 log lines via Portainer API → print.

---

## Rules

- **Password handling**: read from Keychain, store in shell variable for the duration of the API session, `unset` immediately after the last use. Never write to a file. Never echo.
- **Single source of truth for prod state is the NAS**, not the Mac. The Mac's `.env` is dev-only. The NAS `.env` is touched manually by the user (or via the sidecar Settings page once Unit 8 is wired) but never auto-overwritten by this skill.
- **Never auto-pull images on update without `--pull`**. Image rotation is a separate decision from code update; conflate them and you risk surprise breakage when `latest` shifts.
- **Always snapshot before update**. Even if the snapshot file is huge, disk is cheap and rollback safety is priceless.
- **Health check both Docker AND application layers**. Container `healthy` is necessary but not sufficient — Postiz can be `healthy` per its own healthcheck and still fail at the API layer (we hit this earlier with the 502/wget bug). Phase 6 catches that.
- **Refuse to deploy with uncommitted changes or failing tests.** Production deploys should be reproducible from the git ref; uncommitted changes mean the deploy isn't traceable.

## Common gotchas

| Symptom | Likely cause | Fix |
|---|---|---|
| `curl: (7) Failed to connect to 192.168.29.211 port 9000` | NAS off, wrong IP, firewall | Ping the NAS; check if Portainer is running |
| Auth returns 401 | Password rotated | Update Keychain entry: `security delete-generic-password -a vishalan -s commoncreed-portainer && security add-generic-password -a vishalan -s commoncreed-portainer -w '<new>'` |
| Stack create returns 500 with "duplicate name" | A `commoncreed` stack already exists but Phase 1 didn't find it (filter typo) | Manually find stack ID via `GET /api/stacks` and patch the EXISTING_STACK_ID variable |
| Phase 5 timeout: Postiz never goes healthy | First-pull of Postiz image takes long on slow networks; OR Temporal/ES not ready yet | Re-run with longer timeout; check Phase 6 logs for the actual error |
| `rsync: connection unexpectedly closed` | SSH key not set up; using password auth without `sshpass` | Set up SSH key auth: `ssh-copy-id vishalan@192.168.29.211` |
| Sidecar `/health` says `pipeline_code_visible: false` | Phase 2 rsync didn't reach `/volume1/docker/commoncreed/scripts/` OR the bind mount path in the deployed compose still has `../../scripts/` | Re-check Phase 0 step 3 transformation and re-run |
| Postiz UI blank but `/auth` returns 200 | Cookie domain mismatch — `MAIN_URL` in NAS .env is `localhost` instead of the NAS IP | Edit `/volume1/docker/commoncreed/.env`, fix `POSTIZ_MAIN_URL` and `POSTIZ_FRONTEND_URL`, restart postiz container |

## When NOT to use this skill

- Code is mid-development and not committed → stash or commit first
- You want to do a one-off command on the NAS (use direct `ssh vishalan@192.168.29.211` instead)
- The deploy is a brand-new install and the user hasn't created the NAS deploy directory yet → walk the user through `mkdir /volume1/docker/commoncreed/` manually first
- You're trying to debug why Postiz crashed at the application layer → use `--logs postiz` or SSH directly
- You want to RESTART a single service without redeploying → use the sidecar Settings page (Unit 8) or `ssh vishalan@192.168.29.211 docker compose -f /volume1/docker/commoncreed/deploy/portainer/docker-compose.yml restart <svc>`
