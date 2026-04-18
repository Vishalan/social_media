---
title: "Server migration: Synology NAS to Ubuntu with Docker + Portainer + Tailscale Funnel"
date: 2026-04-11
category: integration-issues
module: deployment
problem_type: integration_issue
component: tooling
symptoms:
  - "NAS (Celeron J4125, 8GB) too slow for ffmpeg + pipeline workloads"
  - "BrokenPipeError from resource exhaustion during generative pipeline"
  - "No GPU available for local model inference"
root_cause: incomplete_setup
resolution_type: environment_setup
severity: high
tags:
  - server-migration
  - docker
  - portainer
  - tailscale-funnel
  - synology
  - ubuntu
  - postgres-migration
  - oauth-redirect
---

# Server migration: Synology NAS to Ubuntu with Docker + Portainer + Tailscale Funnel

## Problem

The CommonCreed production stack (7 Docker services: Postiz, Temporal, sidecar, Postgres, Redis, Elasticsearch) was running on a Synology DS1520+ NAS (Celeron J4125, 8GB RAM, no GPU) which was underpowered for ffmpeg transcoding, PIL overlays, and concurrent APScheduler jobs. Migrated to a dedicated Ubuntu 24.04 server (Ryzen 5 3600X, 16GB RAM, RTX 2070 SUPER).

## Symptoms

- ffmpeg video normalization slow on 4-core Celeron
- Occasional `BrokenPipeError` during `moviepy.write_videofile` from resource contention
- No local GPU inference possible (ComfyUI, EchoMimic required cloud GPU rental)
- Pipeline lock contention between generative and meme reposter tracks

## What Didn't Work

- **Direct `scp` from Synology**: DSM doesn't expose the SCP subsystem. `scp` commands fail with `subsystem request failed on channel 0`. Workaround: pipe files through `ssh cat` instead.
- **Portainer build API with macOS tar**: macOS injects `com.apple.provenance` xattr metadata into tar archives. Portainer's Docker build rejects these with `lsetxattr: operation not supported`. Workaround: build directly on the server via `ssh docker build` instead of uploading tar to Portainer API.
- **`tailscale funnel --bg` while foreground funnel running**: Returns `foreground listener already exists for port 443`. Must kill the foreground process first, then use `tailscale serve --bg` followed by `tailscale funnel --bg`.

## Solution

### 1. Directory structure on Ubuntu

```
/opt/commoncreed/
├── scripts/     # Pipeline Python scripts
├── sidecar/     # FastAPI sidecar source + Dockerfile
├── assets/      # Brand assets (fonts, logos)
├── secrets/     # gmail_oauth.json
├── deploy/      # docker-compose.yml, nginx, temporal config
├── db/          # SQLite databases
└── output/      # Generated content (runtime)
```

### 2. File transfer (NAS → Ubuntu)

```bash
# rsync for code (from dev Mac)
rsync -avz scripts/ vishalan@192.168.29.237:/opt/commoncreed/scripts/
rsync -avz sidecar/ vishalan@192.168.29.237:/opt/commoncreed/sidecar/

# Secrets via ssh cat (SCP unavailable on Synology DSM)
ssh vishalan@192.168.29.211 "cat /volume1/docker/commoncreed/.env" > /tmp/env_transfer
cat /tmp/env_transfer | ssh vishalan@192.168.29.237 "cat > /opt/commoncreed/.env"
```

### 3. Postgres dump/restore

```bash
# Dump on NAS via Portainer exec API (pg_dump -Fc inside container)
# Restore on Ubuntu
docker exec -i commoncreed_postgres pg_restore -U postiz -d postiz --clean --if-exists < postiz.dump
```

### 4. SQLite migration

```bash
# Extract via Portainer archive API or base64 exec, then docker cp into new container
docker cp sidecar.db commoncreed_sidecar:/app/db/sidecar.db
```

### 5. Deploy script updates

Key changes in `cc_update_stack.py`:
- `PORTAINER`: `http://192.168.29.211:9000` → `https://192.168.29.237:9443`
- Added `ssl.create_default_context()` with `verify_mode=CERT_NONE` for self-signed TLS
- Username: `vishalan` → `admin`
- Keychain label: `commoncreed-portainer` → `commoncreed-portainer-new`
- Path transforms: `/volume1/docker/commoncreed/` → `/opt/commoncreed/`
- Health check: hardcoded URL → `f"http://{SERVER_HOST}:5000/api/auth/register"`

### 6. Sidecar image build

```bash
# Build directly on server (avoids macOS xattr tar issues)
ssh vishalan@192.168.29.237 "cd /opt/commoncreed/sidecar && docker build -t commoncreed/sidecar:0.1.0 ."
```

### 7. Tailscale Funnel (persistent)

```bash
sudo tailscale serve --bg 5000
sudo tailscale funnel --bg 5000
# Result: https://commoncreed-server.tail47ec78.ts.net → proxy http://127.0.0.1:5000
```

### 8. OAuth redirect URIs

Update in Google Cloud Console and Facebook Developer Console:
- Old: `http://192.168.29.211:5000`
- New: `https://commoncreed-server.tail47ec78.ts.net`
- Add paths: `/integrations/social/youtube`, `/integrations/social/facebook`
- Gmail OAuth: no change needed (token-based with refresh_token, no redirect URI)
- Telegram bot: no change needed (polling, not webhooks)

### 9. .env updates

```
POSTIZ_MAIN_URL=https://commoncreed-server.tail47ec78.ts.net
POSTIZ_FRONTEND_URL=https://commoncreed-server.tail47ec78.ts.net
POSTIZ_HOST_PORT=5000   # was 5100 on macOS due to AirPlay conflict
```

## Why This Works

The migration is a lift-and-shift: same Docker Compose stack, same service topology, same env vars. The only changes are host paths (`/volume1/docker/` → `/opt/commoncreed/`), Portainer coordinates (IP, port, TLS, username), and OAuth redirect URIs (LAN IP → Tailscale Funnel HTTPS URL). All application code is unchanged.

Postgres dump/restore preserves all Postiz data (OAuth tokens, connected accounts, scheduled posts). SQLite file copy preserves sidecar state (pipeline runs, meme candidates, approvals). Gmail OAuth uses refresh tokens that work from any server.

## Prevention

- **Use `COPYFILE_DISABLE=1` or `xattr -cr`** when creating tar archives on macOS for Linux Docker builds
- **Use `ssh cat` instead of `scp`** when working with Synology DSM (no SCP subsystem)
- **Build Docker images directly on the target server** via SSH when Portainer build API has issues with macOS-originated tars
- **Always set `POSTIZ_HOST_PORT=5000`** on Linux servers (the `5100` default is a macOS AirPlay workaround)
- **Use `tailscale funnel --bg`** (not foreground) for persistent funnel that survives SSH disconnection
- **Set timezone immediately** after server setup: `sudo timedatectl set-timezone Asia/Kolkata`

## Related Issues

- Plan: `docs/plans/2026-04-11-001-refactor-server-migration-plan.md`
- Idea: `docs/ideas/move_to_another_server.md`
