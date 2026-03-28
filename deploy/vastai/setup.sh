#!/bin/bash

##############################################################################
# Vast.ai Setup Script for ComfyUI
# Finds and configures cheapest GPU instance with ComfyUI pre-installed
# Optimized for spot pricing and cost-effective video generation
##############################################################################

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}╔════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Vast.ai ComfyUI Instance Setup                            ║${NC}"
echo -e "${GREEN}║    Find and configure cheapest GPU for video generation           ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════════╝${NC}"

# Configuration
VASTAI_API_KEY="${VASTAI_API_KEY}"
GPU_RAM_MIN=${GPU_RAM_MIN:=20}  # Minimum 20GB VRAM
GPU_MEM_TYPE="unified"          # Prefer unified memory
DOCKER_IMAGE="runpod/comfyui"   # Pre-built ComfyUI image
VOLUME_SIZE=${VOLUME_SIZE:=50}  # 50GB volume for models

# Verify dependencies
echo -e "${YELLOW}[1/5] Checking dependencies...${NC}"

for cmd in curl python3 jq; do
    if ! command -v $cmd &> /dev/null; then
        echo -e "${RED}Error: $cmd not found. Please install it.${RED}"
        exit 1
    fi
done

# Check API key
if [ -z "$VASTAI_API_KEY" ]; then
    echo -e "${YELLOW}Vast.ai API key not found in VASTAI_API_KEY environment variable${NC}"
    echo -e "${YELLOW}Get your API key from: https://vast.ai/account/api-keys${NC}"
    echo ""
    read -p "Enter your Vast.ai API key: " VASTAI_API_KEY
    export VASTAI_API_KEY="$VASTAI_API_KEY"
fi

# Function to search for cheapest GPUs
search_cheapest_gpu() {
    echo -e "${YELLOW}[2/5] Searching for cheapest available GPU...${NC}"

    # Vast.ai API endpoint
    API_URL="https://api.vast.ai/api/v0"

    # Search parameters
    # Filters: RTX 4090, RTX 6000 Ada, L40, A100, H100 - minimum 20GB VRAM, no cuda errors
    FILTERS="gpu_name=RTX4090 OR gpu_name=RTX6000Ada OR gpu_name=L40 OR gpu_name=A100 OR gpu_name=H100"

    echo "Querying Vast.ai API for available instances..."

    # Get available offers sorted by price (ascending)
    RESPONSE=$(curl -s \
        -H "Authorization: Bearer $VASTAI_API_KEY" \
        "$API_URL/offers/?order=dph_total&limit=50&type=on-demand&verified=true&min_ram=${GPU_RAM_MIN}000&gpu_memory_bandwidth>100" \
        2>/dev/null || echo "")

    if [ -z "$RESPONSE" ] || [ "$RESPONSE" == "Connection refused" ]; then
        echo -e "${RED}Error connecting to Vast.ai API${NC}"
        echo "Check that:"
        echo "  1. API key is valid (VASTAI_API_KEY env var)"
        echo "  2. Network connectivity is working"
        return 1
    fi

    # Parse response and display options
    echo -e "${YELLOW}Top 10 cheapest instances:${NC}"
    echo ""
    echo "$RESPONSE" | jq -r '.offers[] | select(.gpu_ram >= 20000) |
        "\(.id): \(.gpu_name) (\(.gpu_ram/1000|floor)GB) - $\(.dph_total|floor*100/100)/hr - \(.host_name)"' \
        | head -20

    # Get the ID of the cheapest option
    CHEAPEST_ID=$(echo "$RESPONSE" | jq -r '.offers[0].id' 2>/dev/null)

    if [ -z "$CHEAPEST_ID" ] || [ "$CHEAPEST_ID" == "null" ]; then
        echo -e "${RED}No suitable GPUs found. Try adjusting filters.${NC}"
        return 1
    fi

    echo ""
    echo -e "${GREEN}Selected cheapest: Instance ID $CHEAPEST_ID${NC}"
    echo "$CHEAPEST_ID"
}

# Get cheapest GPU
GPU_INSTANCE=$(search_cheapest_gpu)
if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to find suitable GPU. Exiting.${NC}"
    exit 1
fi

# Create instance
echo -e "${YELLOW}[3/5] Creating instance on Vast.ai...${NC}"

cat > /tmp/instance_config.json << EOF
{
    "client_id": "default",
    "instance_type": "$GPU_INSTANCE",
    "image": "$DOCKER_IMAGE",
    "volume": $VOLUME_SIZE,
    "cuda": true,
    "docker": true
}
EOF

echo "Creating instance with GPU: $GPU_INSTANCE"
echo "Docker image: $DOCKER_IMAGE"
echo "Volume size: ${VOLUME_SIZE}GB"

# Create the instance (actual implementation depends on Vast.ai API details)
# This is a placeholder - refer to Vast.ai docs for exact API
INSTANCE_RESPONSE=$(curl -s \
    -X POST \
    -H "Authorization: Bearer $VASTAI_API_KEY" \
    -H "Content-Type: application/json" \
    -d @/tmp/instance_config.json \
    "https://api.vast.ai/api/v0/instances/" \
    2>/dev/null || echo "")

echo -e "${BLUE}Instance creation response:${NC}"
echo "$INSTANCE_RESPONSE" | jq '.' 2>/dev/null || echo "$INSTANCE_RESPONSE"

# Extract instance ID
INSTANCE_ID=$(echo "$INSTANCE_RESPONSE" | jq -r '.id' 2>/dev/null)

if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" == "null" ]; then
    echo -e "${RED}Failed to create instance${NC}"
    exit 1
fi

echo -e "${GREEN}Instance created: $INSTANCE_ID${NC}"

# Wait for instance to start
echo -e "${YELLOW}[4/5] Waiting for instance to start...${NC}"

MAX_WAIT=300  # 5 minutes
ELAPSED=0
CHECK_INTERVAL=10

while [ $ELAPSED -lt $MAX_WAIT ]; do
    STATUS=$(curl -s \
        -H "Authorization: Bearer $VASTAI_API_KEY" \
        "https://api.vast.ai/api/v0/instances/$INSTANCE_ID/" \
        2>/dev/null | jq -r '.state' 2>/dev/null)

    if [ "$STATUS" == "running" ]; then
        echo -e "${GREEN}Instance is running!${NC}"
        break
    fi

    echo "Status: $STATUS (waiting...)"
    sleep $CHECK_INTERVAL
    ELAPSED=$((ELAPSED + CHECK_INTERVAL))
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    echo -e "${RED}Instance startup timeout${NC}"
    exit 1
fi

# Get connection details
echo -e "${YELLOW}[5/5] Getting connection details...${NC}"

INSTANCE_INFO=$(curl -s \
    -H "Authorization: Bearer $VASTAI_API_KEY" \
    "https://api.vast.ai/api/v0/instances/$INSTANCE_ID/" \
    2>/dev/null)

HOSTNAME=$(echo "$INSTANCE_INFO" | jq -r '.hostname' 2>/dev/null)
PORT=$(echo "$INSTANCE_INFO" | jq -r '.port' 2>/dev/null)
SSH_PORT=$(echo "$INSTANCE_INFO" | jq -r '.ssh_port' 2>/dev/null)
IP=$(echo "$INSTANCE_INFO" | jq -r '.public_ipaddr' 2>/dev/null)

# Create connection script
cat > /tmp/vast_connect.sh << EOF
#!/bin/bash

# Vast.ai Instance Connection Details
INSTANCE_ID="$INSTANCE_ID"
HOSTNAME="$HOSTNAME"
IP="$IP"
SSH_PORT="$SSH_PORT"
COMFYUI_PORT="$PORT"

echo "Vast.ai Instance Information"
echo "=============================="
echo "Instance ID: \$INSTANCE_ID"
echo "IP Address: \$IP"
echo "SSH Port: \$SSH_PORT"
echo ""

# SSH Connection
echo "To connect via SSH:"
echo "  ssh -p \$SSH_PORT root@\$IP"
echo ""

# ComfyUI Web Interface
echo "ComfyUI Web Interface:"
echo "  http://\$IP:\$COMFYUI_PORT"
echo ""

# Copy SSH key if available
if [ -f ~/.ssh/id_rsa ]; then
    echo "SSH key found. Copy to instance:"
    echo "  ssh-copy-id -p \$SSH_PORT root@\$IP"
fi
EOF

chmod +x /tmp/vast_connect.sh

# Display summary
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              Instance Setup Complete!                              ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Instance Details:${NC}"
echo "  ID: $INSTANCE_ID"
echo "  IP Address: $IP"
echo "  Hostname: $HOSTNAME"
echo "  SSH Port: $SSH_PORT"
echo "  ComfyUI Port: $PORT"
echo ""

echo -e "${BLUE}Connect to instance:${NC}"
echo "  ssh -p $SSH_PORT root@$IP"
echo ""

echo -e "${BLUE}Access ComfyUI Web UI:${NC}"
echo "  http://$IP:$PORT"
echo ""

echo -e "${YELLOW}Next steps:${NC}"
echo "  1. SSH into the instance and verify ComfyUI is running"
echo "  2. Download video generation models (if not pre-installed)"
echo "  3. Start generating videos"
echo "  4. Stop instance when done to save costs"
echo ""

echo -e "${YELLOW}Stopping the instance:${NC}"
echo "  curl -X DELETE \\"
echo "    -H 'Authorization: Bearer \$VASTAI_API_KEY' \\"
echo "    'https://api.vast.ai/api/v0/instances/$INSTANCE_ID/'"
echo ""

echo -e "${YELLOW}Cost estimation:${NC}"
echo "  View pricing at: https://vast.ai/console/instances/"
echo ""

# Save config for future reference
cat > ~/.vast_instance.json << EOF
{
    "instance_id": "$INSTANCE_ID",
    "ip": "$IP",
    "hostname": "$HOSTNAME",
    "ssh_port": $SSH_PORT,
    "comfyui_port": $PORT,
    "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "gpu_instance": "$GPU_INSTANCE",
    "docker_image": "$DOCKER_IMAGE"
}
EOF

echo -e "${GREEN}Configuration saved to ~/.vast_instance.json${NC}"
