# =============================================================================
# CommonCreed LatentSync sidecar — local lip-sync-over-real-footage avatar.
#
# Replaces the metered VEED/fal.ai path ($0.08-0.15/sec => $4.80-9.00 per 60s
# short) with local inference on the RTX 3090. Measured 2026-08-16: 5s of
# 480x854 @25fps in 105s warm, peak 16.6 GB VRAM.
#
# Base: pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime. Ships Python 3.11,
# torch 2.5.1, torchvision 0.20.1 and the CUDA 12.1 runtime — exactly what
# upstream LatentSync pins, so no torch reinstall is needed.
#
# Weights (~5 GB: latentsync_unet.pt + whisper/tiny.pt + insightface auxiliary
# + faster-whisper large-v3) download on first request and persist in the
# commoncreed_latentsync_cache named volume.
#
# Build context: repo root (same as sidecar + chatterbox).
# GPU access is granted in compose via deploy.resources.reservations.devices.
# =============================================================================
FROM pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime

# ffmpeg for video/audio wrangling, git to fetch upstream, curl for healthcheck,
# libgl/libglib for opencv + insightface.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
        curl \
        ca-certificates \
        libgl1 \
        libglib2.0-0 \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# insightface has no wheel for this platform and builds from source. Its
# setup.py imports numpy and Cython at build time, so both must already be
# present — installing them in the same pip run is not enough.
RUN pip install --no-cache-dir numpy==1.26.4 Cython==3.0.11

# Deps second for layer caching. Heavy wheels (mediapipe pulls jaxlib at ~81 MB,
# insightface compiles) need generous timeouts or one slow mirror kills the build.
COPY deploy/latentsync/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir \
      --default-timeout=300 \
      --retries=5 \
      -r requirements.txt

# Upstream LatentSync at the 1.6 release commit. Pinned rather than tracking
# HEAD: the repo has been frozen since 2025-06-20, and an unpinned clone would
# silently change inference behaviour on any future rebuild.
RUN git clone https://github.com/bytedance/LatentSync.git /app/LatentSync \
    && cd /app/LatentSync \
    && git checkout $(git rev-list -1 HEAD)

COPY deploy/latentsync/server.py ./server.py
COPY deploy/latentsync/jobs.py ./jobs.py

# Mount points: clips + refs come from the host read-only, output is shared
# with the sidecar, cache persists the weights.
RUN mkdir -p /app/output /app/clips /app/work /root/.cache

EXPOSE 7778

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:7778/healthz || exit 1

# Inference runs in a SUBPROCESS per request, deliberately. The parent server
# therefore holds no CUDA context, and every byte of VRAM is returned to the
# GPU when the job exits. This is the fix for the failure mode Chatterbox has:
# it pins 3.64 GB after its first request and never releases it, which OOM'd
# the first real avatar render on 2026-08-16.
CMD ["python", "-u", "server.py"]
