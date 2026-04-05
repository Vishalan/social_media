# EchoMimic V3 on RunPod Serverless — Avatar Cost Reduction

## Decision

Add EchoMimic V3 on RunPod Serverless as a new avatar provider option (~$0.01-0.03/min), alongside existing providers (VEED Fabric, Kling, HeyGen). The pipeline should be parameterised so the avatar provider is selectable per run — allowing cost-optimised runs via EchoMimic V3 or quality-prioritised runs via VEED Fabric ($4.80/min) without code changes.

## Why EchoMimic V3

- Only open-source model with **half-body + hand gestures + lip sync from audio** — matching VEED/Fabric's key features
- V3 Flash mode uses 5 sampling steps for fast inference
- Requires 12-16GB VRAM (RTX A5000 24GB or RTX 4090 24GB is the sweet spot)
- Apache 2.0 license, already referenced in our codebase (`scripts/avatar_gen/`)
- Comparable lip sync and gesture quality to VEED Fabric at a fraction of the cost

## Why RunPod Serverless

- **Pay-per-second billing, scales to zero** — no idle cost for our sporadic workload (15-30 min GPU/day)
- **No egress fees** — free to download generated videos
- **Sub-200ms cold starts** with FlashBoot
- **Predictable pricing** — no marketplace fluctuation (unlike Vast.ai)
- We have existing RunPod credits and deploy infrastructure (`deploy/runpod/`)

## Cost Comparison

| Provider | Cost/Min | Monthly (75 videos) |
|----------|----------|---------------------|
| VEED Fabric 480p (current) | $4.80 | $150-430 |
| RunPod Serverless A5000 | ~$0.01 | ~$1.20-2.00 |
| RunPod Serverless 4090 | ~$0.03 | ~$2.55-4.25 |
| Vast.ai Interruptible 3090 | ~$0.01 | ~$0.75-1.60 |

## Conditions / Requirements

### Instance Lifecycle Management
- RunPod Serverless must support **automatic spawn on request** — a cold worker spins up only when a generation job is submitted
- Workers must **auto-stop after idle timeout** — no GPU minutes burned waiting for the next job
- Must support **resume/warm workers** — if multiple videos are queued in a batch (e.g. daily pipeline runs 2-3 videos), keep the worker warm between jobs to avoid repeated cold starts
- Verify RunPod Serverless **scales to zero workers** when no jobs are pending — this is the core cost optimization

### API Compatibility
- RunPod Serverless endpoint must accept audio URL + portrait image URL as inputs and return a video URL/file
- Must integrate with our existing `AvatarClient` ABC interface (`generate(audio_url, output_path)`)
- Must support async polling (submit job → poll status → download result) to fit our pipeline's async architecture

### Parameterised Pipeline
- Avatar provider must be selectable via CLI flag (`--avatar-provider echomimic-v3`), config file (`avatar_provider` field), or env var (`AVATAR_PROVIDER`)
- Provider selection already exists in `scripts/avatar_gen/factory.py` — extend it to include `echomimic-v3-runpod`
- Default provider remains VEED Fabric; EchoMimic V3 is opt-in until quality is validated
- Support provider override per-run without changing global config (e.g. `python pipeline.py single --avatar-provider echomimic-v3-runpod`)

### Quality Validation
- Lip sync quality must be benchmarked against VEED Fabric output before promoting as default
- Hand gesture naturalness must be comparable to VEED (side-by-side comparison on 10+ test clips)
- Output must support 9:16 portrait aspect ratio natively (no post-crop needed)

### Fallback Strategy
- Pipeline should auto-fallback to VEED if RunPod job fails or times out after 10 minutes
- Fallback chain configurable: e.g. `echomimic-v3-runpod → veed → kling`

### Deployment
- Create a RunPod Serverless Docker image with EchoMimic V3 weights baked in (for fast cold starts)
- Use RunPod's FlashBoot for sub-second worker startup
- Store model weights on RunPod network volume to avoid re-downloading on each cold start

## Alternatives Considered

| Option | Why Not |
|--------|---------|
| Local RTX 2070 Super (8GB) | Insufficient VRAM — EchoMimic V3 needs 12-16GB |
| Vast.ai Interruptible | Cheapest on paper but unreliable — instances preempted, prices fluctuate |
| MuseTalk 1.5 (local) | Runs on 2070 Super but no hand gestures — lip sync only |
| Hedra Live Avatars ($0.05/min) | Streaming-only, not pre-rendered MP4 |
| SadTalker | Head movement only, no hand gestures |
