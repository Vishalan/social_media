#!/usr/bin/env bash
set -e

ECHOMIMIC_DIR=${ECHOMIMIC_DIR:=/workspace/EchoMimicV3}
MODELS_DIR=${MODELS_DIR:=/workspace/models}
PYTHON=${PYTHON:=python3.10}

echo "=== EchoMimic V3 Setup ==="

# System dependencies
apt-get update -qq
apt-get install -y -qq ffmpeg libgl1-mesa-glx libglib2.0-0

# Clone repo (skip if already present)
if [ ! -d "$ECHOMIMIC_DIR" ]; then
  git clone https://github.com/antgroup/EchoMimicV3.git "$ECHOMIMIC_DIR"
fi
cd "$ECHOMIMIC_DIR"

# Python deps
$PYTHON -m pip install -q -r requirements.txt

# Wan2.1 base weights (shared with existing ComfyUI workflow)
WAN21_PATH="$MODELS_DIR/wan2.1-1.3b"
if [ ! -d "$WAN21_PATH" ]; then
  echo "Downloading Wan2.1 1.3B base weights..."
  mkdir -p "$WAN21_PATH"
  $PYTHON -c "
from huggingface_hub import snapshot_download
snapshot_download('Wan-AI/Wan2.1-T2V-1.3B', local_dir='$WAN21_PATH', token='${HF_TOKEN:-}')
"
fi

# EchoMimic V3 checkpoints
ECHOMIMIC_CKPT="$MODELS_DIR/echomimic_v3"
if [ ! -d "$ECHOMIMIC_CKPT" ]; then
  echo "Downloading EchoMimic V3 checkpoints..."
  mkdir -p "$ECHOMIMIC_CKPT"
  $PYTHON -c "
from huggingface_hub import snapshot_download
snapshot_download('antgroup/EchoMimicV3', local_dir='$ECHOMIMIC_CKPT', token='${HF_TOKEN:-}')
"
fi

echo "=== EchoMimic V3 setup complete ==="
echo "ECHOMIMIC_DIR=$ECHOMIMIC_DIR"
echo "MODELS_DIR=$MODELS_DIR"
