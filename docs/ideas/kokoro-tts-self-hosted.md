# Kokoro TTS Self-Hosted — Zero-Cost Voice Provider

## Decision

Add Kokoro TTS as a self-hosted voice provider option for zero ongoing cost. Positioned as a future upgrade path once voice cloning maturity improves, or as an immediate option for non-brand-voice content where cloning isn't required.

## Why Kokoro

- **$0/mo** — Apache 2.0, fully self-hosted
- **Was #1 on TTS Arena** leaderboard — quality punches far above its 82M parameter size
- **Runs on local hardware** — only 82M params, works on CPU or the existing RTX 2070 Super (8GB)
- **36x real-time** on a free Colab GPU — inference is extremely fast
- **OpenAI-compatible API wrapper** available (kokoro-web) — near drop-in replacement
- Supports English, French, Korean, Japanese, Mandarin

## Why Not Primary (Yet)

- **Voice cloning (KokoClone) is a community project** — not production-grade for a brand voice you're building an audience around
- Fewer languages than Fish Audio S2 (5 vs 30+)
- No emotional control tags like Fish Audio's `[laugh]`, `[excited]`
- Community-maintained, no commercial support

## When This Becomes the Right Move

- KokoClone matures to production-grade voice cloning quality
- You need a zero-cost TTS for high-volume batch content (e.g. repurposing long-form into dozens of clips)
- You want a local-first pipeline with no API dependencies at all
- Non-brand-voice content (e.g. secondary characters, narration variations) where stock voices are fine

## Conditions / Requirements

### Local Deployment
- Must run on the RTX 2070 Super (8GB) — confirmed viable at 82M params
- Deploy via Docker with kokoro-web for OpenAI-compatible API endpoint
- No cloud cost, no GPU rental needed

### Pipeline Integration
- Add as a voice provider option: `--voice-provider kokoro`
- Same parameterised pipeline as Fish Audio and ElevenLabs
- OpenAI-compatible API means the client can reuse OpenAI TTS client code with a different base URL

### Quality Gate
- Side-by-side listening test vs Fish Audio S2 and ElevenLabs on 10+ clips before enabling
- Acceptable for non-cloned voice content; must re-evaluate once KokoClone improves

## Cost Comparison

| Provider | Monthly Cost | Runs Locally | Voice Cloning |
|----------|-------------|--------------|---------------|
| Kokoro (self-hosted) | $0 | Yes (2070 Super) | Limited (KokoClone) |
| Fish Audio S2 (API) | ~$5.40 | No | Yes (production-grade) |
| Fish Audio S2 (self-hosted) | $0 | No (needs 24GB+ GPU) | Yes |
| ElevenLabs Flash v2.5 | ~$21.60 | No | Yes |

## Related Ideas

- [Fish Audio S2 Voice Provider](fish-audio-s2-voice-provider.md) — recommended primary replacement for ElevenLabs
- [EchoMimic V3 on RunPod Serverless](echomimic-v3-runpod-serverless.md) — RunPod infra for GPU-dependent models
