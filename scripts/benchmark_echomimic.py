#!/usr/bin/env python3
"""
EchoMimic V3 Quality Benchmark — RunPod GPU Pod

Spins up a temporary RunPod GPU pod, installs EchoMimic V3,
generates avatar clips from the same audio segments used in
recent VEED runs, and saves side-by-side comparisons.

Usage:
    python benchmark_echomimic.py

Requires:
    RUNPOD_API_KEY in environment or ../.env
    Existing audio segments in output/debug_avatar/*_sent_to_veed.mp3
    Portrait image at assets/logos/owner-portrait-9x16.jpg
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Load .env from parent directory
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

import runpod


def main():
    api_key = os.environ.get("RUNPOD_API_KEY")
    if not api_key:
        print("ERROR: RUNPOD_API_KEY not set")
        sys.exit(1)

    runpod.api_key = api_key

    # Check for existing audio segments
    debug_dir = Path("output/debug_avatar")
    seg_names = ["hook", "pip1", "pip2", "cta"]
    audio_files = {n: debug_dir / f"{n}_sent_to_veed.mp3" for n in seg_names}

    missing = [n for n, p in audio_files.items() if not p.exists()]
    if missing:
        print(f"ERROR: Missing audio segments: {missing}")
        print("Run a SMOKE_USE_VEED=1 smoke test first to generate debug assets.")
        sys.exit(1)

    portrait = Path("../assets/logos/owner-portrait-9x16.jpg")
    if not portrait.exists():
        portrait = Path("assets/logos/owner-portrait-9x16.jpg")
    if not portrait.exists():
        print("ERROR: Portrait image not found")
        sys.exit(1)

    print("=" * 60)
    print("EchoMimic V3 Quality Benchmark")
    print("=" * 60)
    print(f"Audio segments: {list(audio_files.keys())}")
    print(f"Portrait: {portrait}")
    print()

    # Step 1: Create GPU pod
    print("↗  Creating RunPod GPU pod (RTX A5000, 24GB VRAM)...")

    pod = runpod.create_pod(
        name="echomimic-v3-benchmark",
        image_name="runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04",
        gpu_type_id="NVIDIA RTX A5000",
        gpu_count=1,
        volume_in_gb=30,
        ports="8888/http",
        docker_args="",
    )

    pod_id = pod["id"]
    print(f"✓  Pod created: {pod_id}")
    print("   Waiting for pod to be ready...")

    # Wait for pod to start
    for attempt in range(60):
        status = runpod.get_pod(pod_id)
        state = status.get("desiredStatus", "unknown")
        runtime = status.get("runtime", {})
        if runtime and runtime.get("uptimeInSeconds", 0) > 0:
            print(f"✓  Pod is running (uptime: {runtime['uptimeInSeconds']}s)")
            break
        time.sleep(10)
        if attempt % 3 == 0:
            print(f"   Still waiting... (state: {state})")
    else:
        print("ERROR: Pod failed to start in 10 minutes")
        runpod.terminate_pod(pod_id)
        sys.exit(1)

    print()
    print(f"Pod ID: {pod_id}")
    print("Connect via: runpodctl exec {pod_id} -- bash")
    print()
    print("NEXT STEPS (manual for now):")
    print("1. SSH into the pod")
    print("2. Install EchoMimic V3:")
    print("   git clone https://github.com/antgroup/echomimic_v3.git")
    print("   cd echomimic_v3 && pip install -r requirements.txt")
    print("   python download_models.py")
    print("3. Upload audio segments + portrait image")
    print("4. Run inference on each segment")
    print("5. Download generated clips")
    print("6. Terminate pod when done:")
    print(f"   python -c \"import runpod; runpod.api_key='{api_key[:8]}...'; runpod.terminate_pod('{pod_id}')\"")
    print()

    input("Press Enter when you've finished generating clips (or Ctrl+C to abort)...")

    # Cleanup
    print("↗  Terminating pod...")
    runpod.terminate_pod(pod_id)
    print("✓  Pod terminated. Check output/benchmark_echomimic/ for results.")


if __name__ == "__main__":
    main()
