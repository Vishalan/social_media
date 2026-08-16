# commoncreed-server — Handoff Context

Self-hosted Ubuntu server (dual-boot with corrupt Windows). User is `vishalan`.
Currently mid drive-swap: original WD Blue SN580 NVMe failed SMART; RMA
replacement is plugged in but not yet configured. Server currently booted from
the Seagate HDD (verify actual root device on first SSH).

## Access

- **SSH (Tailscale, works anywhere):** `ssh vishalan@100.72.251.52`
- **SSH (LAN):** `ssh vishalan@192.168.29.235`
- **Tailscale DNS:** `commoncreed-server.tail47ec78.ts.net`
- **LAN CIDR:** `192.168.29.0/24`
- Passwordless sudo enabled.

## Hardware

- **CPU:** AMD Ryzen 5 3600X (6c/12t)
- **GPU:** NVIDIA RTX 3090, **24 GB VRAM** (older docs mis-labeled this box "2070 Super" — it isn't)
- **RAM:** 62 GB
- **Motherboard:** MSI B450
- **Drives (verify current state on SSH — topology is mid-change):**
  - Original NVMe (`nvme0n1`): WD Blue SN580 1 TB — **SMART FAILED**, being RMA'd. May be removed.
  - New WD NVMe: **just installed by user, not yet configured**. Enumeration (`nvme0n1` vs `nvme1n1`) TBD.
  - HDD (`sda`): Seagate ST3500418AS 465 GB — healthy, was hosting `/var/lib/docker` + `/var/lib/containerd`.

## NAS

- **IP:** `192.168.29.211` (also `Vishalan_NAS.local` via mDNS)
- **SMB share:** `//192.168.29.211/home`, backup folder: `Devices/3090 PC/`
- **Server-side mount creds:** `/root/.smbcreds.nas` (mode 600), user `vishalan`

## Hosted services (URLs)

- **Postiz** (social scheduler): https://commoncreed-server.tail47ec78.ts.net/launches
- **Open WebUI** (Ollama chat): https://commoncreed-server.tail47ec78.ts.net:8443/ — login `reach.vishalan.ai@gmail.com`
- **Ollama API:** http://commoncreed-server.tail47ec78.ts.net:11434/ (Ollama runs on host, NOT in a container)
- **Netdata:** http://commoncreed-server.tail47ec78.ts.net:19999/
- **Portainer:** `:9000` (TLS)

## Docker stack (project name: `commoncreed`)

Compose file: `/opt/commoncreed/deploy/portainer/docker-compose.yml`
Always run `docker compose` commands with **`-p commoncreed`** or duplicate volumes get created.

| Container | Image | Role |
|---|---|---|
| commoncreed_postiz | ghcr.io/gitroomhq/postiz-app:latest | Social scheduler (nginx+backend+frontend+orchestrator) |
| commoncreed_postgres | postgres:16.4-alpine | Postiz DB (`postiz`/`postiz-db-local`) |
| commoncreed_redis | redis:7.4-alpine | Postiz queue/cache |
| commoncreed_temporal | temporalio/auto-setup:1.28.1 | Workflow engine |
| commoncreed_temporal_postgres | postgres:16-alpine | Temporal DB |
| commoncreed_temporal_elasticsearch | elasticsearch:7.17.27 | Temporal visibility |
| open-webui | ghcr.io/open-webui/open-webui:main | Chat UI for Ollama |
| netdata | netdata/netdata | Monitoring |
| portainer | portainer/portainer-ce:lts | Stack UI |
| commoncreed_sidecar | commoncreed/sidecar:0.1.0 | Custom pipeline control container; SQLite at `SIDECAR_DB_PATH` |
| commoncreed_comfyui | (occasional) | ComfyUI image gen; often stopped |

**Named volumes (matter for restore):**
`commoncreed_postgres_data`, `commoncreed_temporal_postgres_data`,
`commoncreed_temporal_elasticsearch_data`, `commoncreed_postiz_uploads`,
`commoncreed_postiz_config`, `commoncreed_chatterbox_cache`,
`commoncreed_comfyui_models`.

## Key file paths

- **Compose project root:** `/opt/commoncreed/`
- **Compose file:** `/opt/commoncreed/deploy/portainer/docker-compose.yml`
- **`.env` (all 70+ secrets):** `/opt/commoncreed/.env`
- **`.env` symlink for Compose:** `/opt/commoncreed/deploy/portainer/.env` → `/opt/commoncreed/.env` (critical — see gotcha)
- **NAS SMB creds:** `/root/.smbcreds.nas` (mode 600)
- **GPT + boot-sector backups from previous session:** `/mnt/nas/Devices/3090 PC/partition-rebalance-backup-2026-06-06/`

## Known gotchas

- **Postiz `.env` gotcha:** Compose looks for `.env` in its working dir (`/opt/commoncreed/deploy/portainer/`), not the parent (`/opt/commoncreed/`). Without the symlink, all `${VAR}` refs silently resolve to empty strings → Postiz stuck in restart loop with `DATABASE_URL resolved to an empty string`. **Verify the symlink still exists** if Postiz is dead.
- **Compose project name mismatch:** default is dir name (`portainer`) but existing volumes/network are tagged `commoncreed`. Always `-p commoncreed`.
- **Windows partition on failing NVMe:** 699 NTFS bitmap mismatches + 4 bad sectors that chkdsk can't fix. Don't try to boot Windows or resize it.
- **Old NVMe SMART:** persistent FAILED status, Critical Warning `0x04`, 232 media errors — RMA in progress. Don't put load on it.

## Current task context

User just installed the RMA replacement NVMe. Server booted from HDD (needs verification of how). Next intended action: **test the new NVMe before committing to using it** — SMART baseline, controller info, seq/random read+write benchmark, thermal check.

## Storage plan for the new drive (from prior planning)

Not yet executed:
- Fresh Ubuntu Server 24.04 install onto new NVMe (partition to taste — user was considering ~400 GB Windows / 1.5 TB Ubuntu on a 2 TB drive)
- Restore Ubuntu via selective tar of `/etc`, `/home`, `/root`, `/opt`, `/var/lib/tailscale`, etc. (backup was proposed but confirm whether user actually ran it)
- Docker stack survives via existing Seagate mount (`/var/lib/docker` + `/var/lib/containerd` bind) once fstab is re-added
