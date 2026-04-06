# Fish Audio S2 as Voice Provider — TTS Cost Reduction

## Decision

Add Fish Audio S2 as a new voice provider option alongside ElevenLabs, with a parameterised pipeline (same pattern as avatar providers). Fish Audio S2 becomes the cost-optimised default; ElevenLabs Flash v2.5 serves as the quality fallback.

## Why Fish Audio S2

- **87% cost reduction** vs ElevenLabs Multilingual v2: ~$5.40/mo vs ~$43.20/mo at current volume (~360K chars/month)
- **Voice cloning** is production-grade — short audio clip input, not a community hack
- **Emotional control via inline tags** — `[laugh]`, `[excited]`, `[whispers]`, `[sad]` — a new lever for script engagement that no other provider at this price offers
- Excellent quality, trained on 10M+ hours of audio, 30+ languages
- Python SDK with async support
- **Apache 2.0 self-hostable** — can migrate to RunPod for $0/mo later if volume grows
- 2M+ community voice library for pre-built templates

## Cost Comparison

| Provider | $/M chars | Monthly (360K chars) | Voice Cloning | Emotional Tags |
|----------|-----------|----------------------|---------------|----------------|
| ElevenLabs Multilingual v2 (current) | $120 | $43.20 | Yes | No |
| ElevenLabs Flash v2.5 | $60 | $21.60 | Yes | No |
| Fish Audio S2 (API) | ~$15 | ~$5.40 | Yes | Yes |
| Fish Audio S2 (self-hosted) | $0 | $0 | Yes | Yes |
| OpenAI tts-1 | $15 | ~$5.40 | No | No |
| Google Cloud Neural2 | $16 | ~$5.76 | No | No |
| Kokoro (self-hosted) | $0 | $0 | Limited (KokoClone) | No |

## Conditions / Requirements

### Parameterised Pipeline
- Voice provider must be selectable via CLI flag (`--voice-provider fish-audio`), config file, or env var (`VOICE_PROVIDER`)
- Extend `VoiceGenerator` or create a provider abstraction similar to `AvatarClient` ABC in `scripts/avatar_gen/base.py`
- Default provider switches to Fish Audio S2; ElevenLabs Flash v2.5 is the fallback
- Support provider override per-run without changing global config

### Voice Cloning Strategy
- Clone the CommonCreed brand voice on Fish Audio once voice identity is finalised
- Keep the same voice cloned on ElevenLabs as fallback — voice consistency across providers matters
- Voice cloning quality must be validated side-by-side before switching default

### Emotional Tags Integration
- Script generator (`scripts/content_gen/script_generator.py`) should optionally emit Fish Audio emotional tags in generated scripts
- Tags like `[excited]`, `[laugh]`, `[whispers]` inserted at natural points in the script (hook openings, emphasis moments, CTAs)
- Must be provider-aware — strip tags when sending to ElevenLabs which doesn't support them

### Quality Validation
- Side-by-side listening test: 10+ clips comparing Fish Audio S2 vs ElevenLabs on identical scripts
- Naturalness, pacing, pronunciation accuracy, emotional range
- Validate voice cloning fidelity matches ElevenLabs quality

### Fallback Strategy
- Fallback chain: `fish-audio → elevenlabs-flash → elevenlabs-v2`
- Auto-fallback if Fish Audio API returns error or times out
- Fallback logic at the pipeline level, not within each provider client

### Future Self-Hosting Option
- Fish Audio S2 is Apache 2.0 — can self-host on RunPod serverless (same infra as EchoMimic V3 idea)
- Defer self-hosting until API costs justify the ops overhead
- When ready, deploy alongside EchoMimic V3 on same RunPod infrastructure

## Alternatives Considered

| Option | Why Not Primary |
|--------|----------------|
| Kokoro TTS (self-hosted) | $0 cost is great, #1 TTS Arena quality, but voice cloning (KokoClone) is a community project — not mature enough for brand voice |
| OpenAI tts-1 | Same price as Fish Audio but no voice cloning, only 13 voices, 4K char limit |
| Google Cloud Neural2 | No voice cloning, less natural than top-tier options |
| ElevenLabs Flash v2.5 only | 50% savings but still $21/mo — doesn't solve long-term cost structure |
| Cartesia Sonic 3 | Excellent quality but 2-3x more expensive than Fish Audio |
| Resemble.AI | Enterprise pricing ($80-150/M chars) — overkill for current scale |

## Related Ideas

- [EchoMimic V3 on RunPod Serverless](echomimic-v3-runpod-serverless.md) — same RunPod infra can host Fish Audio S2 self-hosted later
