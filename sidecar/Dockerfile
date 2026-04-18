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
        tzdata \
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
        fontconfig \
        fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# libass must be present for ASS karaoke subtitles (Unit A2 caption rendering).
# ffmpeg wraps libass via the 'ass' filter — assert its presence at build time so
# a broken ffmpeg image fails early rather than silently falling back.
RUN ffmpeg -filters 2>&1 | grep -qw ass \
    || (echo "FAIL: ffmpeg in this image does not include libass" && exit 1)

# CommonCreed brand fonts (Inter, SIL OFL) — shipped in-repo under assets/fonts.
# fc-cache rebuilds the fontconfig index so Pillow/libass can resolve "Inter".
# The grep asserts registration succeeded; a failed fontconfig would otherwise
# silently fall back to default fonts and ruin every caption + headline frame.
COPY assets/fonts/ /usr/local/share/fonts/commoncreed/
RUN fc-cache -f -v && fc-list | grep -qi "Inter" || (echo "Inter font registration failed" && exit 1)

WORKDIR /app

# Cache-friendly: copy requirements first, install, then copy source.
# Build context is repo root (see docker-compose.yml), so paths are repo-relative.
COPY sidecar/requirements.txt /app/sidecar_requirements.txt
RUN pip install --no-cache-dir -r /app/sidecar_requirements.txt

# Pipeline runtime lives in its own venv so its newer anthropic/httpx/etc.
# don't conflict with the sidecar app's pinned versions. The sidecar
# subprocess dispatcher invokes /opt/pipeline_venv/bin/python3 for smoke_e2e.
COPY sidecar/pipeline_requirements.txt /app/pipeline_requirements.txt
RUN python3 -m venv /opt/pipeline_venv \
    && /opt/pipeline_venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/pipeline_venv/bin/pip install --no-cache-dir -r /app/pipeline_requirements.txt \
    && /opt/pipeline_venv/bin/playwright install chromium \
    && /opt/pipeline_venv/bin/playwright install-deps chromium || true

# Copy sidecar source last so edits don't bust the pip cache.
COPY sidecar/ /app/sidecar

ENV PYTHONPATH=/app

EXPOSE 5050

CMD ["uvicorn", "sidecar.app:app", "--host", "0.0.0.0", "--port", "5050"]
