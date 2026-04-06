# =============================================================================
# CommonCreed sidecar — FastAPI control plane for the pipeline
# =============================================================================
# Base: python:3.11-slim on x86_64 (Synology J4125 compatible). Installs
# ffmpeg + Playwright Chromium runtime deps so downstream units (caption gen,
# screenshot capture) can use them without rebuilding. The actual pipeline
# (moviepy, playwright, whisper) runs in a separate venv mounted from the
# host at /app/scripts — the sidecar does NOT import those libraries.
# =============================================================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System packages: ffmpeg for any A/V probing, plus the minimum shared libs
# that Playwright Chromium needs at runtime. Kept in a single RUN layer so
# the apt cache can be discarded in the same step.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        ca-certificates \
        curl \
        libnss3 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libpango-1.0-0 \
        libcairo2 \
        libasound2 \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cache-friendly: copy requirements first, install, then copy source.
COPY requirements.txt /app/sidecar_requirements.txt
RUN pip install --no-cache-dir -r /app/sidecar_requirements.txt

# Copy sidecar source last so edits don't bust the pip cache.
COPY . /app/sidecar

ENV PYTHONPATH=/app

EXPOSE 5050

CMD ["uvicorn", "sidecar.app:app", "--host", "0.0.0.0", "--port", "5050"]
