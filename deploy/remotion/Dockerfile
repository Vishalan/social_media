# =============================================================================
# CommonCreed Remotion sidecar — cinematic chart renderer
# =============================================================================
# Base: node:20-bullseye-slim. Installs Chromium + ffmpeg + fontconfig so the
# Remotion renderer (@remotion/renderer) can spawn a headless browser and
# encode MP4s. We ship the CommonCreed Inter font family so chart labels
# render in brand typography, matching the Python sidecar's font setup.
#
# Build context: repo root (see deploy/portainer/docker-compose.yml).
# This keeps `COPY assets/fonts/` resolvable, identical to the sidecar image.
# =============================================================================
FROM node:20-bullseye-slim

# Chromium runtime deps for Remotion's headless rendering, plus ffmpeg for
# encoding. fontconfig + fonts-liberation cover generic sans-serif fallbacks;
# the Inter family is copied in below and fc-cache'd.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        ffmpeg \
        fontconfig \
        fonts-liberation \
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
        libxss1 \
        libgtk-3-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Node dependencies first so the npm cache survives source edits.
# If package-lock.json is absent (no network at image build time), the image
# build will fail here — the operator must `npm install` before building.
COPY deploy/remotion/package.json deploy/remotion/package-lock.json ./
RUN npm ci --omit=dev

# TypeScript sources + config.
COPY deploy/remotion/tsconfig.json ./
COPY deploy/remotion/remotion.config.ts ./
COPY deploy/remotion/src ./src

# CommonCreed brand fonts — shared with the Python sidecar.
# fc-cache rebuilds fontconfig so Chromium can resolve "Inter" at render time.
COPY assets/fonts/ /usr/local/share/fonts/commoncreed/
RUN fc-cache -f && fc-list | grep -qi "Inter" \
    || (echo "Inter font registration failed" && exit 1)

# Compile TypeScript to dist/. Use the project's local tsc so the version is
# locked to the devDependency in package.json — but devDeps were pruned by
# --omit=dev above. We reinstall tsc only for the build step, then drop it.
RUN npm install --no-save typescript@~5.4.0 \
    && npx tsc \
    && npm uninstall typescript

# Output directory for rendered MP4s — mounted as a shared volume at runtime.
RUN mkdir -p /app/output

# Point Remotion at the system Chromium so it doesn't try to download its own.
ENV REMOTION_CHROME_EXECUTABLE=/usr/bin/chromium \
    NODE_ENV=production

EXPOSE 3030

CMD ["node", "dist/server.js"]
