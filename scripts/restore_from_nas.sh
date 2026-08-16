#!/bin/bash
#
# Restore CommonCreed server from NAS backup made 2026-06-20.
# Run on a fresh Ubuntu 24.04 install on /dev/sda HDD.
#
# Usage (after fresh Ubuntu install with hostname=commoncreed-server, user=vishalan):
#   ssh vishalan@NEW_IP 'sudo bash /tmp/restore_from_nas.sh' < /tmp/nas_password
#
set -e
set -o pipefail

BACKUP_DIR="/mnt/nas/Devices/3090 PC/Backup/Ubuntu Server/20260620-1058-commoncreed"
SHARE="//192.168.29.211/home"
USER="vishalan"

# ----- 1. Read NAS password from stdin (no chat exposure) -----
read -r NAS_PW

# ----- 2. Install dependencies -----
echo "=== install deps ==="
apt update
DEBIAN_FRONTEND=noninteractive apt install -y \
  docker.io docker-compose-v2 \
  cifs-utils smartmontools pigz \
  curl ca-certificates gnupg

# Tailscale (separate repo)
if ! command -v tailscale > /dev/null; then
  curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg \
    | tee /usr/share/keyrings/tailscale-archive-keyring.gpg > /dev/null
  curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list \
    | tee /etc/apt/sources.list.d/tailscale.list > /dev/null
  apt update
  DEBIAN_FRONTEND=noninteractive apt install -y tailscale
fi

# ----- 3. Mount NAS -----
echo "=== mount NAS ==="
mkdir -p /mnt/nas
CREDS=/tmp/.smb.$$
umask 077
cat > $CREDS <<EOF
username=$USER
password=$NAS_PW
EOF
unset NAS_PW

if ! mountpoint -q /mnt/nas; then
  mount -t cifs $SHARE /mnt/nas \
    -o credentials=$CREDS,vers=3.0,uid=0,gid=0,iocharset=utf8
fi
shred -u $CREDS 2>/dev/null || rm -f $CREDS

if ! ls "$BACKUP_DIR" > /dev/null 2>&1; then
  echo "ERR: backup dir not found at $BACKUP_DIR"
  exit 2
fi
echo "Backup dir: $BACKUP_DIR ($(du -sh "$BACKUP_DIR" | cut -f1))"

# ----- 4. Verify SHA256 checksums -----
echo "=== verify backup integrity ==="
cd "$BACKUP_DIR"
if ! sha256sum -c <(grep -A100 "## SHA256" MANIFEST.txt | grep "tar.gz") 2>&1 | tail -15; then
  echo "WARN: some checksums may not match — proceeding anyway"
fi

# ----- 5. Restore /opt/commoncreed -----
echo "=== restore /opt/commoncreed ==="
tar -C /opt -xzf "$BACKUP_DIR/opt-commoncreed.tar.gz"
ls /opt/commoncreed | head

# ----- 6. Restore /etc configs (DO NOT overwrite hostname/hosts of NEW machine) -----
# We selectively restore only daemon.json + systemd network + fstab; hostname/hosts skipped
echo "=== restore /etc configs (selective) ==="
mkdir -p /etc/docker /etc/systemd/network
tar -C / -xzf "$BACKUP_DIR/etc-configs.tar.gz" \
  etc/docker/daemon.json \
  etc/systemd/network 2>/dev/null || true
# fstab backup line — keep new install's fstab, just append our HDD comments if missing
echo "(NOTE: fstab from backup has disabled HDD lines that no longer apply; skipping)"

systemctl restart docker || true

# ----- 7. Restore Tailscale identity -----
echo "=== restore tailscale identity ==="
systemctl stop tailscaled 2>/dev/null || true
tar -C /var/lib -xzf "$BACKUP_DIR/tailscale.tar.gz"
systemctl enable --now tailscaled
sleep 5
tailscale up --reset || tailscale up || true
sleep 3
tailscale status | head -5

# ----- 8. Restore Docker volumes -----
VOLUMES=(
  commoncreed_postgres_data
  commoncreed_temporal_postgres_data
  commoncreed_sidecar_db
  commoncreed_postiz_uploads
  commoncreed_postiz_config
  commoncreed_temporal_elasticsearch_data
  commoncreed_output
)
for V in "${VOLUMES[@]}"; do
  TAR="$BACKUP_DIR/${V}.tar.gz"
  if [ ! -f "$TAR" ]; then
    echo "  SKIP $V (no tarball)"
    continue
  fi
  echo "=== restore volume $V ==="
  docker volume create $V > /dev/null
  tar -C /var/lib/docker/volumes/$V/_data -xzf "$TAR"
  du -sh /var/lib/docker/volumes/$V/_data | head -1
done

# ----- 9. Build + start the stack -----
echo "=== bring up stack (sidecar will build, others pull) ==="
cd /opt/commoncreed/deploy/portainer
docker compose -p commoncreed up -d --build \
  postgres redis temporal-postgres temporal-elasticsearch temporal postiz commoncreed_sidecar

# Wait for sidecar to come healthy
echo "=== waiting for stack to settle ==="
for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
  sleep 10
  HEALTH=$(docker inspect commoncreed_sidecar --format '{{.State.Health.Status}}' 2>/dev/null || echo "starting")
  echo "  [$i/12] sidecar=$HEALTH"
  if [ "$HEALTH" = "healthy" ]; then break; fi
done

echo ""
echo "=== final container state ==="
docker ps --format "table {{.Names}}\t{{.Status}}"

echo ""
echo "=== data integrity quick-check ==="
docker exec commoncreed_postgres sh -c 'psql -U $POSTGRES_USER -d postiz -tAc "SELECT COUNT(*) AS users, (SELECT COUNT(*) FROM \"Integration\" WHERE \"deletedAt\" IS NULL) AS integrations, (SELECT COUNT(*) FROM \"Post\") AS posts FROM \"User\""' 2>&1 | head -3
docker exec commoncreed_sidecar sqlite3 /app/db/sidecar.db "SELECT COUNT(*) AS memes, COUNT(*) FILTER (WHERE status='published') AS published FROM meme_candidates" 2>&1 | head -3

# ----- 10. Cleanup -----
umount /mnt/nas 2>/dev/null || true

echo ""
echo "*** RESTORE COMPLETE ***"
echo ""
echo "Verify:  curl https://commoncreed-server.tail47ec78.ts.net/auth/login"
echo "Expect:  HTTP 200 (login page)"
echo ""
echo "Expected counts (from backup at 2026-06-20 11:00):"
echo "  Postiz: 5 users / 6 active integrations / 143 posts"
echo "  Sidecar: 438 meme candidates / 97 published"
