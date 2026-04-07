---
name: cc-deploy-portainer
description: End-to-end deploy of the CommonCreed stack to the Synology DS1520+ Portainer instance. Handles preflight, SSH-based code+secrets upload, Portainer REST API stack create/update, container health verification, and rollback on failure. Use whenever you need to push the stack to production.
---

# cc-deploy-portainer

Deploy or update the CommonCreed `docker-compose.yml` stack on the owner's Synology DS1520+ via Portainer's REST API. No browser interaction required — Portainer is fully API-driven.

## Usage

```
/cc-deploy-portainer                # full fresh deploy or in-place update
/cc-deploy-portainer --dry-run      # preflight + show what would happen, no changes
/cc-deploy-portainer --rollback     # restore the previous stack version (uses Portainer's stack history)
/cc-deploy-portainer --logs <svc>   # tail the last 100 lines of one service after deploy
/cc-deploy-portainer --status       # quick health check of the running stack, no deploy
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
| Stack name in Portainer | `commoncreed` | constant |

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

### Phase 2 — Upload code and secrets to the NAS

The compose file's bind mounts reference:
- `/volume1/docker/commoncreed/scripts/` — pipeline code
- `/volume1/docker/commoncreed/sidecar/` — sidecar service source
- `/volume1/docker/commoncreed/deploy/portainer/temporal-dynamicconfig/` — Temporal config
- `/volume1/docker/commoncreed/.env` — secrets
- `/volume1/docker/commoncreed/secrets/gmail_oauth.json` — Gmail OAuth token (if Unit 3 fully configured)

Upload everything via `rsync` over SSH. This is incremental — only changed files transfer on subsequent deploys.

```bash
# 1. Ensure deploy dir exists on NAS
ssh vishalan@192.168.29.211 'mkdir -p /volume1/docker/commoncreed/secrets && chmod 700 /volume1/docker/commoncreed/secrets'

# 2. Sync pipeline code (scripts/)
rsync -avz --delete \
  --exclude '__pycache__' --exclude '*.pyc' \
  --exclude 'output' --exclude 'tmp*' \
  ./scripts/ vishalan@192.168.29.211:/volume1/docker/commoncreed/scripts/

# 3. Sync sidecar source
rsync -avz --delete \
  --exclude '__pycache__' --exclude '*.pyc' --exclude 'tests' \
  ./sidecar/ vishalan@192.168.29.211:/volume1/docker/commoncreed/sidecar/

# 4. Sync deploy config (temporal-dynamicconfig)
rsync -avz --delete \
  ./deploy/portainer/temporal-dynamicconfig/ vishalan@192.168.29.211:/volume1/docker/commoncreed/deploy/portainer/temporal-dynamicconfig/

# 5. Sync .env (single file, special handling — only push if user confirms)
# IMPORTANT: this overwrites the NAS .env. Confirm with the user first.
# Better default: warn that the local .env and NAS .env are different files
# and the user should manage them separately. The skill should NEVER auto-push
# the local .env to the NAS without explicit confirmation, because the local
# .env may have dev-only values (localhost URLs, test API keys) that would
# break production.

# 6. Sync gmail_oauth.json if it exists locally
if [ -f secrets/gmail_oauth.json ]; then
  scp secrets/gmail_oauth.json vishalan@192.168.29.211:/volume1/docker/commoncreed/secrets/
  ssh vishalan@192.168.29.211 'chmod 600 /volume1/docker/commoncreed/secrets/gmail_oauth.json'
fi
```

**.env handling rule:** the skill must NOT push the local `.env` to the NAS automatically. Instead it checks whether `/volume1/docker/commoncreed/.env` exists on the NAS via SSH. If absent, it generates a fresh `.env.synology` template locally (copying from `.env.example` with `localhost` URLs replaced by the NAS IP) and instructs the user to fill it in manually on the NAS the first time. On subsequent deploys, the NAS `.env` is treated as production state and never overwritten.

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
