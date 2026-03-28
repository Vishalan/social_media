# GPU Cloud Deployment - Quick Start Guide

Get your video generation pipeline running in minutes.

## Step 1: Check Costs (2 minutes)
```bash
python3 gpu_cost_comparison.py
```

This shows you exactly how much each GPU option costs per video and per month.

**Key findings:**
- RTX 4090 on Vast.ai: Cheapest (~$0.04/short clip)
- L40 on RunPod: Best balance (~$0.10/short clip, reliable)
- A100 on Vast.ai: Performance (~$0.15/short clip)

## Step 2: Choose Your Provider

### Option A: Local Testing (Free, if you have GPU)
```bash
# Install Docker and nvidia-docker
# Then:
docker-compose up
# Access at http://localhost:8188
```

### Option B: RunPod (Recommended for beginners)
1. Sign up: https://www.runpod.io/
2. Get API key from: https://www.runpod.io/console/api-keys
3. Set environment variable:
   ```bash
   export RUNPOD_API_KEY="your-key-here"
   ```
4. Run your workflows:
   ```bash
   python3 runpod/run_workflow.py
   ```

### Option C: Vast.ai (Best for cost optimization)
1. Sign up: https://vast.ai/
2. Get API key from: https://vast.ai/account/api-keys
3. Run setup:
   ```bash
   export VASTAI_API_KEY="your-key-here"
   bash vastai/setup.sh
   ```

## Step 3: Create Your Workflow

Example workflow structure for ComfyUI:
```json
{
  "1": {
    "inputs": {
      "text": "Your prompt here",
      "clip": ["model", 0]
    },
    "class_type": "CLIPTextEncode"
  },
  "2": {
    "inputs": {
      "samples": ["sampler_output", 0],
      "vae": ["model", 1]
    },
    "class_type": "VAEDecode"
  },
  "3": {
    "inputs": {
      "images": ["2", 0],
      "filename_prefix": "output"
    },
    "class_type": "SaveImage"
  }
}
```

## Step 4: Monitor Costs

### While Running
```bash
# RunPod
curl -H "Authorization: Bearer $RUNPOD_API_KEY" \
  https://api.runpod.io/pods

# Vast.ai
curl -H "Authorization: Bearer $VASTAI_API_KEY" \
  https://api.vast.ai/api/v0/instances/
```

### Expected Costs (per video)

**10-15 second clips:**
- RTX 4090: $0.04-0.06
- L40: $0.08-0.10
- A100: $0.15-0.20

**30-60 second clips:**
- RTX 4090: $0.15-0.20
- L40: $0.25-0.30
- A100: $0.50-0.65

## Budget Examples

### $50/month Budget
- **10 short clips/month**
- Use: RTX 4090 on Vast.ai
- Cost: $35-40

### $100/month Budget
- **20 short clips + 5 long-form/month**
- Use: L40 on RunPod
- Cost: $95-100

### $200/month Budget
- **50 short + 10 long-form/month**
- Use: A100 40GB on Vast.ai
- Cost: $180-200

## Stop Costs Immediately

**CRITICAL**: Always stop your pod when done!

### RunPod
```python
manager.stop_pod()  # In your script
```

Or via API:
```bash
curl -X POST \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  https://api.runpod.io/pod/$POD_ID/stop
```

### Vast.ai
```bash
curl -X DELETE \
  -H "Authorization: Bearer $VASTAI_API_KEY" \
  https://api.vast.ai/api/v0/instances/$INSTANCE_ID/
```

### Local Docker
```bash
docker-compose down
```

## Troubleshooting

### "CUDA Out of Memory"
- Use smaller model (Wan2.1 instead of CogVideoX)
- Reduce batch size to 1
- Use RTX 4090 instead of smaller GPUs

### "Generation takes forever"
- Check GPU utilization: `nvidia-smi`
- May need larger GPU (A100 vs RTX 4090)
- Optimize prompt (simpler = faster)

### "Pod won't start"
- Wait 2-3 minutes for full boot
- Check cloud provider dashboard
- Verify API key is correct

### "API key invalid"
- Regenerate key in cloud dashboard
- Export correctly: `export RUNPOD_API_KEY="key"`
- Verify no extra spaces/quotes

## Performance Benchmarks

### Short Clips (720p, ~15 sec output)
- RTX 4090: 5 min generation = $0.04
- L40: 6 min generation = $0.06
- A100 40GB: 3 min generation = $0.05

### Long-form (1080p, ~60 sec output)
- RTX 4090: 15 min generation = $0.11
- L40: 12 min generation = $0.12
- A100 40GB: 8 min generation = $0.13

## Next Steps

1. **Create account** on your chosen provider
2. **Get API key** from settings
3. **Test locally** first (if possible)
4. **Run cost comparison** to confirm budget
5. **Start with small job** ($5-10) to test
6. **Scale up** once comfortable with workflow
7. **Automate** using Python scripts for batch processing

## Common Mistakes to Avoid

❌ Forgetting to stop pod (costs keep accumulating)
❌ Choosing wrong GPU (too expensive for your needs)
❌ Not testing locally first (wasting cloud dollars)
❌ Using high-res models when not needed
❌ Running 24/7 without batching (huge waste)
❌ Committing API keys to git (security risk)

## Cost Optimization Pro Tips

✓ Batch multiple videos in one session (save startup overhead)
✓ Use quantized models (faster + cheaper)
✓ Stop pod immediately after job (prevents accidents)
✓ Monitor nvidia-smi (confirm GPU is being used)
✓ Cache models to persistent volume (skip re-downloads)
✓ Use spot instances on Vast.ai (30% cheaper, if interruption OK)
✓ Schedule jobs during off-peak hours (sometimes cheaper)

## Support Resources

- RunPod Docs: https://docs.runpod.io/
- Vast.ai Docs: https://vast.ai/help/
- ComfyUI: https://github.com/comfyanonymous/ComfyUI
- Models: https://huggingface.co/models

## Getting Help

1. Check `README.md` for detailed documentation
2. Review logs: `docker logs comfyui` or cloud dashboard
3. Test connection: `curl http://localhost:8188/api/system_stats`
4. Check GPU: `nvidia-smi`
5. Verify API key: `echo $RUNPOD_API_KEY` or `echo $VASTAI_API_KEY`

---

**Estimated time to first video:** 15-30 minutes
**First month cost (recommended budget):** $100-150
**Monthly cost at scale:** $500-2000 (depending on volume)
