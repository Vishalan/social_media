---
title: "AI-Driven B-Roll Type Selection with GPU Phase-Gating"
date: 2026-03-29
category: workflow-issues
module: broll_gen
problem_type: workflow_issue
component: tooling
symptoms:
  - "GPU pod spun up every day even when content did not need AI video"
  - "All topics got identical generic AI b-roll (glowing circuits) regardless of content type"
  - "No mechanism to select between browser screenshot, image montage, code walkthrough, or stats card"
  - "FFmpeg xfade produced black frames between Ken Burns clips"
  - "Single-point ComfyUI failure meant zero b-roll with no fallback"
root_cause: missing_workflow_step
resolution_type: tooling_addition
severity: high
related_components:
  - background_job
  - development_workflow
tags:
  - broll
  - ffmpeg
  - anthropic-sdk
  - constrained-decoding
  - json-schema
  - gpu-cost-optimization
  - pipeline-phase-gating
  - playwright
---

# AI-Driven B-Roll Type Selection with GPU Phase-Gating

## Problem

The @commoncreed pipeline's b-roll generation was a single-path stub that unconditionally called ComfyUI/Wan2.1 on a GPU pod for every video, producing generic AI visuals (glowing circuits, abstract tech) with no relationship to the specific topic being discussed. This required a $0.69/hr RunPod GPU pod every day (~$0.35/day fixed cost) even when CPU-only b-roll would produce far more engaging, topic-relevant footage at zero GPU cost.

## Symptoms

- B-roll visually disconnected from narration — abstract AI video had no relationship to the topic
- Daily GPU pod cost even when no GPU generation was needed
- No fallback strategy — a single ComfyUI failure meant the video had no b-roll
- Every topic got the same treatment regardless of whether it involved code, data, or browser-accessible content
- Viewer disengagement from generic, non-topical visuals

## What Didn't Work

The original stub treated b-roll as a one-step GPU task — pick a Wan2.1 workflow, run it, done. This was insufficient because:

1. **No content awareness** — a topic about a new API release benefits from code walkthrough b-roll; a stats-heavy video needs a stats card; an article topic deserves a browser visit scroll. One visual style cannot cover all cases.
2. **No cost gating** — the GPU pod was unconditional. Days where all topics could use CPU generators still started the pod.
3. **No resilience** — one generator with no fallback is a fragile pipeline.

## Solution

### Architecture: Two-Phase CPU-First Pipeline

```
Phase 1 (CPU, pod OFF):
  BrollSelector.select(topic, url, script)
    → AsyncAnthropic + output_config json_schema → [primary, fallback]
  BrollFactory.make(type).generate(job, target_duration_s, output_path)
    ├─ success → job.broll_path set, job.needs_gpu_broll = False
    └─ failure → try fallback
         ├─ success → job.broll_path set
         └─ failure → job.needs_gpu_broll = True

Phase 2 gate:
  if not any(j.needs_gpu_broll for j in jobs):
      skip pod entirely  # $0 GPU cost day
  else:
      start pod → AiVideoGenerator for flagged jobs only
```

**Five generators — four CPU, one GPU fallback:**

| Type | Method | Cost |
|------|---------|------|
| `browser_visit` | Playwright screenshot + FFmpeg crop scroll | $0 |
| `image_montage` | Pexels/Bing/OG image + Ken Burns zoompan | $0 |
| `code_walkthrough` | Claude + Pygments render + typewriter reveal | Haiku tokens only |
| `stats_card` | Claude json_schema + PIL frames + FFmpeg concat | Haiku tokens only |
| `ai_video` | ComfyUI/Wan2.1 (GPU fallback) | $0.69/hr only when needed |

---

### BrollSelector — Constrained Decoding via json_schema

Uses `output_config.format` in Anthropic SDK 0.86.0 to guarantee a valid enum response:

```python
response = await client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=100,
    system="...",
    messages=[{"role": "user", "content": f"Topic: {topic_title}..."}],
    output_config={
        "format": {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "primary": {"type": "string", "enum": ["browser_visit","image_montage","code_walkthrough","stats_card","ai_video"]},
                    "fallback": {"type": "string", "enum": ["browser_visit","image_montage","code_walkthrough","stats_card","ai_video"]}
                },
                "required": ["primary","fallback"],
                "additionalProperties": False  # required for strict validation
            }
        }
    }
)
data = json.loads(response.content[0].text)
```

Always wrap in `try/except` with a hardcoded safe default — selector failure must never block the pipeline:

```python
try:
    return [data["primary"], data["fallback"]]
except Exception:
    logger.warning("BrollSelector failed — using safe default")
    return ["image_montage", "ai_video"]  # works for any topic
```

---

### FFmpeg Ken Burns — setpts=PTS-STARTPTS Is Required

**Without `setpts=PTS-STARTPTS` after `zoompan`, cross-fades between clips produce black frames** because timestamps are not reset before `xfade`.

```python
per_image_filter = (
    f"scale=1920:1080:force_original_aspect_ratio=decrease,"
    f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
    f"zoompan=z='zoom+0.001':d={int(fps*per_clip_s)}:s=1920x1080,"
    f"setpts=PTS-STARTPTS,"  # CRITICAL — resets timestamps before xfade
    f"scale=1080:540"
)
# xfade offset = clip_index * per_clip_s - (fade_duration / 2)
```

---

### FFmpeg Scroll for Browser Screenshots

```python
cmd = [
    "ffmpeg", "-y",
    "-loop", "1", "-i", screenshot_png,
    "-t", str(target_duration_s),
    "-vf", f"scale=1080:-1,crop=1080:540:0:'(ih-540)*t/{target_duration_s}'",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
    output_path
]
```

Use `scale=1080:-1` (preserve aspect ratio) before `crop` — never assume screenshot dimensions.

---

### FFmpeg Concat Demuxer for Frame Sequences

Used for typewriter (code_walkthrough) and stats cards. The last frame **must** be repeated with a short duration or FFmpeg drops it:

```python
with open(concat_file, "w") as f:
    for png_path in frame_paths:
        f.write(f"file '{png_path}'\nduration {frame_duration:.3f}\n")
    # Repeat last frame — FFmpeg quirk: last frame is otherwise dropped
    f.write(f"file '{frame_paths[-1]}'\nduration 0.001\n")

cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), ...]
```

---

### BrowserVisit — Paywall Detection

After page load, check word count before continuing. Paywalled/login-gated pages produce very little body text:

```python
body_text = await page.inner_text("body")
if len(body_text.split()) < 200:
    raise BrollError("paywall or insufficient content")
```

---

### VideoJob Schema Extension

Two fields wire the two phases together:

```python
@dataclass
class VideoJob:
    # ... existing fields ...
    broll_type: str = ""           # winning generator name, for logging
    needs_gpu_broll: bool = False  # True only when all CPU generators failed
```

---

### Phase 2 Skip-Completed-Jobs Guard (C4)

Phase 2 must skip jobs where Phase 1 already set `broll_path`, or it will overwrite a successful CPU result:

```python
async def _phase2_broll_jobs(self, jobs: list[VideoJob]) -> None:
    for job in jobs:
        if job.broll_path:  # C4: skip — Phase 1 already handled
            continue
        # ... GPU generation ...
```

---

### Pexels API Authentication

Pexels uses a bare API key in the Authorization header — **not** a Bearer token:

```python
headers = {"Authorization": pexels_api_key}         # correct
# headers = {"Authorization": f"Bearer {pexels_api_key}"}  # WRONG
```

---

### Audio Duration Estimation Without mutagen

```python
try:
    from mutagen.mp3 import MP3
    audio_duration = MP3(audio_path).info.length
except Exception:
    word_count = len(script.get("script", "").split())
    audio_duration = max(15.0, word_count / 2.5)  # ~2.5 words/sec
target_duration_s = max(6.0, audio_duration - 6.0)  # subtract hook + CTA
```

## Why This Works

The root cause was a **single-strategy b-roll pipeline** with no relationship between content type and visual treatment. Adding an LLM classifier at the cheapest possible point (Haiku, constrained to valid enums, ~$0.00025/call) routes each topic to the generator that best fits it — live articles get scroll animations, stats stories get data cards, code releases get walkthroughs — and only escalates to GPU when all CPU options fail.

The Phase 2 gate makes GPU a conditional branch instead of a required step. The two-generator fallback chain (primary → fallback → GPU) provides resilience: each generator raises `BrollError` on failure, the factory catches it and tries next, and the pipeline continues regardless.

## Prevention

**LLM-based selectors**
- Always wrap in `try/except` with a hardcoded safe default — selector failure must never propagate to the pipeline
- Use `output_config.format` with `json_schema` and `additionalProperties: False` for enum type selection — eliminates an entire class of parsing bugs vs. free-text parsing
- Use Haiku for classification, Sonnet/Opus only for content generation

**FFmpeg**
- Ken Burns: always include `setpts=PTS-STARTPTS` immediately after `zoompan` — black frames at xfade transitions are the symptom when this is missing
- Concat demuxer: always repeat the last frame with `duration 0.001` to prevent the final frame from being dropped
- Browser scroll: always `scale=w:-1` before `crop` — never assume screenshot dimensions

**Phase gate pattern**
- Check `needs_gpu_broll` across ALL jobs before starting any GPU infrastructure — start the pod at most once per pipeline run, only when at least one job requires it
- Add explicit boolean flags (`needs_gpu_broll`) rather than inferring GPU need from absence of `broll_path` — flags are self-documenting and safe to check multiple times

**External APIs**
- Pexels: no Bearer prefix — just the raw key in Authorization
- Playwright b-roll: always check word count after navigation — under 200 words reliably indicates a paywall or JS-rendered blank page

**Job schema design**
- Log `broll_type` on every job — knowing which generator wins most often informs future cost optimization
- Add the Phase 2 `broll_path` guard in every pipeline that has a CPU-then-GPU phase structure (the C4 pattern is general, not specific to b-roll)

## Related Issues

- Origin requirements: `docs/brainstorms/2026-03-29-rich-broll-engagement-requirements.md`
- Implementation plan: `docs/plans/2026-03-29-003-feat-rich-broll-engagement-system-plan.md`
- Implementation: `scripts/broll_gen/` package — `selector.py`, `browser_visit.py`, `image_montage.py`, `code_walkthrough.py`, `stats_card.py`, `ai_video.py`, `factory.py`
- Pipeline changes: `scripts/commoncreed_pipeline.py` — `_run_cpu_broll()`, Phase 2 gate, `VideoJob` extension
