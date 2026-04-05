---
title: Avatar lip sync desynchronized on all segments except hook
date: 2026-04-05
category: integration-issues
module: video_pipeline
problem_type: integration_issue
component: tooling
symptoms:
  - "Avatar lips lag behind audio by ~1-3 seconds on all body and CTA segments"
  - "Hook (first 3s) is perfectly synced while PiP #1, PiP #2, and CTA are late"
  - "Debug videos (avatar + matching audio) show perfect sync in isolation"
  - "VEED Fabric auto-trims CTA clips when trailing audio is silence"
root_cause: logic_error
resolution_type: code_fix
severity: critical
tags:
  - avatar
  - lip-sync
  - veed-fabric
  - moviepy
  - audio-duration
  - concatenation
  - mutagen
  - assembly
---

# Avatar lip sync desynchronized on all segments except hook

## Problem

In the assembled final video, all avatar segments except the hook (first 3s) had visibly delayed lip movements — the avatar's lips lagged behind the voiceover audio by 1-3 seconds. Debug videos pairing each VEED avatar clip with its corresponding audio segment showed perfect sync, confirming the issue was in the assembly pipeline, not VEED generation.

## Symptoms

- Hook avatar (0→3s): lips match audio perfectly
- PiP #1 circle (bottom-right, ~18→24s): lips ~1-2s behind audio
- PiP #2 circle (bottom-left, ~38→44s): lips ~2-3s behind audio
- CTA (last 3s): lips completely desynced or clip truncated to <1s
- Debug `*_avatar_with_original_audio.mp4` files: all perfectly synced

## What Didn't Work

1. **Concatenated single VEED call** — One continuous avatar clip from concatenated audio segments. VEED's lip-sync model needed ~1s warm-up after each audio jump between non-contiguous segments, causing cumulative drift.

2. **MP3 `-c copy` extraction** — Cutting MP3 segments with FFmpeg `-c copy` introduced ~26ms padding per segment due to MP3 frame boundaries. Cumulative across 4 segments = ~80ms drift. Fixed by extracting as WAV then re-encoding to MP3.

3. **Lead-in audio buffers** — Adding 1s of pre-audio before each segment for VEED warm-up. Increased cost without fixing the root cause.

4. **`concatenate_videoclips` assembly** — MoviePy's `concatenate_videoclips([hook, body, cta])` introduced timing drift at clip join boundaries. The hook was unaffected (first clip), but subsequent clips accumulated offset.

5. **Global `AVATAR_SYNC_OFFSET_S`** — A fixed offset applied to all segments. Wrong approach since only non-hook segments were affected, and the root cause was a duration mismatch, not a fixed delay.

## Solution

Three independent root causes were identified and fixed:

### Root Cause 1: Audio duration from wrong source (CRITICAL)

`mutagen` was not installed. The fallback estimated duration from word count:
```python
# BEFORE (broken):
try:
    from mutagen.mp3 import MP3
    audio_duration = MP3(audio_path).info.length
except Exception:
    audio_duration = max(15.0, len(script.get("script", "").split()) / 2.5)
```

For a 169-word script: `169 / 2.5 = 67.6s`. Actual audio: `64.37s`. The 3.2s error propagated to `_compute_avatar_windows()`, producing wrong extraction timestamps. The assembler used `AudioFileClip.duration` (correct), creating a mismatch in body layout timestamps.

```python
# AFTER (fixed):
from moviepy import AudioFileClip as _AFC
audio_duration = _AFC(audio_path).duration
```

### Root Cause 2: Single concatenated VEED call

Audio segments from non-contiguous timestamps were concatenated into one MP3 and sent as a single VEED call. The audio had hard jumps (e.g., second 3 → second 21) that confused VEED's lip-sync model.

**Fix**: 4 separate VEED API calls, one per segment, run in parallel via `asyncio.gather`. Each receives clean continuous audio. Same cost, same wall time (~50s parallel vs ~100s serial), perfect sync from frame 1.

### Root Cause 3: `concatenate_videoclips` timing drift

MoviePy's `concatenate_videoclips([hook, body, cta])` introduced timing drift at join boundaries between clips with different frame rates (hook=25fps from VEED, body=30fps from make_frame, CTA=25fps).

**Fix**: Single unified `VideoClip(final_make_frame, duration=total_duration)` that renders the entire video — hook, body PiPs, and CTA — in one `make_frame` function. No clip joins, no timing drift. All avatar frames pre-read into memory arrays at load time for seek-free rendering.

### Additional Fix: VEED CTA auto-trim

VEED auto-trims trailing silence, producing a 0.68s clip from a 4s audio segment. Fixed by extending the CTA audio window 2s backwards to capture actual speech before the silence.

## Why This Works

The sync chain requires that the SAME audio duration drives both avatar extraction (`_compute_avatar_windows`) and assembly layout (`_assemble_broll_body`). When these used different sources (word-count estimate vs AudioFileClip), the body layout timestamps (`t1, t2, t3, t4`) differed by up to 3.2s, causing every non-hook segment to read avatar frames at wrong positions.

The hook was unaffected because `audio[0→3]` is always the first 3 seconds regardless of total duration — `t1/t2/t3/t4` don't affect the hook's extraction or assembly.

## Prevention

1. **Never estimate audio duration from word count** — always read from the actual audio file using the same library the assembler uses:
   ```python
   from moviepy import AudioFileClip
   audio_duration = AudioFileClip(audio_path).duration
   ```

2. **Unit test sync alignment** — verify that `_compute_avatar_windows()` timestamps match the assembler's body layout at multiple sample durations:
   ```python
   for dur in [45.0, 55.0, 64.37, 72.75, 90.0]:
       windows = _compute_avatar_windows(dur)
       # Verify h1_start == hook_end + t1 - _BUFFER
   ```

3. **Separate VEED calls per segment** — never concatenate non-contiguous audio for a single lip-sync generation call. Each segment gets clean continuous audio.

4. **Avoid `concatenate_videoclips` when precise A/V sync matters** — use a single `VideoClip(make_frame)` with pre-read frames instead.

5. **Debug assets** — save `*_sent_to_veed.mp3` and `*_avatar_with_original_audio.mp4` files during VEED generation. These isolate whether sync issues are in VEED or assembly. (auto memory [claude])

## Related Issues

- `docs/solutions/workflow-issues/intelligent-broll-type-selection-gpu-phase-gating-2026-03-29.md` — avatar duration math (hook + CTA = 6s constant) referenced in b-roll pipeline
