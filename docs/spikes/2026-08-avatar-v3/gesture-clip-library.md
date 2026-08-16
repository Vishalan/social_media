# Gesture clip library + voice reference v2

**Date:** 2026-08-16 · **Source:** `assets/input_media/IMG_1774_3.mp4` (1920×1080, 30 fps, 138.03 s)

Both assets derive from the *same* recording, so face and voice are matched by construction.

---

## 1. Gesture clip library

**Location (server):** `/opt/commoncreed/assets/gesture_clips/` · manifest at `manifest.json`
**Format:** 480×854, 25 fps, H.264, **no audio** — exactly what LatentSync consumes, no conversion needed.

### How the windows were found

Sampled every 0.25 s (553 samples) and ran InsightFace `buffalo_l` detection, keeping only samples
that are **face-present, near-frontal (|yaw| < 20°, |pitch| < 25°), close-framed (face width > 200 px)
and confident (score > 0.6)** — the conditions LatentSync actually requires.

| Raw run | Verdict |
|---|---|
| t = 0.00–14.00 | **keep** — frontal, stable, |yaw|max 4.7° |
| t = 51.00–63.75 | **reject** — face width 119–162 px, |yaw|max 84° (profile / away shots) |
| t = 72.00–105.50 | **keep 72.00–102.25** — tail drifts off-axis |
| t = 120.25–136.75 | **keep** — frontal, |yaw|max 10.3° |

**Usable total: 61.25 s across 3 windows** → cut into **12 clips / 59.25 s**.

That is enough for exactly one 60 s short with no reuse. Anything beyond one short per capture
session needs more footage — which is the concrete answer to the plan's open question about how
much base footage family 3 requires.

### Clips, tagged by motion

Motion = mean absolute frame difference on the lower 45 % of frame (hands/torso), so the tag
tracks *gesture* activity, not head movement.

| Clip | Window | Source | Dur | Motion | Tag |
|---|---|---|---|---|---|
| clip_01 | 1 | 0.00–5.00 | 5.00 | 1.949 | moderate |
| clip_02 | 1 | 5.00–10.00 | 5.00 | 0.722 | **calm** |
| clip_03 | 1 | 10.00–14.25 | 4.25 | 1.196 | **calm** |
| clip_04 | 2 | 72.00–77.00 | 5.00 | 3.532 | animated |
| clip_05 | 2 | 77.00–82.00 | 5.00 | 3.517 | animated |
| clip_06 | 2 | 82.00–87.00 | 5.00 | 3.996 | animated |
| clip_07 | 2 | 87.00–92.00 | 5.00 | **5.056** | animated |
| clip_08 | 2 | 92.00–97.00 | 5.00 | 2.911 | moderate |
| clip_09 | 2 | 97.00–102.00 | 5.00 | 3.535 | animated |
| clip_10 | 3 | 120.25–125.25 | 5.00 | 3.075 | animated |
| clip_11 | 3 | 125.25–130.25 | 5.00 | 4.647 | animated |
| clip_12 | 3 | 130.25–135.25 | 5.00 | 2.072 | moderate |

**Distribution: 2 calm · 3 moderate · 7 animated.** Thin on calm — worth noting for the capture
session, since a hook usually wants energy but a stat-card beat usually wants stillness.

### How to use

Pick a clip whose motion tag matches the beat, then:

```bash
python -m scripts.inference \
  --unet_config_path configs/unet/stage2_512.yaml \
  --inference_ckpt_path checkpoints/latentsync_unet.pt \
  --inference_steps 20 --guidance_scale 1.5 --enable_deepcache \
  --video_path /opt/commoncreed/assets/gesture_clips/clip_07.mp4 \
  --audio_path <16kHz mono wav> \
  --video_out_path out.mp4
```

⚠️ **Audio must be 16 kHz mono** (`stage2_512.yaml:16 → audio_sample_rate: 16000`), and the clip's
duration should match the audio; LatentSync pairs them frame-for-frame.

⚠️ **Observed: 125 frames in → 127 frames out** (5.000 s → 5.080 s). Harmless once, but it
compounds across a multi-segment assembly. Pin this down before Unit 6 — it is the same class of
defect as the April `avatar-lip-sync-desync-across-segments` learning.

---

## 2. Voice reference v2 — cloned from the same recording

**Output:** `/opt/commoncreed/assets/vishalan_voice_ref_v2.wav` · also in `output/avatar-spike/`

### Pipeline

1. **Extract** audio from `IMG_1774_3.mp4` → 48 kHz mono WAV. Integrated loudness **−21.1 LUFS**.
   No silence detected at −35 dB → continuous background present, so isolation was necessary.
2. **Isolate vocals** with `Kim_Vocal_2.onnx` via StableAvatar's own `vocal_seperator.py`
   (the checkpoint ships with StableAvatar — no extra download). Separation took 2 min 01 s.
   Result: noise floor **−71.3 dB**, speech peak **−16.4 dB**, voiced fraction **81.7 %**.
3. **Select the best passage.** Scored every candidate 10 s window on speech density, level
   consistency and longest internal gap. Winner: **t = 19.40** (density 0.92, max gap 0.5 s).
4. **Cut a continuous 30 s from t = 19.40** — continuous rather than spliced, so there are no
   join artifacts, *and* the best-delivered passage lands at the head.
5. **Resample to 24 kHz mono** — matches `S3GEN_SR = 24000`, so no resampling penalty on the
   decoder path.
6. **Two-pass `loudnorm` to −27 LUFS with `linear=true`** (static gain, not time-varying).
   Measured −20.89 → achieved **−26.8 LUFS**.

### Why the head placement matters

From `tts-deep-findings.md` §3, verified in Chatterbox source:

```python
ENC_COND_LEN = 6  * S3_SR      # first  6 s → T3 speech-conditioning
DEC_COND_LEN = 10 * S3GEN_SR   # first 10 s → s3gen decoder reference
```

**Only the first 10 s drives prosody and timbre.** The remaining 20 s feeds nothing but the
speaker embedding. Putting the best-scoring passage at t=0 of the reference is therefore a free
quality win, and it is invisible in the documentation.

### Why normalize at all

The original `ChatterboxTTS` we run **does not loudness-normalize the reference** (Turbo/Nano do,
to −27 LUFS; ours does not). So the absolute level of an isolated clip is an uncontrolled variable
across runs. Normalizing ourselves to the same −27 LUFS the codebase uses elsewhere makes runs
reproducible. Old reference sat at −24.4 LUFS, so this also changes conditioning slightly.

### A/B

Same sentence, `exaggeration=0.5`, both references:

| Reference | Output length | Generation time |
|---|---|---|
| `vishalan_voice_ref.wav` (old) | 4.40 s | 3012 ms |
| **`vishalan_voice_ref_v2.wav` (new)** | 4.68 s | 2625 ms |

Files: `output/avatar-spike/ab_old.wav`, `ab_new.wav`, `ab_compare.wav` (old → 0.6 s gap → new).

**Not yet decided — this needs a listening judgment from the owner.** The new reference is
better-controlled on every measurable axis (isolated, level-normalized, best passage at head,
matched to the on-camera face). Whether it *sounds* better is the call that matters, and it is
not one the measurements can make.

---

## Note on the old reference

`vishalan_voice_ref.wav` (30 s, 24 kHz, −24.4 LUFS) is **not** replaced or deleted — v2 sits
alongside it. Keep both until the listening test settles it.
