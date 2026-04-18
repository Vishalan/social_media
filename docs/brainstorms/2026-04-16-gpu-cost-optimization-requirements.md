---
date: 2026-04-16
topic: gpu-cost-optimization
---

# RTX 3090 GPU Cost Optimization — Local Voice + Avatar Generation

## Problem Frame

The pipeline pays for ElevenLabs TTS ($5-22/month) and VEED Fabric avatar ($0.15/sec) when both can run locally on the RTX 3090 (24 GB VRAM) at comparable or better quality, for zero ongoing cost.

## Requirements

### Voice Generation (Replace ElevenLabs)

- R1. Install Chatterbox TTS on the server for local voice generation
- R2. Support two voice modes: (a) clone owner's voice from 30s reference audio, (b) AI-generated Indian English voice
- R3. Generate quality samples of both modes for owner comparison before committing
- R4. Integrate as a new provider in `scripts/voiceover/voice_generator.py` alongside ElevenLabs (configurable, not replacement)
- R5. Voice output must be natural enough for short-form reel content (30-60s)

### Avatar Generation (Resume Wan2.2-S2V — paused plan)

- R6. Resume `docs/plans/2026-04-15-001-feat-wan22-avatar-provider-plan.md` — ComfyUI workflow creation + quality comparison
- R7. Generate a sample avatar clip with Wan2.2-S2V for owner quality review before committing

## Success Criteria

- Owner approves voice quality from local samples (blind comparison vs ElevenLabs)
- Owner approves avatar quality from Wan2.2-S2V sample (comparison vs EchoMimic V3)
- Both run locally on RTX 3090 without OOM
- $330-534/year in API costs eliminated

## Scope Boundaries

- Not replacing Anthropic API for creative writing (captions, scripts) — stays on Sonnet
- Not fine-tuning any models — using pre-trained weights
- Quality testing before pipeline integration — no automatic switchover

## Key Decisions

- **Chatterbox over F5-TTS**: MIT license (F5-TTS weights are CC-BY-NC), beats ElevenLabs in 63.75% blind tests, emotion control
- **Clone + AI voice both tested**: Owner needs to hear both before choosing the brand voice
- **Wan2.2-S2V already downloaded**: 46 GB model on server, ComfyUI running. Just need workflow + test.

## Outstanding Questions

### Deferred to Planning

- [Affects R2][Technical] Best reference audio format/length for Chatterbox Indian English cloning
- [Affects R4][Technical] Whether Chatterbox chunking is needed for 60s clips or if it handles long-form natively
- [Affects R6][Needs research] FantasyTalking workflow requires additional model downloads (fantasytalking_fp16.safetensors, wav2vec2, CLIP vision, VAE, T5)

## Next Steps

→ Install Chatterbox, generate voice samples, present to owner
→ Resume Wan2.2-S2V avatar plan
