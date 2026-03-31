#!/usr/bin/env bash
# CommonCreed daily pipeline runner.
# Called by the macOS LaunchAgent at the configured schedule.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPTS_DIR="$PROJECT_DIR/scripts"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/pipeline_$(date +%Y-%m-%d).log"

mkdir -p "$LOG_DIR"

echo "=== CommonCreed pipeline run: $(date) ===" >> "$LOG_FILE"

# Load .env (LaunchAgent doesn't inherit shell env)
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_DIR/.env"
    set +a
fi

cd "$SCRIPTS_DIR"
exec /usr/bin/python3 commoncreed_pipeline.py >> "$LOG_FILE" 2>&1
