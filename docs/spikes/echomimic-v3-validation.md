---
date: 2026-03-27
spike: echomimic-v3-validation
status: pending
---

# EchoMimic V3 Validation Spike

**Gate for:** Full pipeline build (Units 1-9 of `2026-03-27-001-feat-commoncreed-avatar-pipeline-plan.md`)

**Do not build the full pipeline until this spike passes.**

---

## VS1 — Quality Gate

### Objective

Score EchoMimic V3 output on owner's reference footage ≥ 4/5 average across three axes before committing to build.

### Step 1: Provision GPU Instance

```bash
# RunPod: launch RTX 4090 pod (24GB VRAM)
# Target instance: ~$0.69/hr
# Vast.ai alternative: ~$0.44/hr for RTX 4090

# SSH into instance
ssh root@<instance-ip>
```

### Step 2: Install EchoMimic V3

```bash
# System deps
apt-get update -qq && apt-get install -y ffmpeg libgl1-mesa-glx git wget

# Clone
cd /workspace
git clone https://github.com/antgroup/EchoMimicV3.git
cd EchoMimicV3

# Python deps (Python 3.10, CUDA 12.1+)
pip install -r requirements.txt
```

### Step 3: Download Checkpoints

```bash
# Wan2.1 base (also used by existing b-roll workflow)
python -c "
from huggingface_hub import snapshot_download
snapshot_download('Wan-AI/Wan2.1-T2V-1.3B', local_dir='/workspace/models/wan2.1-1.3b')
"

# EchoMimic V3 weights
python -c "
from huggingface_hub import snapshot_download
snapshot_download('antgroup/EchoMimicV3', local_dir='/workspace/models/echomimic_v3')
"
```

### Step 4: Prepare Reference Footage

Record or upload a reference video meeting these specs:
- Resolution: 1080p or higher
- Frame rate: 24fps+
- Duration: 10-30 seconds
- Lighting: well-lit, no harsh shadows
- Background: neutral or blurred
- Content: speaking naturally with clear lip movement
- Format: H.264 or ProRes

Upload to instance:
```bash
scp owner_reference.mp4 root@<instance-ip>:/workspace/reference.mp4
```

**Security:** Delete the reference video from the instance immediately after VS1 is complete. Do not snapshot the instance with the reference video present.

### Step 5: Prepare Test Audio

Create or use a 45-second audio clip (MP3/WAV) of the owner's voice reading sample tech news content.

```bash
scp test_audio_45s.mp3 root@<instance-ip>:/workspace/test_audio.mp3
```

### Step 6: Run Inference

```bash
# Check EchoMimic V3 inference script — exact command depends on repo structure
# Typical invocation:
python inference.py \
  --reference_video /workspace/reference.mp4 \
  --audio_path /workspace/test_audio.mp3 \
  --output_path /workspace/output_vs1.mp4 \
  --width 576 \
  --height 1024 \
  --fps 24

# Download output
scp root@<instance-ip>:/workspace/output_vs1.mp4 ./output_vs1.mp4
```

### Step 7: Score Output

View `output_vs1.mp4` and score each axis on a 1-5 scale. Blind scoring preferred (show to someone unfamiliar with the project).

| Axis | Score (1-5) | Notes |
|------|-------------|-------|
| Lip-sync accuracy | | How closely lip movement matches audio |
| Natural motion | | No jitter, artifacts, or unnatural blending |
| Identity consistency | | Owner's face preserved throughout clip |
| **Average** | | Must be ≥ 4.0 to proceed |

**Scoring guide:**
- 5: HeyGen-quality or better
- 4: Clearly the owner's face, convincing lip sync, minor artifacts only
- 3: Recognizable but noticeable artifacts or sync issues
- 2: Major quality problems (wrong face, significant artifacts)
- 1: Unusable output

### Decision

| Average Score | Action |
|---------------|--------|
| ≥ 4.0 | ✅ **VS1 PASS** — Proceed to VS2 |
| < 4.0 | ❌ **VS1 FAIL** — Evaluate Duix.Avatar (VS3) |

---

## VS2 — Cost Gate

### Objective

Verify GPU cost per video fits within $2/video cap.

### Measure Inference Time

```bash
# Time the 45-second clip inference
time python inference.py \
  --reference_video /workspace/reference.mp4 \
  --audio_path /workspace/test_audio.mp3 \
  --output_path /workspace/output_vs2.mp4
```

### Calculate Cost

```
cost_per_video = (inference_seconds / 3600) * instance_hourly_rate
```

| Instance | Rate | Max inference time for $2 cap |
|----------|------|-------------------------------|
| Vast.ai RTX 4090 | $0.44/hr | 16 minutes 22 seconds |
| RunPod RTX 4090 | $0.69/hr | 10 minutes 26 seconds |

For a pipeline with 3 videos/day + b-roll generation, total GPU time must also fit within budget. Estimate: if 3 × avatar inference + 3 × b-roll generation > 1.5 hours, reconsider instance selection.

### Decision

| Cost | Action |
|------|--------|
| ≤ $2/video | ✅ **VS2 PASS** — Proceed to build |
| > $2/video | ❌ **VS2 FAIL** — Evaluate VS3 or use L40/cheaper instance |

---

## VS3 — Fallback Evaluation (only if VS1 or VS2 fail)

### Fallback Chain

```
EchoMimic V3 (VS1/VS2)
  └─► Duix.Avatar (VS3a)
        └─► HeyGen API bridge (VS3b)
```

### VS3a: Duix.Avatar

Duix.Avatar is a more direct HeyGen clone with an API-first design. Evaluate if EchoMimic V3 fails.

- Docs: https://docs.duix.com/avatar
- Pricing: Check current pricing; verify $2/video cost cap
- Quality: More production-tested than EchoMimic V3; less open-source

### VS3b: HeyGen API Bridge

If both open-source options fail:

- Plan: Use HeyGen API ($29-89/month) as a temporary bridge
- Trigger: Remove this bridge when a better open-source option matures
- Cost: HeyGen API pricing varies; verify it fits within budget
- This is a temporary measure, not a permanent solution

---

## Cleanup

```bash
# Delete reference video from GPU instance immediately
ssh root@<instance-ip> "rm -f /workspace/reference.mp4"

# Terminate instance (do not snapshot with reference video present)
# RunPod: Stop pod from dashboard
# Vast.ai: Destroy instance from dashboard
```

---

## Record Results Here

```
Date: ___________
Instance: ___________  (provider + GPU + $/hr)

VS1 Results:
  Lip-sync accuracy: ___ / 5
  Natural motion:    ___ / 5
  Identity:          ___ / 5
  Average:           ___ / 5
  Pass/Fail: ___

VS2 Results:
  Inference time (45s clip): ___ seconds
  Cost per video:            $___
  Pass/Fail: ___

Decision: [ ] Proceed with EchoMimic V3  [ ] Evaluate Duix.Avatar  [ ] HeyGen API bridge

Notes:
```
