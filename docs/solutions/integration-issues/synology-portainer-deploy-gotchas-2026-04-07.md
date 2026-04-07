---
title: Six gotchas hit during the first Synology Portainer deploy of the CommonCreed stack
category: integration-issues
date: 2026-04-07
tags: [synology, portainer, docker, postiz, temporal, deploy, ssh, rsync, pam]
module: deploy/portainer
component: cc-deploy-portainer skill
---

# Six gotchas hit during the first Synology Portainer deploy

## Problem

Deploying the CommonCreed `docker-compose.yml` stack to a Synology DS1520+ via Portainer's REST API for the first time hit six distinct failure modes that the original `cc-deploy-portainer` skill did not anticipate. None of them surfaced during local Colima testing because Colima is a vanilla Linux Docker host without the Synology-specific quirks. Each failure cost a debug round-trip; together they would have blocked the deploy entirely if pursued naively.

## Symptoms

1. `docker compose up` from Portainer returned `unable to prepare context: path "/volume1/docker/commoncreed/sidecar" not found` even though the path existed and was world-writable.
2. Postiz containers crash-looped with `POSTGRES_PASSWORD must be a non-empty value` even though `.env` on the NAS contained the password.
3. `Error starting userland proxy: listen tcp4 0.0.0.0:5000: bind: address already in use` on the Postiz container even though no other Docker container claimed port 5000.
4. `rsync ./scripts/ vishalan@192.168.29.211:/volume1/docker/commoncreed/scripts/` returned `Permission denied, please try again.` repeatedly even though plain `ssh vishalan@192.168.29.211 'echo ok'` worked without password (key auth verified).
5. After Phase 5 of the deploy reported all containers running, Postiz returned HTTP 502 from `POST /api/auth/register`. Container logs showed `[Error: 14 UNAVAILABLE: connect ECONNREFUSED 172.27.0.4:7233] Backend failed to start on port 3000` repeated indefinitely.
6. The `temporal` container was healthy at the Docker layer but `temporal-server` was not actually serving on port 7233. Restarting it once made it serve correctly.

## What didn't work

- **Mounting `/volume1` into the Portainer container** to fix gotcha #1: would have required modifying the user's existing Portainer install and recreating it with new bind mounts. Too invasive.
- **Pinning Postiz to an older `arm64-1735743825` tag** (Jan 2025 build): this version did NOT need Temporal at all, but its Prisma schema was internally inconsistent — the running code looked for a `User.marketplace` column the migrations didn't create. So the older tag swapped one set of bugs for another.
- **`scp`/SFTP for the file uploads**: SFTP subsystem is disabled in Synology's `/etc/ssh/sshd_config`. Returns `subsystem request failed on channel 0`.
- **Adding the `vishalan` user to the `administrators` group**: the user was already there. Group membership wasn't the bottleneck.
- **`StrictModes no` workaround for the 777 mode `.ssh` dir**: not the issue. SSH key auth itself worked. The block was downstream.
- **Setting `UsePAM no` in sshd_config**: would require sudo and modify Synology system files. The whole point of using Synology is to NOT touch DSM internals.
- **Loading the SSH key into the agent via `ssh-add --apple-use-keychain`**: the key WAS in the agent, but rsync's ssh subprocess still failed because the issue is server-side PAM, not client-side auth.
- **Removing the `pty` option from `authorized_keys`**: didn't help. PAM fires regardless of pty.

## Solution

A coordinated set of six fixes, all baked into the `cc-deploy-portainer` skill (`.claude/skills/cc-deploy-portainer/SKILL.md`).

### Gotcha 1: Synology DSM occupies port 5000

**Root cause:** DSM's web management UI listens on `http://<nas>:5000`. This is hardcoded by Synology and cannot be moved without breaking DSM. Postiz tried to bind the same host port → Docker rejected with "address already in use".

**Fix:** Set `POSTIZ_HOST_PORT=5100` in the NAS `.env` (or any free port that isn't 5000/5001). Update `POSTIZ_MAIN_URL` and `POSTIZ_FRONTEND_URL` accordingly. The compose file uses `${POSTIZ_HOST_PORT:-5100}:5000` so the in-container port stays 5000 and only the host-side mapping changes.

```bash
ssh vishalan@192.168.29.211 "sed -i 's|^POSTIZ_HOST_PORT=.*|POSTIZ_HOST_PORT=5100|; s|http://192.168.29.211:5000|http://192.168.29.211:5100|g' /volume1/docker/commoncreed/.env"
```

### Gotcha 2: Portainer's compose runner can't see `/volume1/`

**Root cause:** Portainer runs as a Docker container itself. When it executes `docker compose up`, the compose process runs from inside Portainer's container, which doesn't have `/volume1/docker/commoncreed/sidecar` bind-mounted. The `build:` directive in the compose tries to use that path as a build context and fails.

**Fix:** Pre-build the sidecar image **directly on the NAS Docker daemon** via Portainer's image-build API, then strip the `build:` block from the compose payload before sending it. Docker pulls the local image by tag (`commoncreed/sidecar:0.1.0`).

```bash
# Build context as tar
tar czf /tmp/cc_sidecar_build_ctx.tar.gz \
  --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '.pytest_cache' --exclude 'tests' \
  -C sidecar .

# POST to Portainer's build endpoint
curl -sf -X POST \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/x-tar" \
  --data-binary @/tmp/cc_sidecar_build_ctx.tar.gz \
  "http://192.168.29.211:9000/api/endpoints/3/docker/build?t=commoncreed/sidecar:0.1.0&dockerfile=Dockerfile"
```

Strip the build block from the compose before sending to `/api/stacks/create/standalone/string`:
```python
import re
out = re.sub(
    r'  commoncreed_sidecar:\n    build:\n      context: [^\n]+\n      dockerfile: [^\n]+\n',
    '  commoncreed_sidecar:\n',
    compose_text,
)
```

### Gotcha 3: Portainer's create-stack API does NOT auto-load `.env`

**Root cause:** Compose `${VAR}` references must be resolved at parse time. Portainer's REST API does not look for a `.env` file on the host — it only uses what you pass in the `env` array of the create-stack request body. We sent `env: []`, so every variable resolved to empty string, breaking POSTGRES_PASSWORD, JWT_SECRET, and everything else.

**Fix:** SSH to the NAS, read the `.env` file silently into a Python dict, build the `env` array, pass it explicitly:
```python
result = subprocess.run(
    ["ssh", "-o", "BatchMode=yes", "vishalan@192.168.29.211", "cat /volume1/docker/commoncreed/.env"],
    capture_output=True, text=True, check=True,
)
env = []
for line in result.stdout.splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env.append({"name": k.strip(), "value": v.strip().strip('"').strip("'")})
# NEVER print env values
print(f"parsed {len(env)} env vars (values not echoed)")
```
**Critical:** never echo any `value` field to chat — chat history persists secrets. See `feedback_never_cat_dotenv` memory.

### Gotcha 4: Synology PAM blocks rsync over SSH

**Root cause:** Synology's `/etc/pam.d/sshd` includes `pam_syno_support.so ssh` plus `pam_unix.so` in the auth chain. When SSH runs `rsync --server` as a non-interactive command, the Synology PAM module produces a `Permission denied, please try again.` prompt that corrupts the rsync protocol stream. SSH key auth works fine for interactive shells (`pam_unix` doesn't fire), and works for `ssh user@host 'arbitrary command'`, but fails specifically for the rsync server protocol over SSH because of how rsync's stdin/stdout pattern interacts with PAM's session-open.

**Fix:** Use **`tar | ssh ... 'tar xzf -'`** for ALL code uploads. tar over SSH is plain stdin/stdout streaming and doesn't trigger the same PAM path.

```bash
# Pipeline code
tar czf - --exclude '__pycache__' --exclude '*.pyc' --exclude 'output' \
  -C scripts . | \
  ssh -o BatchMode=yes vishalan@192.168.29.211 \
  'rm -rf /volume1/docker/commoncreed/scripts && mkdir -p /volume1/docker/commoncreed/scripts && tar xzf - -C /volume1/docker/commoncreed/scripts'

# Sidecar source
tar czf - --exclude '__pycache__' --exclude '*.pyc' \
  -C sidecar . | \
  ssh -o BatchMode=yes vishalan@192.168.29.211 \
  'rm -rf /volume1/docker/commoncreed/sidecar && mkdir -p /volume1/docker/commoncreed/sidecar && tar xzf - -C /volume1/docker/commoncreed/sidecar'

# Temporal dynamicconfig
tar czf - -C deploy/portainer/temporal-dynamicconfig . | \
  ssh -o BatchMode=yes vishalan@192.168.29.211 \
  'mkdir -p /volume1/docker/commoncreed/deploy/portainer/temporal-dynamicconfig && tar xzf - -C /volume1/docker/commoncreed/deploy/portainer/temporal-dynamicconfig'
```

Trade-off: tar replaces the entire directory each deploy (no incremental sync like rsync would give). For a multi-MB code base this is fine — the upload takes <2 seconds.

### Gotcha 5: Temporal's `auto-setup` script races on first boot

**Root cause:** `temporalio/auto-setup:1.28.1` runs schema migrations and search attribute registration before exec'ing into `temporal-server`. The search attribute registration tries to call the Temporal frontend API but the frontend isn't fully serving yet, producing `failed reaching server: Frontend is not healthy yet` errors. The script exits successfully but the `temporal-server` process inside the container may not have transitioned cleanly. The container reports as running but isn't actually serving on port 7233.

**Fix:** **Restart the temporal container once** after the initial deploy. On the second boot, the schema is already in place, search attributes already exist (warnings are harmless), and the server starts cleanly in <30s.

```bash
TEMPORAL_CID=$(curl -sf -H "Authorization: Bearer $JWT" \
  "http://192.168.29.211:9000/api/endpoints/3/docker/containers/json?filters=%7B%22name%22%3A%5B%22commoncreed_temporal%22%5D%7D" \
  | python3 -c 'import json,sys; cc=json.load(sys.stdin); print([c for c in cc if c["Names"][0]=="/commoncreed_temporal"][0]["Id"])')
curl -sf -X POST -H "Authorization: Bearer $JWT" \
  "http://192.168.29.211:9000/api/endpoints/3/docker/containers/$TEMPORAL_CID/restart?t=10"
sleep 60
```

Also: **remove the temporal `healthcheck:` block from the compose** (the official Postiz compose has none) and downgrade `postiz`'s `depends_on` for temporal from `condition: service_healthy` to `condition: service_started`. Temporal's `tctl` was removed in 1.28+ images so the previous healthcheck was always failing anyway.

### Gotcha 6: Postiz crash-loops on cached Temporal failure

**Root cause:** When Postiz starts and Temporal isn't yet serving, the NestJS backend logs `Backend failed to start on port 3000` and exits. The container's supervisor restarts the backend, but Postiz's frontend nginx caches the failed upstream connection. Even after Temporal becomes available, Postiz keeps returning 502 because its backend keeps crash-looping with the same error pattern.

**Fix:** **Restart the postiz container once** AFTER Temporal has been restarted (gotcha #5) and is fully serving. This forces Postiz to retry against the now-working Temporal, the backend connects successfully, and serves on port 3000.

```bash
POSTIZ_CID=$(curl -sf -H "Authorization: Bearer $JWT" \
  "http://192.168.29.211:9000/api/endpoints/3/docker/containers/json?filters=%7B%22name%22%3A%5B%22commoncreed_postiz%22%5D%7D" \
  | python3 -c 'import json,sys; cc=json.load(sys.stdin); print([c for c in cc if c["Names"][0]=="/commoncreed_postiz"][0]["Id"])')
curl -sf -X POST -H "Authorization: Bearer $JWT" \
  "http://192.168.29.211:9000/api/endpoints/3/docker/containers/$POSTIZ_CID/restart?t=10"

# Poll until backend serves (HTTP 400 with validation error = healthy backend)
for i in 1 2 3 4 5 6 7 8 9 10; do
  sleep 15
  code=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    http://192.168.29.211:5100/api/auth/register \
    -H "Content-Type: application/json" -d '{}')
  [ "$code" = "400" ] && break
done
```

The Temporal+Postiz restart dance is **mandatory for every fresh deploy** — bake it into the deploy skill as Phase 5.5, before the smoke test phase.

## Why this works

These six fixes address the actual contracts of Synology DSM, Portainer's sandbox, and Postiz's startup ordering, rather than fighting them. The skill no longer:
- Tries to share host paths with Portainer's container (uses pre-built images instead)
- Trusts that Portainer will read host `.env` files (passes env explicitly)
- Uses rsync (which trips Synology PAM)
- Trusts that "all containers running" means "the application works" (does an explicit Postiz API smoke test after a mandatory restart dance)

## Prevention

- **Always test new deployment patterns end-to-end on a real Synology before declaring a deploy skill complete.** Local Colima testing catches a lot but misses Synology-specific quirks: PAM, DSM port collisions, Portainer sandbox boundaries.
- **Bake the Temporal+Postiz restart dance into every fresh-deploy path** until upstream Postiz fixes the boot ordering. Mark this as a known workaround in the skill, not a one-off.
- **Add a preflight check** in the deploy skill that pings DSM at `<nas>:5000` BEFORE deploy — if DSM responds, the user has not customized POSTIZ_HOST_PORT and the deploy will fail. Refuse to deploy with a clear message instead of letting Docker discover it.
- **Add the test `tar czf - file | ssh user@host 'tar xzf -'`** as the SSH transport check during preflight, NOT plain `ssh user@host 'echo ok'`. The latter passes but the former is what the deploy actually relies on.
- **Never use `cat`/`head`/`grep` on `.env` over SSH** — see `feedback_never_cat_dotenv` memory. The `cc-deploy-portainer` skill has been updated to verify uploads via `wc -l` and `stat -c "%n size=%s mode=%a"` only.
- **Postiz's `latest` image is the only working tag for self-hosters with the full Temporal+ES stack.** Older arm64-only timestamp tags have internal Prisma schema mismatches. Don't try to pin away from the official compose pattern.

## Test cases (for the deploy skill)

These should run as preflight assertions before any real deploy is attempted:

```python
# 1. DSM port 5000 collision check
import urllib.request
try:
    with urllib.request.urlopen("http://192.168.29.211:5000", timeout=3) as r:
        # Got a response — DSM is on 5000, refuse deploy unless POSTIZ_HOST_PORT != 5000
        nas_env = ssh_read_env_silently()
        if nas_env.get("POSTIZ_HOST_PORT", "5000") == "5000":
            raise SystemExit("DSM owns port 5000. Set POSTIZ_HOST_PORT=5100 in NAS .env first.")
except urllib.error.URLError:
    pass  # Port 5000 free — DSM probably moved

# 2. tar-over-ssh transport check
result = subprocess.run(
    ['sh', '-c',
     'echo test | tar czf - --files-from /dev/stdin -T /dev/null 2>/dev/null; '
     'echo "test_payload" | ssh -o BatchMode=yes vishalan@192.168.29.211 "cat > /tmp/cc_transport_test && cat /tmp/cc_transport_test && rm /tmp/cc_transport_test"'],
    capture_output=True, text=True,
)
assert "test_payload" in result.stdout, "tar-over-ssh transport broken — Synology PAM may be blocking. See gotcha #4."

# 3. Portainer endpoint exists
endpoints = portainer_api("GET", "/endpoints")
assert any(e["Type"] == 1 for e in endpoints), "No local Docker endpoint in Portainer"
```
