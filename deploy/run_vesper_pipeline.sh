#!/usr/bin/env bash
# Vesper daily pipeline runner.
# Called by the macOS LaunchAgent (com.vesper.pipeline) at 09:30.
#
# Mirrors run_pipeline.sh (CommonCreed) — same env-loading shape, same
# log-per-day pattern — but targets scripts/vesper_pipeline/ and keeps
# Vesper logs separate so ops can tail one channel at a time.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS_DIR="$PROJECT_DIR/scripts"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/vesper_pipeline_$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"

echo "=== Vesper pipeline run: $(date) ===" >> "$LOG_FILE"

# Load .env (LaunchAgent doesn't inherit shell env)
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a
fi

cd "$SCRIPTS_DIR"
exec /usr/bin/python3 -m vesper_pipeline >> "$LOG_FILE" 2>&1
