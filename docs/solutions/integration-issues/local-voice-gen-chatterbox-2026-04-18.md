---
title: "Replace ElevenLabs with local Chatterbox TTS voice cloning on RTX 3090"
date: 2026-04-18
category: integration-issues
module: voiceover-pipeline
problem_type: integration_issue
component: tooling
symptoms:
  - "ElevenLabs API costs $5-22/month for voice generation"
  - "Dependency on external API for core pipeline function"
root_cause: missing_tooling
resolution_type: environment_setup
severity: medium
tags:
  - chatterbox
  - tts
  - voice-cloning
  - elevenlabs
  - gpu
  - cost-optimization
---

# Replace ElevenLabs with local Chatterbox TTS voice cloning on RTX 3090

## Problem

The CommonCreed pipeline used ElevenLabs API ($5-22/month) for voice-over generation. With an RTX 3090 (24 GB VRAM) available, a local open-source TTS model can eliminate this recurring cost while matching or exceeding ElevenLabs quality.

## Symptoms

- Monthly ElevenLabs bill for voice generation
- Pipeline dependency on external API (latency, rate limits, outages)

## What Didn't Work

- **Artificial post-processing for depth** — attempted pitch shifting (-8%), heavy bass EQ (+8dB at 80Hz), nasal frequency cut (-3dB at 800Hz) via ffmpeg. Produced unnatural "through a tube" sound. The raw Chatterbox clone without post-processing sounded better.

## Solution

### Model selection: Chatterbox (Resemble AI)
- MIT license, 5-7 GB VRAM, beats ElevenLabs in 63.75% of blind A/B tests
- Zero-shot voice cloning from 10-30s reference audio
- Emotion exaggeration control (0.0-1.0)
- ~18 seconds to generate 1 minute of speech on RTX 3090

### Voice reference preparation
1. Extract audio from a video of the owner speaking: `ffmpeg -i video.mp4 -vn -acodec pcm_s16le -ar 44100 -ac 1 raw.wav`
2. Separate vocals from background music using **demucs** (GPU-accelerated, 3 seconds): `apply_model(htdemucs_model, wav)` → extract vocals track (index 3)
3. Trim to 30 seconds, convert to mono 24kHz: saved as `/opt/commoncreed/assets/vishalan_voice_ref.wav`

### Pipeline integration
- `scripts/voiceover/chatterbox_generator.py` — `ChatterboxVoiceGenerator` class matching `VoiceGenerator` interface
- Factory function `make_voice_generator(config)` in `scripts/voiceover/__init__.py` picks the provider based on the `voice_provider` config key
- `scripts/commoncreed_pipeline.py` calls the factory (not `VoiceGenerator` directly)
- Config via `.env`: `VOICE_PROVIDER=elevenlabs` is the default for backward compatibility; flip to `chatterbox` + set `CHATTERBOX_REFERENCE_AUDIO=/opt/commoncreed/assets/vishalan_voice_ref.wav` when the local GPU + reference clip are in place
- Runtime deps for chatterbox (`chatterbox-tts`, `torchaudio`) are imported lazily inside `_load_model`, so the factory + class construct cleanly in environments where those packages aren't installed (e.g. CI, production sidecar without GPU passthrough)

### Deployment state (2026-04-19)
Code wired end-to-end and tested, but **chatterbox is NOT the default in production** yet. Two prerequisites remain:

1. **GPU passthrough to the sidecar container** — current `deploy/portainer/docker-compose.yml` does not grant the sidecar GPU access. Either add `deploy.resources.reservations.devices` for NVIDIA, or run chatterbox as a separate HTTP sidecar (like Remotion) so the GPU-less sidecar can call it over the compose network.
2. **Reference audio upload** — `/opt/commoncreed/assets/vishalan_voice_ref.wav` must exist on the Ubuntu host.

Once both are in place: set `VOICE_PROVIDER=chatterbox` + `CHATTERBOX_REFERENCE_AUDIO=/opt/commoncreed/assets/vishalan_voice_ref.wav` in `/opt/commoncreed/.env` and redeploy.

## Why This Works

Chatterbox uses a flow-matching diffusion architecture (PerthNet) that produces natural prosody from short reference audio. The model runs entirely on the local GPU at 5-7 GB VRAM, leaving headroom for other workloads (Ollama uses 5.5 GB). Generation speed (~55 it/s on RTX 3090) means 1 minute of speech generates in ~18 seconds — faster than ElevenLabs API round-trip.

## Prevention

- Use the factory pattern (`make_voice_generator`) for all voice generation — never instantiate `VoiceGenerator` directly in pipeline code
- Keep the ElevenLabs provider as a fallback for quality comparison or if GPU is busy
- Store voice reference audio in `assets/` with a descriptive name — it's the "voice identity" for the brand
- When changing the brand voice, replace only the reference WAV file — no code change needed

## Related Issues

- GPU cost optimization brainstorm: `docs/brainstorms/2026-04-16-gpu-cost-optimization-requirements.md`
- EVGA 3090 fan control fix: `docs/solutions/integration-issues/commoncreed-pipeline-expansion-2026-04-12.md`
- Server migration: `docs/solutions/integration-issues/server-migration-synology-to-ubuntu-2026-04-11.md`
