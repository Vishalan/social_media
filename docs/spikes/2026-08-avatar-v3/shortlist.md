# Unit 3 — Avatar Candidate Shortlist

**Date:** 2026-08-16 · Derived from `landscape.md` · **This is what Unit 4's capture session must serve.**

Four candidates, ordered by expected value, covering all three families as R1 requires.
Plus one time-boxed side bet outside the shortlist.

---

## 1. LatentSync 1.6 — lip-sync over real footage · **PRIMARY**

**Family 3 — the family the April project never tried.**

| | |
|---|---|
| Licence | Apache 2.0 (code) / OpenRAIL++ (weights) — **both commercial-clear** |
| VRAM | 18 GB; wrapper states "RTX 3090 compatible" |
| Est. 60 s on 3090 | **~1–2 h** — inside budget with 4–8× margin |
| Face resolution | 512×512 |
| Evidence | **The only candidate with third-party measured timings** (issue #365) |

**Why primary:** identity preservation is **perfect by construction** — the face is real, so it
cannot drift because it was never generated. Against a rubric scoring "uncanny-valley
believability" and "identity likeness" separately, this starts at ceiling on both. It is also
the plan's mandated **mature/stable baseline**: frozen since June 2025 with 6k stars and known,
documented failure modes. For a workload whose entire risk is *consistency across 60 seconds*,
that maturity is evidence, not staleness.

**Known risks to measure in Unit 2:**
- VRAM grows 17 → 20 → **23 GB** during the loop (issue #326) — **breaches the ≤22 GB guard.**
  This single measurement could disqualify the primary candidate. Take it early and cheaply.
- Chunk seams at transitions — echoes `avatar-lip-sync-desync-across-segments-2026-04-05`.
  **Score post-assembly, never on isolated clips.**

**The decisive product question:** it only moves the mouth. Head motion, gestures and framing all
come from base footage — so a 60 s short needs ~60 s of usable footage, and looping reads as
looped. **This bounds how many shorts one capture session can serve.**

---

## 2. LongCat-Video-Avatar-1.5 — image-driven · **GENERATIVE CANDIDATE**

| | |
|---|---|
| Licence | **MIT** — cleanest in the survey |
| VRAM | Q6_K 15.5 GB / Q8_0 19.1 GB |
| Est. 60 s on 3090 | **~2–3.5 h @ 480×832**; **5–9 h @ 768×1280 ⚠️** |
| Steps | DMD2-distilled, fixed **8 NFE** |
| ComfyUI | node validated **2026-08-09** on Core 0.31.0 |

**Ship at 480×832 plus a separate upscale pass.** 768×1280 is the config that risks the 8 h wall.

A full year newer than anything evaluated in April. Whisper-Large drives lip dynamics
(vendor claim). Supports SageAttention (Ampere-compatible).

**Integration traps:** the ComfyUI node **does not support GGUF** — bf16 or INT8 only; the
popular GGUF quants target a *different* path (kijai's WanVideoWrapper). Aspect is 0.577, not
true 9:16 (0.5625) — minor crop/pad.

---

## 3. StableAvatar — image-driven · **CALIBRATOR — RUN THIS FIRST**

| | |
|---|---|
| Licence | **MIT** |
| VRAM | **18 GB bf16, no quantisation needed** |
| Est. 60 s on 3090 | ~1.2–1.5 h |
| Benchmark | "5 s @ 480×832 @ 25 fps in 3 min on a 4090" |

**Its job is not to win — its job is to calibrate.** It is the only model in the field with a
clean, concrete consumer-GPU benchmark. Reproducing that one documented case on the 3090 yields
the **true Ampere-vs-Ada conversion factor**, which then applies to every other estimate in
`landscape.md`. Cheapest possible way to replace the shakiest assumption in the whole survey.

Ten months stale, architecturally a generation behind. Run it anyway, and run it first.

---

## 4. Wan2.2-S2V-14B (distilled only) — video/identity-driven · **DOCUMENTED FALLBACK**

| | |
|---|---|
| Licence | **Apache 2.0** (conduct clause, no commercial restriction) |
| Est. 60 s on 3090 | **~1.5–2.5 h with 4-step Lightning LoRA** · **13–19 h undistilled ❌** |
| Output | 16 fps native in ComfyUI (HF card says 24 — **unresolved conflict**) |

Included to close out the April plan and to represent family 2. **Only with the 4-step
Lightning/lightx2v LoRA.** 16 fps needs RIFE interpolation to reach 30 — an extra stage and an
extra failure mode.

⚠️ **Never benchmark the undistilled path and conclude the family is unviable.** Step count, not
model choice, decides the budget.

---

## Side bet (outside the shortlist) — LeapTalk / SoulX-FlashHead-1.3B

Apache 2.0, 2026-07-29, claims **1-NFE** inference and "up to 200 FPS in the Lite setting" —
with the GPU unnamed, no VRAM published, and no ComfyUI node.

**Time-box one afternoon.** Highest information-value-per-hour available; lowest evidence
quality in the survey. If even a third of the claim survives contact with a 3090, the economics
change completely.

---

## Demoted: EchoMimic V3 (the April incumbent)

Keep only as a **cheap, fast control** — not a contender.

1. Frozen since **2026-01-22** while LongCat shipped 1.5.
2. Documented envelope is **768×768 square** — 9:16 means off-spec use or crop-and-pad.
3. **Hard 138-frame ceiling** (5.5 s) → ~11 chained windows for 60 s, exactly where drift bites.
4. **No published wall-clock anywhere**, and it has **never been quality-validated on this
   hardware** (`echomimic-v3-validation.md` still `status: pending`; the April plan benchmarked
   a *hosted API*, not a local run).

**It carries no incumbency credit.**

---

## What this shortlist demands of the Unit 4 capture session

The single biggest consequence: **the primary candidate needs real footage, not just a portrait.**

| Requirement | Driven by | Spec |
|---|---|---|
| **Base video footage** | LatentSync (#1) | **25 FPS**, frontal, face visible throughout, no large head rotation. Enough usable takes that 60 s of short does not require visible looping. |
| **Still reference portrait** | LongCat (#2), StableAvatar (#3) | Portrait framing suitable for 480×832 |
| **Real-footage control take** | Plan's own control | Already in the plan — now doubles as LatentSync's input |
| **Voice reference clip** | Chatterbox | **Best-delivered passage at the HEAD of the file** — only the first 10 s drive prosody and timbre (`tts-deep-findings.md` §3) |

**Test one-shot identity before considering any LoRA training.** LongCat, StableAvatar,
MagiHuman and Stand-In all take identity from a single reference image. If one-shot holds for
this face, LoRA is a cost never paid — and LoRA is the one path where the 3090's 24 GB actually
hurts (musubi-tuner's documented floor is "24 GB or more", i.e. exactly on the line).

---

## Cadence consequence for Unit 8

At 2–3 h per short, the 3090 produces **one short per half-day**. Unit 8 must report
**shorts-per-week**, not just per-short render time — the cost win over VEED ($4.80–9.00/short →
$0.10–0.30 of electricity, 20–50×) is real, but throughput, not dollars, is the binding
constraint on posting cadence.
