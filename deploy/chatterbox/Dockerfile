# =============================================================================
# CommonCreed Chatterbox sidecar — local TTS via Resemble AI Chatterbox.
#
# Base: pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime. This image ships with
# Python 3.10, torch 2.3.1, torchvision, torchaudio, and CUDA 12.1 runtime —
# everything chatterbox-tts needs without a separate torch install.
#
# Model weights (~2-3 GB) are downloaded on first request from the HuggingFace
# hub. They persist under /root/.cache/huggingface across container restarts
# via the commoncreed_chatterbox_cache named volume (see docker-compose.yml).
#
# Build context: repo root (same as sidecar + remotion).
# GPU access is granted in compose via deploy.resources.reservations.devices
# (nvidia runtime + all capabilities, one GPU).
# =============================================================================
FROM pytorch/pytorch:2.3.1-cuda12.1-cudnn8-runtime

# System deps: ffmpeg for any audio-side wrangling, curl for healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching.
# chatterbox-tts transitively pulls several heavy wheels (gradio, librosa,
# scipy, etc.) on top of the pytorch base, so pip timeouts + retries are
# non-negotiable — one slow download otherwise kills a 15-min build.
COPY deploy/chatterbox/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir \
      --default-timeout=300 \
      --retries=5 \
      -r requirements.txt

# Server code. Kept minimal — FastAPI + one TTS endpoint + healthz.
COPY deploy/chatterbox/server.py ./server.py

# Assets dir is mounted at runtime from /opt/commoncreed/assets (reference
# audio lives there), not baked in.
RUN mkdir -p /app/output /app/refs

EXPOSE 7777

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:7777/healthz || exit 1

# Chatterbox model loads lazily on first /tts call. We could preload at
# container startup but that costs ~10s boot time — the container would
# answer /healthz before ready. Current behavior: startup is fast, first
# /tts pays the ~10s model load. Subsequent calls are ~18s per minute of
# speech on RTX 3090.
CMD ["python", "-u", "server.py"]
