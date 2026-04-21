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
# Vesper entrypoint: the package's CLI (to be added as a __main__.py
# in a follow-up; for now callers import and invoke VesperPipeline().run_daily()
# via an inline -c. When __main__ lands, replace with:
#   exec /usr/bin/python3 -m vesper_pipeline
exec /usr/bin/python3 -c "
import logging, sys
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
from vesper_pipeline_runtime import build_pipeline_from_env
pipe = build_pipeline_from_env()
pipe.run_daily()
" >> "$LOG_FILE" 2>&1
