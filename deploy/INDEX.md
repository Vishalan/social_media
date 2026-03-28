# GPU Cloud Deployment Suite - File Index

Complete reference for all deployment scripts, configurations, and documentation.

## 📋 Documentation Files

### Start Here
- **QUICKSTART.md** - 5-minute setup guide to get running fast
  - For: People who want to start immediately
  - Time: 5-10 minutes
  - Outcome: First video generation

- **DEPLOYMENT_OPTIONS.md** - Complete provider comparison
  - For: Choosing between RunPod, Vast.ai, Lambda Labs, Local
  - Covers: Cost, reliability, features, recommendations
  - Includes: Decision matrix and migration path

- **README.md** - Full technical documentation
  - For: Comprehensive reference
  - Covers: All setup steps, troubleshooting, best practices
  - Includes: Model information, security guidelines

## 🐍 Python Scripts

### Cost Analysis
- **gpu_cost_comparison.py** - Cost calculator and comparison tool
  - Location: `/deploy/gpu_cost_comparison.py`
  - Run: `python3 gpu_cost_comparison.py`
  - Output: Cost tables, monthly estimates, ROI analysis
  - Generates: `gpu_pricing.json` for programmatic use

### RunPod Workflow
- **runpod/run_workflow.py** - ComfyUI workflow executor for RunPod
  - Location: `/deploy/runpod/run_workflow.py`
  - Dependencies: `pip install -r requirements.txt`
  - Features:
    - Pod creation and lifecycle management
    - Workflow submission and status polling
    - Result downloading
    - Auto-shutdown for cost control
    - Idle timeout detection
  - Usage: See example at bottom of file

## 🔧 Bash Setup Scripts

### RunPod Setup
- **runpod/setup_comfyui.sh** - ComfyUI installation for RunPod
  - Location: `/deploy/runpod/setup_comfyui.sh`
  - Run: `bash runpod/setup_comfyui.sh`
  - Installs:
    - ComfyUI (latest)
    - ComfyUI-Manager
    - Video models (Wan2.1, CogVideoX-5B)
    - SDXL base model
    - Custom nodes for video processing
  - Output: Ready-to-use ComfyUI API

### Vast.ai Setup
- **vastai/setup.sh** - Automated instance setup on Vast.ai
  - Location: `/deploy/vastai/setup.sh`
  - Run: `bash vastai/setup.sh`
  - Features:
    - Query Vast.ai for cheapest GPUs
    - Automatic instance creation
    - Model downloading
    - Connection info output
    - Saves config to ~/.vast_instance.json

## 🐳 Docker Configuration

### Docker Compose
- **docker-compose.yml** - Local ComfyUI setup with GPU support
  - Location: `/deploy/docker-compose.yml`
  - Run: `docker-compose up`
  - Features:
    - NVIDIA GPU support
    - Volume persistence
    - Health checks
    - Optional Nginx proxy
  - Access: http://localhost:8188

### Nginx Config
- **nginx.conf** - Reverse proxy configuration
  - Location: `/deploy/nginx.conf`
  - Used by: docker-compose.yml (optional)
  - Features:
    - Request proxying
    - WebSocket support
    - Gzip compression
    - Long request timeout

## 📦 Dependencies

- **requirements.txt** - Python package dependencies
  - Location: `/deploy/requirements.txt`
  - Install: `pip install -r requirements.txt`
  - Packages:
    - runpod (RunPod API)
    - requests (HTTP client)
    - rich (Terminal formatting)
    - pydantic (Data validation)
    - python-dotenv (Environment variables)

## 📁 Directory Structure

```
deploy/
├── INDEX.md                    # This file
├── README.md                   # Full documentation
├── QUICKSTART.md               # Quick start guide
├── DEPLOYMENT_OPTIONS.md       # Provider comparison
├── gpu_cost_comparison.py      # Cost analysis tool
├── requirements.txt            # Python dependencies
├── docker-compose.yml          # Local setup
├── nginx.conf                  # Reverse proxy config
│
├── runpod/
│   ├── setup_comfyui.sh        # ComfyUI installation
│   └── run_workflow.py         # Workflow executor
│
└── vastai/
    └── setup.sh                # Instance setup
```

## 🚀 Quick Reference by Task

### "I want to check costs first"
→ Run: `python3 gpu_cost_comparison.py`
→ Read: `DEPLOYMENT_OPTIONS.md`

### "I want to start with RunPod"
→ Read: `QUICKSTART.md`
→ Set: `export RUNPOD_API_KEY="..."`
→ Run: `python3 runpod/run_workflow.py`

### "I want the cheapest option (Vast.ai)"
→ Read: `DEPLOYMENT_OPTIONS.md`
→ Set: `export VASTAI_API_KEY="..."`
→ Run: `bash vastai/setup.sh`

### "I have a local GPU"
→ Run: `docker-compose up`
→ Open: `http://localhost:8188`

### "I need help choosing"
→ Read: `DEPLOYMENT_OPTIONS.md` → Decision Matrix

## 📊 Cost Quick Reference

| GPU | Provider | Cost/Hour | Cost/Video (5min) | Cost/Month (20 videos) |
|-----|----------|-----------|-------------------|------------------------|
| RTX 4090 | Vast.ai | $0.30 | $0.04 | $60 |
| RTX 4090 | RunPod | $0.44 | $0.06 | $88 |
| L40 | Vast.ai | $0.45 | $0.06 | $90 |
| L40 | RunPod | $0.60 | $0.10 | $120 |
| A100 40GB | Vast.ai | $0.70 | $0.10 | $140 |
| A100 40GB | RunPod | $0.95 | $0.16 | $190 |

## 🔐 Security Reminders

1. **Never commit API keys** to git
2. **Use environment variables** for secrets
3. **Rotate keys regularly** on provider dashboards
4. **Don't share credentials** in logs or configs
5. **Use .gitignore** to exclude sensitive files

## ⚠️ Cost Control

**CRITICAL: Always stop pods when done!**

- RunPod: `manager.stop_pod()` (in Python) or dashboard
- Vast.ai: `curl -X DELETE` instance API
- Local: `docker-compose down`

Forgetting to stop pods = unexpected charges

## 📈 Typical Workflow

1. **Analyze** costs: `python3 gpu_cost_comparison.py`
2. **Choose provider** based on budget and needs
3. **Create account** on chosen provider
4. **Get API key** from provider dashboard
5. **Test locally** (optional): `docker-compose up`
6. **Run small job** ($5-20) to validate
7. **Monitor costs** during runs
8. **Scale up** based on results
9. **Automate** using provided scripts
10. **Optimize** based on real performance data

## 🆘 Troubleshooting

### Script won't run
- Verify Python 3.8+: `python3 --version`
- Install dependencies: `pip install -r requirements.txt`
- Check path: `pwd` should be `/deploy`

### API key rejected
- Regenerate key in provider dashboard
- Check for extra spaces: `echo $RUNPOD_API_KEY`
- Verify correct provider (RunPod vs Vast.ai)

### GPU out of memory
- Use smaller model (Wan2.1 vs CogVideoX)
- Reduce batch size to 1
- Check nvidia-smi for actual usage

### Pod won't start
- Wait 2-3 minutes for initialization
- Check provider dashboard status
- Verify API key permissions

## 📚 External Resources

- RunPod: https://www.runpod.io/
- Vast.ai: https://vast.ai/
- Lambda Labs: https://lambdalabs.com/
- ComfyUI: https://github.com/comfyanonymous/ComfyUI
- Models: https://huggingface.co/

## 📝 File Descriptions

### Documentation
- INDEX.md (this file) - Navigation and quick reference
- README.md - Complete technical documentation
- QUICKSTART.md - 5-minute getting started guide
- DEPLOYMENT_OPTIONS.md - Provider comparison and recommendations

### Executable Scripts
- gpu_cost_comparison.py - Cost analysis tool (requires Python 3)
- runpod/run_workflow.py - RunPod workflow executor (requires runpod SDK)
- runpod/setup_comfyui.sh - ComfyUI installer (requires bash)
- vastai/setup.sh - Vast.ai setup (requires bash)

### Configuration
- docker-compose.yml - Docker configuration (requires Docker + nvidia-docker)
- nginx.conf - Nginx proxy config (used by docker-compose)
- requirements.txt - Python package list (use with pip)

## ✅ Setup Checklist

Before running any scripts:

- [ ] Read relevant documentation
- [ ] Create account on chosen provider
- [ ] Get API key from provider dashboard
- [ ] Set environment variable: `export KEY="..."`
- [ ] Install Python dependencies: `pip install -r requirements.txt`
- [ ] Verify Python version: `python3 --version`
- [ ] Test API connectivity: `python3 gpu_cost_comparison.py`
- [ ] Check costs: Review output from cost comparison
- [ ] Run small test: $5-20 test job
- [ ] Monitor actively: Watch dashboard while running
- [ ] Stop pod immediately: After job completion

## 🎯 Next Steps

1. Start with: **QUICKSTART.md**
2. Then read: **DEPLOYMENT_OPTIONS.md**
3. Run: **gpu_cost_comparison.py**
4. Choose provider and follow its setup script
5. Refer to: **README.md** for detailed help

---

Last updated: March 2026
All pricing data subject to change - verify with provider
