# GPU Cloud Deployment Scripts for Video Generation

Complete setup and cost optimization suite for deploying video generation workflows on cloud GPU providers.

## Files Overview

### Cost Analysis
- **`gpu_cost_comparison.py`** - Comprehensive cost comparison tool for RunPod, Vast.ai, and Lambda Labs
  - Pricing data for RTX 4090, L40, A100 40GB, A100 80GB, H100
  - Cost calculations for short clips (5 min generation) and long-form (15 min)
  - Monthly cost estimates at different production levels (10, 20, 50, 100 videos/month)
  - Budget tier recommendations
  - ROI analysis per minute of output content

### RunPod Deployment
- **`runpod/setup_comfyui.sh`** - Bash script for RunPod setup
  - Installs ComfyUI from source
  - Installs ComfyUI-Manager for model management
  - Downloads optimized video models (Wan2.1, CogVideoX-5B, SDXL)
  - Installs video processing custom nodes
  - Configures API endpoint

- **`runpod/run_workflow.py`** - Python script for workflow execution
  - Creates and manages RunPod GPU instances
  - Submits ComfyUI workflows via REST API
  - Polls job status until completion
  - Downloads results to local storage
  - Auto-stops pods to save costs
  - Includes idle timeout detection

### Vast.ai Deployment
- **`vastai/setup.sh`** - Bash script for Vast.ai instance setup
  - Queries Vast.ai API for cheapest available GPUs
  - Creates ComfyUI instance with optimal configuration
  - Configures Docker image and volume
  - Provides connection details and monitoring

### Local Development
- **`docker-compose.yml`** - Docker Compose configuration for local GPU testing
  - ComfyUI service with NVIDIA GPU support
  - Volume mounts for models, outputs, and custom nodes
  - Health checks and logging
  - Optional Nginx reverse proxy
  - Persistent storage configuration

## Quick Start

### 1. Check Costs First
```bash
python3 deploy/gpu_cost_comparison.py
```

This will show you cost-per-video and monthly cost estimates for different GPU options and production levels.

### 2. Local Testing (if you have a GPU)
```bash
cd deploy
docker-compose up
# Access at http://localhost:8188
```

### 3. Deploy to RunPod

First, set your API key:
```bash
export RUNPOD_API_KEY="your-api-key"
```

Then run workflows:
```bash
python3 deploy/runpod/run_workflow.py
```

### 4. Deploy to Vast.ai

Set API key:
```bash
export VASTAI_API_KEY="your-api-key"
```

Run setup:
```bash
bash deploy/vastai/setup.sh
```

## Cost Breakdown

### Hourly Rates (March 2026)
| GPU | RunPod | Vast.ai | Lambda Labs |
|-----|--------|---------|-------------|
| RTX 4090 | $0.44 | $0.30 | $0.50 |
| L40 | $0.60 | $0.45 | $0.70 |
| A100 40GB | $0.95 | $0.70 | $1.20 |
| A100 80GB | $1.49 | $1.10 | $1.80 |
| H100 | $3.09 | $2.50 | $3.50 |

### Cost per Video
Assuming generation time:
- **Short clips** (720p, 10-15s): ~5 minutes generation = $0.04-0.15/video
- **Long-form** (1080p, 30-60s): ~15 minutes generation = $0.11-0.44/video

### Monthly Production Budgets

**10 videos/month:**
- RTX 4090 on Vast.ai: ~$35
- Best for: Small creators testing ideas

**20 videos/month:**
- L40 on Vast.ai: ~$80
- Best for: Part-time content creators

**50 videos/month:**
- A100 40GB on Vast.ai: ~$200
- Best for: Full-time creators, better performance

**100+ videos/month:**
- Consider dedicated/reserved instances: $500-2000/month
- Better for: Production studios with consistent needs

## Provider Comparison

### RunPod ✓ Best for
- Reliable availability
- Good developer experience
- Serverless and on-demand options
- Easy scaling
- Cost: 30-40% premium over Vast.ai

### Vast.ai ✓ Best for
- Cost optimization (spot pricing)
- Competitive hourly rates
- Large selection of GPU options
- Risk: Less guaranteed availability
- Cost: ~30% cheaper than alternatives

### Lambda Labs ✓ Best for
- Guaranteed availability
- Consistent performance
- Enterprise support
- Premium stability
- Cost: 40-50% premium over Vast.ai

## Optimization Tips

1. **Batch Processing**
   - Process multiple videos in one pod session
   - Reduces startup overhead per video
   - Share model loading time

2. **Model Quantization**
   - Use GGUF quantized models (Wan2.1)
   - Reduce VRAM requirements by 50-70%
   - Slight quality trade-off

3. **Spot Instances**
   - Use Vast.ai spot pricing for non-urgent work
   - Save 30-50% on compute costs
   - Risk of interruption

4. **Auto-shutdown**
   - Always stop pods after jobs complete
   - Use idle timeout detection
   - Prevents accidental cost overruns

5. **Model Caching**
   - Pre-download models to persistent volumes
   - Skip download time on subsequent runs
   - Can save 5-10 minutes per generation

## Model Information

### Wan2.1 1.3B (GGUF)
- Parameters: 1.3 billion
- VRAM: ~6-8GB (quantized)
- Generation time: 5 min/short clip
- Quality: Good for social media content
- Best for: Fast, cost-effective generation

### CogVideoX-5B
- Parameters: 5 billion
- VRAM: 12-16GB
- Generation time: 10-15 min/clip
- Quality: Higher quality output
- Best for: Premium content

### SDXL Base
- Parameters: 700M (base)
- VRAM: 3-6GB
- Use case: Image/thumbnail generation
- Quality: Excellent for still images

## Monitoring & Costs

### RunPod
- Dashboard: https://www.runpod.io/console
- Usage tracking per pod
- Auto-billing

### Vast.ai
- Dashboard: https://vast.ai/console/instances/
- Real-time cost monitoring
- Spot price history

### Local (Docker)
- Free (uses your GPU)
- Great for development and testing
- No cloud costs

## Troubleshooting

### Out of Memory
```python
# In workflow, reduce batch size
batch_size = 1  # Instead of 2 or 4
```

### Slow Generation
- Check GPU utilization: `nvidia-smi`
- Ensure full GPU is allocated
- Reduce video resolution/duration

### Pod Connection Failed
- Verify API key is set correctly
- Check pod status in cloud dashboard
- Ensure pod is fully started (wait 2-3 minutes)

### Model Download Failures
- Check internet connectivity
- Verify storage space (50GB+ recommended)
- Try downloading manually from Hugging Face

## Security Best Practices

1. **API Keys**
   - Never commit API keys to git
   - Use environment variables
   - Rotate keys regularly

2. **Network**
   - Use VPN for sensitive operations
   - Limit instance network access
   - Use private SSH keys

3. **Storage**
   - Don't store sensitive data in volumes
   - Encrypt model volumes if possible
   - Clean up outputs after downloads

## Resources

- RunPod: https://www.runpod.io/
- Vast.ai: https://vast.ai/
- Lambda Labs: https://lambdalabs.com/
- ComfyUI: https://github.com/comfyanonymous/ComfyUI
- Hugging Face: https://huggingface.co/

## Support

For issues:
1. Check cloud provider documentation
2. Review ComfyUI troubleshooting guide
3. Check model documentation on Hugging Face
4. Review logs: `nvidia-smi` for GPU info

## License

These deployment scripts are provided as-is for video generation workflows.
