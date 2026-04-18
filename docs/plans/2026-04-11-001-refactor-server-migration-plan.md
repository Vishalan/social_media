---
title: "refactor: Migrate CommonCreed stack from Synology NAS to Ubuntu server"
type: refactor
status: completed
date: 2026-04-11
completed_at: 2026-04-19
completion_evidence: "Production running on Ubuntu 192.168.29.237 for ≥36h as of 2026-04-19 per docker ps. cc-deploy-portainer helpers migrated Synology→Ubuntu (commit 9a643a7). Sidecar + Postiz + Temporal + Elasticsearch + Postgres stack all healthy under the new host."
origin: docs/ideas/move_to_another_server.md
---

# refactor: Migrate CommonCreed stack from Synology NAS to Ubuntu server

## Overview

Move the entire CommonCreed Docker stack (Postiz + Temporal + sidecar) from the Synology DS1520+ NAS (192.168.29.211, Celeron J4125 / 8 GB / no GPU) to a dedicated Ubuntu server (192.168.29.237, Ryzen 5 3600X / 16 GB / RTX 2070 SUPER 8 GB). The new server has 4x the CPU cores, 2x the RAM, and a capable GPU — eliminating the NAS performance bottlenecks that prompted this move.

## Problem Frame

The Synology NAS (4-core Celeron, 8 GB RAM) is underpowered for the growing pipeline: ffmpeg transcoding, Pillow overlays, and APScheduler jobs contend for CPU, and the generative pipeline occasionally hits BrokenPipeError from resource exhaustion. The new Ubuntu server with NVIDIA GPU unlocks local model inference (ComfyUI, EchoMimic) that previously required cloud GPU rental.

## Requirements Trace

- R1. All 7 Docker services running on the new server with identical behavior
- R2. OAuth integrations (YouTube, Instagram/Facebook, Gmail) working with updated redirect URIs
- R3. Existing Postiz data (connected accounts, scheduled posts, tokens) preserved via Postgres dump/restore
- R4. Sidecar SQLite DB (pipeline runs, meme candidates, approvals) migrated
- R5. Secrets (`.env`, `gmail_oauth.json`) transferred securely
- R6. Deploy scripts (`cc_update_stack.py`, `cc_logs.py`, `SKILL.md`) updated for new server
- R7. Tailscale Funnel / DNS updated so external callbacks reach the new server
- R8. Old NAS stack torn down only after full verification on new server
- R9. Step-by-step walkthrough for OAuth redirect URL updates (YouTube, Gmail, Facebook)

## Scope Boundaries

- **In scope:** Docker stack migration, data migration, OAuth reconfiguration, deploy script updates, DNS cutover, NAS teardown
- **Out of scope:** GPU-accelerated pipeline work (ComfyUI/EchoMimic setup) — separate plan after migration lands
- **Out of scope:** Changing the application architecture — this is a lift-and-shift with path updates only
- **Out of scope:** CI/CD setup — deploy remains manual via `cc_update_stack.py`

## Context & Research

### Relevant Code and Patterns

- `deploy/portainer/docker-compose.yml` — 7 services, 8 named volumes, 2 networks
- `.claude/skills/cc-deploy-portainer/cc_update_stack.py` — hardcoded `192.168.29.211`, path transforms from `../../` to `/volume1/docker/commoncreed/`
- `.claude/skills/cc-deploy-portainer/cc_logs.py` — hardcoded `192.168.29.211`
- `.claude/skills/cc-deploy-portainer/SKILL.md` — 30+ hardcoded IP references
- `deploy/portainer/.env.example` — full env var template
- `sidecar/Dockerfile` — Python 3.11-slim, dual venvs, ffmpeg, Playwright
- `sidecar/gmail_client.py` — reads `GMAIL_OAUTH_PATH`, uses refresh_token (headless)
- `sidecar/postiz_client.py` — connects via Docker internal DNS (`http://postiz:5000`)

### Key Differences: Synology → Ubuntu

| Aspect | Synology NAS | Ubuntu Server |
|--------|-------------|---------------|
| Base path | `/volume1/docker/commoncreed/` | `/opt/commoncreed/` |
| Portainer URL | `http://192.168.29.211:9000` | `https://192.168.29.237:9443` |
| Portainer auth | HTTP on port 9000 | HTTPS on port 9443 (self-signed) |
| Tailscale DNS | `vishalan-nas.tail0f3d70.ts.net` | `commoncreed-server.tail47ec78.ts.net` |
| GPU | None | RTX 2070 SUPER (NVIDIA Container Toolkit installed) |
| Keychain label | `commoncreed-portainer` | Same label, updated password |
| DSM port conflict | Port 5000 used by DSM | No conflict — Postiz can use 5000 |

## Key Technical Decisions

- **Base path `/opt/commoncreed/`**: Standard Linux convention for self-contained apps. Avoids mixing with user home. Matches the pattern of `/volume1/docker/commoncreed/` but Ubuntu-native.
- **Portainer HTTPS on 9443**: Already configured on the new server. Deploy scripts must use `https://` and handle self-signed cert (`verify=False` or import CA).
- **Postgres dump/restore over volume copy**: Postgres data is not portable across different Docker volume drivers. `pg_dump` / `pg_restore` is the safe path.
- **Same `.env` file, updated URLs only**: Minimizes risk. API keys, tokens, secrets all stay the same. Only `POSTIZ_MAIN_URL`, `POSTIZ_FRONTEND_URL`, and path references change.
- **Sequential cutover, not parallel**: Run both stacks simultaneously during validation window, then DNS cutover + NAS teardown. Avoids split-brain with Postiz tokens.

## Open Questions

### Resolved During Planning

- **Postiz port on Ubuntu?** → Use 5000 (no DSM conflict). `POSTIZ_HOST_PORT=5000`.
- **Gmail OAuth needs re-auth?** → No. Token-based with refresh_token, no redirect URL involved. Just copy `gmail_oauth.json`.
- **Temporal data needs migration?** → No. Temporal stores workflow execution history which is ephemeral. Fresh start is fine.
- **Elasticsearch data?** → No. Temporal visibility store, rebuild on demand.

### Deferred to Implementation

- **Exact Portainer stack ID on new server**: Query at runtime during first deploy.
- **Whether self-signed TLS on Portainer 9443 needs cert import or `verify=False`**: Test during script update.

## Implementation Units

### Phase 1: Prepare New Server

- [ ] **Unit 1: Create directory structure + transfer files**

**Goal:** Set up `/opt/commoncreed/` on the new server with all project files, secrets, and assets.

**Requirements:** R1, R5

**Dependencies:** None (server already has Docker + Portainer + Tailscale)

**Files:**
- Create on server: `/opt/commoncreed/{scripts,sidecar,assets,secrets,deploy,db,output}/`
- Transfer: `.env`, `gmail_oauth.json`, `deploy/portainer/*`

**Approach:**
- `rsync` the project tree from dev machine (or NAS) to `/opt/commoncreed/`
- Copy `.env` from NAS, update `POSTIZ_MAIN_URL` and `POSTIZ_FRONTEND_URL` to new Tailscale DNS or LAN IP
- Copy `gmail_oauth.json` to `/opt/commoncreed/secrets/`
- Set ownership: `chown -R $USER:docker /opt/commoncreed/`

**Verification:**
- All directories exist with correct permissions
- `.env` readable, secrets present, no stale NAS paths

---

- [ ] **Unit 2: Migrate Postiz Postgres data**

**Goal:** Export Postiz database from NAS Postgres, import on new server so all connected accounts, OAuth tokens, and scheduled posts survive.

**Requirements:** R3

**Dependencies:** Unit 1

**Files:**
- Source: NAS container `commoncreed_postgres`
- Target: New server's `commoncreed_postgres` container

**Approach:**
- On NAS: `docker exec commoncreed_postgres pg_dump -U postiz -Fc postiz > /tmp/postiz_backup.dump`
- Transfer dump file to new server via `scp`
- Start only Postgres on new server first: `docker compose up -d postgres`
- Restore: `docker exec -i commoncreed_postgres pg_restore -U postiz -d postiz --clean --if-exists < /tmp/postiz_backup.dump`
- Verify row counts in `Integration`, `Post`, `User` tables

**Verification:**
- `SELECT count(*) FROM "Integration"` matches NAS count
- `SELECT count(*) FROM "Post"` matches NAS count
- Connected platform tokens are intact (verified in Unit 5)

---

- [ ] **Unit 3: Migrate sidecar SQLite DB**

**Goal:** Copy the sidecar SQLite database so pipeline run history, meme candidates, approvals, and denylist survive.

**Requirements:** R4

**Dependencies:** Unit 1

**Files:**
- Source: NAS volume `commoncreed_sidecar_db` → `sidecar.sqlite3`
- Target: `/opt/commoncreed/db/sidecar.sqlite3`

**Approach:**
- On NAS: `docker cp commoncreed_sidecar:/app/db/sidecar.sqlite3 /tmp/sidecar.sqlite3`
- Transfer to new server: `scp /tmp/sidecar.sqlite3 vishalan@192.168.29.237:/opt/commoncreed/db/`
- Verify integrity: `sqlite3 /opt/commoncreed/db/sidecar.sqlite3 "SELECT count(*) FROM pipeline_runs; SELECT count(*) FROM meme_candidates;"`

**Verification:**
- SQLite opens without corruption errors
- Row counts match NAS

---

### Phase 2: Update Deploy Scripts

- [ ] **Unit 4: Update `cc_update_stack.py` for new server**

**Goal:** Point the deploy script at the new Ubuntu server's Portainer instance with correct paths.

**Requirements:** R6

**Dependencies:** Unit 1

**Files:**
- Modify: `.claude/skills/cc-deploy-portainer/cc_update_stack.py`

**Approach:**
- Change `PORTAINER` from `http://192.168.29.211:9000` to `https://192.168.29.237:9443`
- Handle self-signed TLS: add `verify=False` to requests calls (or import cert)
- Update `NAS_HOST` to `192.168.29.237`
- Update `NAS_ENV_PATH` from `/volume1/docker/commoncreed/.env` to `/opt/commoncreed/.env`
- Update path transforms in `regen_prod_compose()`:
  - `../../scripts` → `/opt/commoncreed/scripts`
  - `../../assets` → `/opt/commoncreed/assets`
  - `../../secrets` → `/opt/commoncreed/secrets`
  - `../../sidecar` → `/opt/commoncreed/sidecar`
  - `../../.env` → `/opt/commoncreed/.env`
  - `./postiz-nginx.conf` → `/opt/commoncreed/deploy/portainer/postiz-nginx.conf`
  - `./temporal-dynamicconfig` → `/opt/commoncreed/deploy/portainer/temporal-dynamicconfig`
- Update Postiz health-check URL to new server IP
- Update macOS Keychain: store new Portainer password under same `commoncreed-portainer` label
- Update `ENDPOINT_ID` — query from new Portainer at runtime

**Patterns to follow:**
- Existing `regen_prod_compose()` pattern of string replacement

**Verification:**
- `cc_update_stack.py` runs without connection errors against new Portainer
- Generated compose payload has all `/opt/commoncreed/` paths

---

- [ ] **Unit 5: Update `cc_logs.py` and `SKILL.md`**

**Goal:** Update remaining deploy tooling references to new server.

**Requirements:** R6

**Dependencies:** Unit 4

**Files:**
- Modify: `.claude/skills/cc-deploy-portainer/cc_logs.py`
- Modify: `.claude/skills/cc-deploy-portainer/SKILL.md`

**Approach:**
- `cc_logs.py`: replace `192.168.29.211` with `192.168.29.237`, port `9000` → `9443`, `http` → `https`
- `SKILL.md`: bulk replace all `192.168.29.211` → `192.168.29.237`, update port and protocol references, update `/volume1/docker/commoncreed/` → `/opt/commoncreed/`

**Verification:**
- `grep -r "192.168.29.211" .claude/skills/` returns zero matches
- `grep -r "/volume1/docker" .claude/skills/` returns zero matches

---

### Phase 3: Deploy + Verify Stack

- [ ] **Unit 6: Build sidecar image + deploy full stack on new server**

**Goal:** Build the sidecar Docker image on the new server and bring up all 7 services.

**Requirements:** R1

**Dependencies:** Units 1-5

**Files:**
- Use: `cc_update_stack.py` (updated in Unit 4)
- Use: `sidecar/Dockerfile`

**Approach:**
- Build sidecar image via Portainer build API (same tar-upload pattern as NAS, but against new server)
- Run `cc_update_stack.py` to deploy the full stack
- Verify all 7 containers are running: `cc_logs.py` should show all healthy
- Verify Postiz UI accessible at `http://192.168.29.237:5000`
- Verify sidecar health endpoint: `curl http://192.168.29.237:5050/health`
- Verify Postiz connected accounts still show YouTube + Instagram

**Verification:**
- All 7 containers running (no restart loops)
- `/health` returns 200 with all subsystems OK
- Postiz UI loads and shows connected channels

---

### Phase 4: OAuth Redirect URL Updates (Walkthrough)

- [ ] **Unit 7: Update OAuth redirect URIs across all platforms**

**Goal:** Update all OAuth redirect URIs so social platform callbacks reach the new server.

**Requirements:** R2, R7, R9

**Dependencies:** Unit 6

**Files:**
- External: Google Cloud Console, Facebook Developer Console
- Modify on server: `.env` (`POSTIZ_MAIN_URL`, `POSTIZ_FRONTEND_URL`)

**Approach — step-by-step walkthrough:**

**A. Update `.env` on new server:**
```
POSTIZ_MAIN_URL=http://192.168.29.237:5000
POSTIZ_FRONTEND_URL=http://192.168.29.237:5000
```
(Or use Tailscale DNS: `https://commoncreed-server.tail47ec78.ts.net:5000` if external access needed)

**B. YouTube (Google Cloud Console):**
1. Go to https://console.cloud.google.com/apis/credentials
2. Select project `commoncreed-pipeline`
3. Click on the OAuth 2.0 Client ID used by Postiz
4. Under "Authorized redirect URIs":
   - Remove: `http://192.168.29.211:5000` (old NAS)
   - Add: `http://192.168.29.237:5000`
   - Add: `http://192.168.29.237:5000/integrations/social/youtube`
5. Save
6. In Postiz UI: disconnect + reconnect YouTube to re-authorize with new redirect

**C. Gmail (Google Cloud Console):**
- No redirect URI change needed — Gmail uses Desktop OAuth (refresh token), not web redirect
- The existing `gmail_oauth.json` with its refresh_token works from any server
- Verify: sidecar health ping should show gmail as reachable

**D. Facebook / Instagram:**
1. Go to https://developers.facebook.com/apps/
2. Select the CommonCreed app (App ID: `880552085041070`)
3. Settings → Basic → App Domains: add `192.168.29.237` (or Tailscale DNS)
4. Facebook Login → Settings → Valid OAuth Redirect URIs:
   - Remove: old NAS URI
   - Add: `http://192.168.29.237:5000`
   - Add: `http://192.168.29.237:5000/integrations/social/facebook`
5. Save
6. In Postiz UI: disconnect + reconnect Instagram/Facebook

**E. Tailscale DNS (if using Tailscale Funnel for external access):**
- The new server already has Tailscale with DNS `commoncreed-server.tail47ec78.ts.net`
- If Postiz needs public HTTPS callback, enable Tailscale Funnel on new server:
  `tailscale funnel 5000`
- Update OAuth redirect URIs to use `https://commoncreed-server.tail47ec78.ts.net:5000`

**F. Telegram Bot:**
- No change needed — Telegram bot uses polling (not webhooks), so it works from any server
- Bot token stays the same in `.env`

**Verification:**
- Postiz Channels page shows YouTube + Instagram as "Connected"
- Test: schedule a dummy post via sidecar, verify it appears in Postiz queue
- Test: meme trigger sends previews to Telegram with working Approve/Reject buttons

---

### Phase 5: Validation + Teardown

- [ ] **Unit 8: End-to-end smoke test on new server**

**Goal:** Run the full pipeline end-to-end on the new server to confirm everything works.

**Requirements:** R1, R2, R3, R4

**Dependencies:** Unit 7

**Files:**
- Run: meme trigger, pipeline trigger, Telegram approval flow

**Approach:**
- Run `run_meme_trigger()` via sidecar exec — verify candidates surfaced to Telegram with audio
- Approve one meme — verify it publishes to Postiz with CommonCreed watermark
- Check sidecar dashboard at `http://192.168.29.237:5050/dashboard`
- Verify scheduler jobs are running: `process_pending_runs`, `health_ping`, `retention_job`
- Verify Gmail topic source works (if `SIDECAR_DAILY_TRIGGER_ENABLED=1`)

**Verification:**
- Meme published successfully via Postiz
- Dashboard loads with historical data from migrated SQLite
- Health endpoint shows all subsystems green
- Telegram bot responsive

---

- [ ] **Unit 9: Tear down NAS stack**

**Goal:** Remove the CommonCreed stack from the Synology NAS after confirming the new server is fully operational.

**Requirements:** R8

**Dependencies:** Unit 8 (must pass completely)

**Files:**
- NAS Portainer: delete stack
- NAS filesystem: `/volume1/docker/commoncreed/`

**Approach:**
- Wait 24-48 hours after Unit 8 passes to catch any missed cron issues
- On NAS Portainer: stop all containers in the commoncreed stack
- Delete the stack from Portainer
- Remove Docker volumes: `docker volume rm commoncreed_postgres_data commoncreed_postiz_uploads ...`
- Archive `.env` and `secrets/` from NAS to local backup (do NOT delete secrets until verified on new server)
- Remove `/volume1/docker/commoncreed/` directory
- Update memory/project notes to reflect new server as production

**Verification:**
- No commoncreed containers running on NAS
- New server has been sole production for 24+ hours without issues

---

- [ ] **Unit 10: Update project documentation + memory**

**Goal:** Update all project references to reflect the new server.

**Requirements:** R6

**Dependencies:** Unit 9

**Files:**
- Modify: `deploy/portainer/README.md` (update IP, paths, Portainer URL)
- Modify: `deploy/portainer/.env.example` (update example URLs)
- Modify: project memory files referencing NAS

**Approach:**
- Replace all `192.168.29.211` → `192.168.29.237` in documentation
- Replace `/volume1/docker/commoncreed/` → `/opt/commoncreed/` in documentation
- Update Portainer URL references from `http://:9000` to `https://:9443`
- Update CLAUDE.md if it references the NAS
- Update auto-memory files (`project_synology_portainer.md`, `project_posting_layer.md`)

**Verification:**
- `grep -r "192.168.29.211" docs/ deploy/ CLAUDE.md` returns zero matches
- `grep -r "/volume1/docker" docs/ deploy/` returns zero matches

## System-Wide Impact

- **OAuth tokens:** Postiz Postgres stores all platform OAuth tokens. The Postgres dump/restore preserves them, but redirect URI changes in external consoles are mandatory for re-auth flows.
- **Scheduler jobs:** APScheduler with SQLite jobstore at `scheduler.sqlite3` — migrated alongside the sidecar DB. Jobs re-register on startup, so a fresh jobstore also works.
- **Telegram bot:** Polling-based, no server-side config needed. Works from any IP.
- **NAS heavy work lock (`nas_heavy_work_lock`):** In-memory asyncio.Lock in sidecar runtime — reset on restart, no migration needed.
- **Tailscale:** New server has its own Tailscale identity. If Funnel was used on NAS, it must be re-enabled on new server.

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Postiz Postgres dump fails or is incomplete | Verify row counts before tearing down NAS |
| OAuth re-auth fails on new redirect URI | Keep NAS running until all platforms reconnected |
| Portainer self-signed TLS breaks deploy script | Add `verify=False` or import cert during Unit 4 |
| Timezone difference between NAS and Ubuntu | Set Ubuntu to same TZ as NAS (`timedatectl set-timezone Asia/Kolkata`) |
| Postiz port 5000 conflicts with something on Ubuntu | Check `ss -tlnp | grep 5000` before deploy |

## Documentation / Operational Notes

- After migration, the Portainer URL for the owner changes from `http://192.168.29.211:9000` to `https://192.168.29.237:9443` (or via Tailscale: `https://commoncreed-server.tail47ec78.ts.net:9443`)
- GPU capabilities (ComfyUI, local inference) are available post-migration but planned separately
- The 24-48 hour soak period in Unit 9 is essential — don't rush NAS teardown

## Sources & References

- **Origin document:** [docs/ideas/move_to_another_server.md](docs/ideas/move_to_another_server.md)
- Deploy script: `.claude/skills/cc-deploy-portainer/cc_update_stack.py`
- Docker compose: `deploy/portainer/docker-compose.yml`
- Env template: `deploy/portainer/.env.example`
- Postiz client: `sidecar/postiz_client.py`
- Gmail client: `sidecar/gmail_client.py`
