#!/bin/bash

##############################################################################
# ComfyUI Setup Script for RunPod
# Installs ComfyUI with video generation models and custom nodes
# Optimized for RunPod serverless and on-demand GPU pods
##############################################################################

set -e  # Exit on error

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          ComfyUI Setup for RunPod GPU Instances                    ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════════╝${NC}"

# Set paths
COMFYUI_DIR="${COMFYUI_DIR:=/workspace/ComfyUI}"
MODELS_DIR="${COMFYUI_DIR}/models"
CHECKPOINTS_DIR="${MODELS_DIR}/checkpoints"
DIFFUSION_MODELS_DIR="${MODELS_DIR}/diffusion_models"
VIDEO_MODELS_DIR="${MODELS_DIR}/video_models"
CUSTOM_NODES_DIR="${COMFYUI_DIR}/custom_nodes"

echo -e "${YELLOW}[1/7] Creating directory structure...${NC}"
mkdir -p "$CHECKPOINTS_DIR"
mkdir -p "$DIFFUSION_MODELS_DIR"
mkdir -p "$VIDEO_MODELS_DIR"
mkdir -p "$CUSTOM_NODES_DIR"

# Install system dependencies
echo -e "${YELLOW}[2/7] Installing system dependencies...${NC}"
apt-get update -qq
apt-get install -y -qq \
    git \
    wget \
    curl \
    ffmpeg \
    libopenblas-dev \
    liblapack-dev \
    python3-dev \
    python3-pip \
    2>&1 | grep -v "^Reading state" || true

# Clone ComfyUI repository
echo -e "${YELLOW}[3/7] Setting up ComfyUI...${NC}"
if [ ! -d "$COMFYUI_DIR" ]; then
    git clone https://github.com/comfyanonymous/ComfyUI.git "$COMFYUI_DIR"
    cd "$COMFYUI_DIR"
else
    cd "$COMFYUI_DIR"
    git pull origin master
fi

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -q -U pip setuptools wheel
pip install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
pip install -q -r requirements.txt

# Install ComfyUI-Manager for easy model downloads
echo -e "${YELLOW}[4/7] Installing ComfyUI-Manager...${NC}"
cd "$CUSTOM_NODES_DIR"
if [ ! -d "ComfyUI-Manager" ]; then
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git
    cd ComfyUI-Manager
    pip install -q -r requirements.txt
fi

# Download models
echo -e "${YELLOW}[5/7] Downloading video generation models...${NC}"

# SDXL Base model for image/thumbnail generation
echo "Downloading SDXL base model (3.5GB)..."
cd "$CHECKPOINTS_DIR"
if [ ! -f "sd_xl_base_1.0.safetensors" ]; then
    wget -q --show-progress \
        https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors
fi

# Wan2.1 1.3B GGUF (optimized for VRAM)
echo "Downloading Wan2.1 1.3B model..."
cd "$VIDEO_MODELS_DIR"
if [ ! -f "wan2.1-1.3b-q4.gguf" ]; then
    # Using GGUF quantized version for lower VRAM requirement (~8GB)
    wget -q --show-progress \
        https://huggingface.co/wan-space/wan2.1-1.3b/resolve/main/wan2.1-1.3b-q4.gguf \
        -O wan2.1-1.3b-q4.gguf
fi

# CogVideoX-5B model
echo "Downloading CogVideoX-5B model..."
if [ ! -f "cogvideox-5b.safetensors" ]; then
    wget -q --show-progress \
        https://huggingface.co/THUDM/CogVideoX-5B/resolve/main/pytorch_model.bin \
        -O cogvideox-5b.safetensors
fi

# Download VAE model for video decoding
echo "Downloading VAE model..."
cd "$CHECKPOINTS_DIR"
if [ ! -f "vae-ft-mse-840000-ema.ckpt" ]; then
    wget -q --show-progress \
        https://huggingface.co/stabilityai/sd-vae-ft-mse-original/resolve/main/vae-ft-mse-840000-ema.ckpt
fi

# Install custom nodes for video processing
echo -e "${YELLOW}[6/7] Installing custom nodes...${NC}"
cd "$CUSTOM_NODES_DIR"

# CogVideoX wrapper for ComfyUI
if [ ! -d "ComfyUI-CogVideoXWrapper" ]; then
    git clone https://github.com/kijai/ComfyUI-CogVideoXWrapper.git
    cd ComfyUI-CogVideoXWrapper
    pip install -q -r requirements.txt
    cd ..
fi

# Wan video wrapper
if [ ! -d "ComfyUI-WanVideoWrapper" ]; then
    git clone https://github.com/kijai/ComfyUI-WanVideoWrapper.git
    cd ComfyUI-WanVideoWrapper
    pip install -q -r requirements.txt
    cd ..
fi

# Video Helper Suite for processing
if [ ! -d "ComfyUI-VideoHelperSuite" ]; then
    git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git
    cd ComfyUI-VideoHelperSuite
    pip install -q -r requirements.txt
    cd ..
fi

# Frame interpolation node (optional, for smooth motion)
if [ ! -d "ComfyUI-RIFE" ]; then
    git clone https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git ComfyUI-RIFE
    cd ComfyUI-RIFE
    pip install -q -r requirements.txt
    cd ..
fi

# Setup API endpoint
echo -e "${YELLOW}[7/7] Configuring API endpoint...${NC}"
cd "$COMFYUI_DIR"

# Create launch configuration
cat > launch_config.json << 'EOF'
{
    "listen": "0.0.0.0",
    "port": 8188,
    "enable_cors_header": true,
    "preview_method": "auto",
    "cuda_device": null,
    "disable_smart_memory": false,
    "deterministic": false,
    "user_directory": "./web"
}
EOF

# Create systemd service for automatic startup (optional)
if [ -f /etc/os-release ]; then
    cat > /tmp/comfyui.service << 'EOF'
[Unit]
Description=ComfyUI Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/workspace/ComfyUI
ExecStart=/usr/bin/python3 -m main --listen 0.0.0.0 --port 8188
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    echo "ComfyUI systemd service created at /tmp/comfyui.service"
fi

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                  Setup Complete!                                   ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════════╝${NC}"

echo -e "${YELLOW}ComfyUI Installation Summary:${NC}"
echo "  Directory: $COMFYUI_DIR"
echo "  Models: $MODELS_DIR"
echo "  Custom Nodes: $CUSTOM_NODES_DIR"
echo ""
echo -e "${YELLOW}To start ComfyUI:${NC}"
echo "  cd $COMFYUI_DIR"
echo "  python3 -m main --listen 0.0.0.0 --port 8188"
echo ""
echo -e "${YELLOW}To access the web UI:${NC}"
echo "  http://localhost:8188"
echo ""
echo -e "${YELLOW}Models installed:${NC}"
echo "  ✓ SDXL base (image generation)"
echo "  ✓ CogVideoX-5B (5B parameter video model)"
echo "  ✓ Wan2.1 1.3B GGUF (lightweight video model, ~8GB VRAM)"
echo "  ✓ VAE decoder (video frame generation)"
echo ""
echo -e "${YELLOW}Recommended GPU minimum:${NC}"
echo "  • 24GB VRAM for RTX 4090 (recommended)"
echo "  • 40GB+ for A100 class GPUs"
echo "  • Can run on 12GB with model quantization"
echo ""
echo -e "${GREEN}Next steps:${NC}"
echo "  1. Use run_workflow.py to execute video generation jobs"
echo "  2. Monitor VRAM usage with 'nvidia-smi' command"
echo "  3. Adjust batch_size in workflows if running out of memory"
