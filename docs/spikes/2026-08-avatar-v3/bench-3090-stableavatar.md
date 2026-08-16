# Measured: StableAvatar 1.3B on the RTX 3090 — 5 s calibration run

**Date:** 2026-08-16 · **Purpose:** convert the survey's extrapolated 4090/5070 Ti/H100 numbers into
real 3090 numbers, per `shortlist.md` #3.

**This is the first measured datapoint in the entire spike.** Everything in `landscape.md` was
extrapolated. Three of its assumptions did not survive.

---

## Result

| | |
|---|---|
| Output | **125 frames, 480×832, 25 fps, 5.000 s** — verified with ffprobe |
| Wall clock | **1559 s = 25 min 59 s** |
| **Compute per second of video** | **311.8 s/s** |
| Peak VRAM | **14,380 MiB = 14.0 GB** |
| Config | `model_cpu_offload`, `sample_steps=50`, `clip_sample_n_frames=81`, `overlap_window_length=5`, `motion_frame=25`, seed 42 |
| Per-step | 29.4 s/it × 50 steps |
| Inputs | `owner-portrait-9x16.jpg` → 480×832 · Chatterbox clone of `vishalan_voice_ref.wav`, `exaggeration=0.5` |

**Against the ≤ 8 h / 60 s budget (= ≤ 480 s/s): PASSES at 65 % of budget.**
Linear extrapolation to 60 s: **1559 × 12 ≈ 5.2 hours.**

⚠️ That extrapolation assumes linear scaling across sliding windows. 60 s is ~19 windows versus
this run's ~2. Window-chaining overhead and any drift-correction cost are **not** in this number.

---

## Correction 1 — the vendor's 18 GB / `model_full_load` config does not run on a 3090

The README (line 427) claims: *"For the 5s video (480x832, fps=25), the basic model
(`--GPU_memory_mode="model_full_load"`) requires approximately 18GB VRAM and finishes in 3 minutes
on a 4090 GPU."*

**On a 3090 with the full 24,111 MiB free, `model_full_load` OOMs before a single diffusion step.**

```
torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 884.00 MiB.
GPU 0 has a total capacity of 23.55 GiB of which 119.88 MiB is free.
... this process has 23.42 GiB memory in use.
  → wan/models/wan_vae.py:37 in forward, x = F.pad(x, padding)
  → via prepare_mask_latents → self.vae.encode(mask_pixel_values_bs)
```

It died in **VAE encode during input preparation**, not in the diffusion loop. `model_full_load`
holds the umt5-xxl text encoder (~11 GB), CLIP (4.44 GB), the VAE and the transformer (3.26 GB)
all resident simultaneously. The claimed 18 GB is not reproducible here.

`model_cpu_offload` works and peaks at **14.0 GB** — comfortably inside the repo's ≤22 GB guard,
with ~9.5 GB of headroom.

**Consequence:** the vendor's 3-minute figure is not comparable to ours, because the config that
produced it cannot run on this hardware.

## Correction 2 — the 3090 conversion factor is far worse than the survey assumed

`landscape.md` uses **"3090 ≈ 2–2.5× slower than a 4090 on bf16"** and flags it as a rule of
thumb, not a sourced constant. Measured:

| | Config | 5 s @ 480×832 |
|---|---|---|
| Vendor, RTX 4090 | `model_full_load` | 3 min |
| **Measured, RTX 3090** | `model_cpu_offload` | **26 min** |
| **Ratio** | | **8.7×** |

The 8.7× is **not** pure Ampere-vs-Ada — it bundles the PCIe offload penalty, which is forced
because full-load OOMs. The two effects cannot be separated without a 4090 to test on.

**But for planning purposes the practical factor on this box is what matters, and it is ~8.7×,
not 2–2.5×.** Every extrapolated estimate in `landscape.md` should be treated as optimistic by
roughly 3–4× until individually measured.

**Immediate consequence for the shortlist:** LongCat-Video-Avatar-1.5 was estimated at 2–3.5 h for
60 s at 480p, derived from a 4090 at 14–15 s/step with a 2–2.5× factor. Re-derived at the measured
factor, the same arithmetic gives **8–12 h — outside the 8 h budget.** LongCat's saving grace is
that it is 8-NFE distilled versus this run's 50 steps, so it may still land inside; **but it can
no longer be assumed to.** Measure before relying on it.

## Correction 3 — VRAM contention is real, and `README.md` said otherwise

The spike README recorded: *"VRAM contention is a non-issue. Ollama (9 MiB) and Chatterbox (12
MiB) both lazy-load. The full ~23.5 GB is available to an avatar candidate in practice."*

**That was measured at cold idle and it is wrong in operation.** The first render attempt OOM'd
with this in the log:

```
Process 34445 has 3.55 GiB memory in use.
```

PID 34445 = `python -u server.py` inside **`commoncreed_chatterbox`**. Confirmed with
`nvidia-smi --query-compute-apps` + cgroup lookup: **3,640 MiB held resident after serving a single
TTS request, and never released.**

In the real pipeline TTS runs immediately *before* avatar generation, so **the avatar stage will
always face a warm Chatterbox.** The effective VRAM ceiling is therefore **~19.9 GB, not 23.5 GB.**

This is the deadlock risk the feasibility review flagged and that I recorded as "much reduced."
It is not reduced. It is live, and it changes shortlist viability:

| Candidate | Need | Fits beside warm Chatterbox (19.9 GB)? |
|---|---|---|
| StableAvatar `model_cpu_offload` | 14.0 GB **(measured)** | **Yes** |
| LongCat Q6_K | 15.5 GB | Yes |
| LongCat Q8_0 | 19.1 GB | **Marginal** |
| LatentSync 1.6 (grows to 23 GB, issue #326) | 18→23 GB | **No** |
| StableAvatar `model_full_load` | >23.4 GB | **No — OOMs even with a clean GPU** |

**Unit 2's GPU-safe runner now has a concrete, mandatory job:** evict or stop the Chatterbox
container before the avatar stage, and verify free VRAM as a precondition. `docker stop
commoncreed_chatterbox` returned the GPU to 9 MiB used / 24,111 MiB free.

---

## Quality — first look

Sampled frames 0 / 31 / 62 / 93 / 124 (`contact_sheet.png`).

**Holds up better than expected:**
- **Identity is stable across all 125 frames** — no visible drift in face shape or skin tone.
- **Glasses survive intact** — frame geometry consistent, no warping. This is a common failure mode.
- **Clasped hands survive**, which is the genuine surprise. Hands are where image-driven models
  usually disintegrate; there is finger-position variation but no melting, no extra digits.
- Earbuds, moustache, t-shirt and the background (sage wall, framed art, monitor with orange
  wallpaper) all remain coherent.
- Mouth shapes vary plausibly with speech rather than flapping generically.

**Weaknesses visible at this sample density:**
- Mild framing/scale wobble between frames — the subject drifts slightly in apparent distance.
- Some face-width variation frame to frame (mild identity wobble, well short of a break).
- Skin texture is smoothed relative to the reference.

**Not yet assessed:** lip-sync accuracy against the audio (needs playback, not stills), and
temporal judder. Both are Unit 1 rubric items.

---

## Method notes

- Driving audio generated by the **local Chatterbox clone**, not a stock voice — so this is an
  end-to-end test of the actual intended stack.
- Audio padded to exactly 5.000 s to match the vendor's benchmark case.
- Reference frame derived from `owner-portrait-9x16.jpg` (765×1360, true 9:16) scaled to 480×832.
- VRAM sampled once per second for the whole run via `nvidia-smi -l 1`; peak is the max sample.
- Server is on **WiFi** (`enp34s0` idle, `wlo1` carrying all traffic). The 27 GB weights download
  took ~23 min. Irrelevant to render timing, but relevant to any future model-pull planning.

## Incidental finding — `duration_ms` in the Chatterbox API is mislabeled

`deploy/chatterbox/server.py:192-204` computes `dur_ms = (time.time() - t0) * 1000` — **generation
wall-clock** — and returns it as `duration_ms`, alongside `sample_rate`. The pairing strongly
implies audio length. Observed: API reported `10434 ms` for a file that is **4.24 s** long.

The internal log line names it correctly (`gen_ms=%.0f`), and the sole consumer
(`scripts/voiceover/chatterbox_generator.py:323`) logs it as "gen" time — **so this is not a live
bug**, only a naming hazard. Worth renaming to `generation_ms` before anything else consumes it,
since a caller that trusts the field name would mis-time every video built against it.
