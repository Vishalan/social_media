# Unit 3 — Local Talking-Avatar Model Landscape (R1, R6, R7)

**Date:** 2026-08-16 · **Target GPU:** RTX 3090, 23.5 GB usable · **Budget:** ≤ 8 h per finished 60 s short

---

## ⚠️ Evidence-quality warning — read before quoting any number here

The research session's WebSearch budget was exhausted (200/200) early. Everything below comes
from **direct WebFetch against primary sources**: GitHub READMEs, release/commit pages, issue
threads, HuggingFace model cards and the HF API. Reddit is unfetchable in this environment, so
community anecdote is thin — and none has been invented to fill the gap.

**Almost every wall-clock figure in this document is extrapolated, not measured on a 3090.**
Exactly three real datapoints exist in the whole survey.

| Evidence tier | What actually exists |
|---|---|
| **Measured, third-party** | LatentSync on RTX 5070 Ti (issue #365); InfiniteTalk on 3090 (issues #64, #197) |
| **Vendor, unusually specific** | StableAvatar "5 s @ 480×832 in 3 min on a 4090, 18 GB" |
| **Vendor marketing** | Every "temporal stability" / "identity consistency" / FPS claim |
| **Arithmetic** | All 3090 conversions, using 3090 ≈ 2–2.5× slower than 4090 on bf16 — **a rule of thumb, not a sourced constant** |

### Ampere caveat that invalidates most quoted benchmarks

The 3090 has **no FP8 tensor path**. FP8 checkpoints save VRAM but dequantise to bf16 with
**no speedup**. Any "fp8" timing quoted on Ada / Hopper / Blackwell does not transfer.

SageAttention 2.2.0 (2025-07-01) *does* support Ampere at a claimed 2–5× over FlashAttention.
**SageAttention 3 is Blackwell-only** — the 3090 is permanently capped at the 2.x line.

---

## The bar, restated as arithmetic

**VEED Fabric 1.0 on fal.ai, verified still current 2026-08-16:** $0.08/sec at 480p,
**$0.15/sec at 720p** → **$4.80–$9.00 per 60 s short**. (`veed_client.py:17` already records
both tiers; the plan's "$9/short" framing is the 720p case.)

**Render budget** ≤ 8 h per 60 s short = **≤ 480 s of compute per second of finished video**,
or ≤ 19.2 s per frame at 25 fps. Applied as an explicit filter to every candidate below.

**Electricity:** a 3090 at ~350 W for 2–3 h ≈ **$0.10–0.30** — a 20–50× marginal-cost win.

**But dollars are not the binding constraint.** At 2–3 h/short you get **one short per half-day
per GPU**. Unit 8 must report **shorts-per-week**, not just per-short time — this bears directly
on the plan's open question about sustainable cadence.

---

## What changed since the April 2026 survey

**1. The Wan2.2-S2V blocker was a discovery failure, not a missing artifact.**
`Wan2_2-S2V-14B_fp8_e4m3fn_scaled_KJ.safetensors` (16,653,330,620 bytes) exists at
[`Kijai/WanVideo_comfy_fp8_scaled/tree/main/S2V`](https://huggingface.co/api/models/Kijai/WanVideo_comfy_fp8_scaled/tree/main/S2V).
Kijai **split the fp8 models into a second repo**; the main `WanVideo_comfy` repo genuinely does
not contain it. HF dates the upload ~Aug/Sep 2025 — **it was already there in April 2026.**
Two further unblocking paths now exist: the
[official ComfyUI native S2V tutorial](https://docs.comfy.org/tutorials/video/wan/wan2-2-s2v)
with a "Video S2V Extend" chaining subgraph, and
[QuantStack GGUF quants](https://huggingface.co/QuantStack/Wan2.2-S2V-14B-GGUF) (Q2_K 9.51 GB →
Q8_0 19.6 GB).
→ **`docs/plans/2026-04-15-001-feat-wan22-avatar-provider-plan.md` `status: blocked-upstream`
should be closed.** The unblock condition ("kijai uploads the scaled safetensors") was already
satisfied when it was written.

**2. A materially better model shipped in May.** **LongCat-Video-Avatar-1.5** (Meituan) —
verified via HF API: created **2026-05-21**, lastModified 2026-06-04, **MIT**, 714 likes. It is
the successor lineage to MultiTalk/InfiniteTalk (MeiGen *is* Meituan — one team, not a fork);
both older READMEs now lead with LongCat news.

**3. The incumbent went quiet.** EchoMimic V3's last update is EchoMimicV3-Flash-Pro,
**2026-01-22** — seven months of silence. Its issue tracker contains **no timing data at all**.

**4. Most of the April list is now dead.** Hallo3 (2025-02-27), Sonic (2025-05-06), FLOAT
(2025-06-26), FantasyTalking (2025-07-07), HunyuanVideo-Avatar (2025-06-06) — no meaningful
release in 12–18 months. Dating them as stale is a **finding**, not an absence of research.

**5. A one-step/streaming family appeared** — SoulX-FlashHead/FlashTalk (Feb–Apr 2026) and
**LeapTalk (2026-07-29, Apache-2.0)**, claiming 1-NFE inference. High upside, near-zero evidence.

---

## Family 1 — Image-driven (still portrait + audio)

| Model | Date | Licence | VRAM | 60 s on 3090 | 9:16 | Verdict |
|---|---|---|---|---|---|---|
| **LongCat-Video-Avatar-1.5** | 2026-05-21 | **MIT** | Q6_K 15.5 / Q8_0 19.1 GB | **~2–3.5 h** (est) @480p | ~native 480×832 | **Shortlist** |
| **StableAvatar** | 2025-08-11, stale 2025-10-12 | **MIT** | **18 GB bf16, no quant** | **~1.2–1.5 h** (from vendor 4090) | native 480×832 | **Shortlist (calibrator)** |
| EchoMimic V3 | stale 2026-01-22 | Apache 2.0 | 12 GB | fast, but unmeasured | **768² square only** | **Demote** |
| InfiniteTalk / MultiTalk | 2025-08-19 | Apache 2.0 | offload flag | **3 h+ for 40 s undistilled** | arbitrary | Superseded |
| LeapTalk / SoulX-FlashHead | **2026-07-29** | Apache 2.0 | **unpublished** | claims ~40 s (!) | unspecified | Side bet |

### LongCat-Video-Avatar-1.5 — the generative candidate

13.6B DiT, **DMD2-distilled to a fixed 8 NFE**, Whisper-Large replacing Wav2Vec2 for lip
dynamics (vendor claim). ComfyUI support via
[rookiestar28/ComfyUI-LongCat-Avatar](https://github.com/rookiestar28/ComfyUI-LongCat-Avatar) —
MIT, **last validated 2026-08-09 on ComfyUI Core 0.31.0** (nine days before this survey).
Supports SDPA / FA2 / FA3 / xFormers / **SageAttention** (Ampere-compatible).

**Two integration traps, both verified:**
- The node **explicitly does not support GGUF** — only bf16, official INT8 sharded, and
  single-file INT8. The popular GGUF quants target kijai's WanVideoWrapper, a *different* path.
- `sageattn_3` fails fast (LongCat's varlen cross-attention wiring is incomplete). Irrelevant on
  Ampere, which cannot run SA3 anyway.

**Aspect-ratio correction.** LongCat's model card does **not** state 9:16. The ComfyUI node
documents 480×832 and 768×1280. Both are portrait, but 480×832 = 0.577 and 768×1280 = 0.600
versus true 9:16 = **0.5625** — near-vertical, not exact. Minor crop/pad required. Treat
"native 9:16" as *approximately* true.

**Speed evidence is weak, and the reason matters.** The only figure is
[PR #115](https://github.com/meituan-longcat/LongCat-Video/pull/115) (2026-05-25, **unmerged**):
third-party H100 at ~7.8 s/step, PR author's **RTX 4090 at 14–15 s/step**. The PR's original
"29 min → 14 s/step" headline was **retracted by its own author** — the 29 min was PCIe
sysmem-fallback thrash under VRAM pressure, not compute. Exactly the kind of number that gets
miscited downstream.

At 8 steps × ~19 windows for 60 s: 4090 ≈ 1–1.5 h; 3090 at 2–2.5× ≈ **2–3.5 h at 480p**, and
**5–9 h at 720p**. → **480p plus a separate upscale pass is the shipping config**, not 768×1280.

### StableAvatar — the calibration baseline

It earns its place for an unglamorous reason: it is the **only model in the entire survey with a
clean, concrete consumer-GPU benchmark** — "5-second 480×832 at 25 fps finishes in 3 minutes on
a 4090", 18 GB. That fits 23.5 GB at bf16 with **no quantisation gymnastics at all**, implying
~1.2–1.5 h for 60 s on a 3090. MIT, natively portrait, ComfyUI-integrated since 2025-08-15.

Ten months stale and architecturally a generation behind — **but running it first yields the
true Ampere-vs-Ada conversion factor to apply to every other estimate in this document.**
One measurement de-risks the whole table.

### EchoMimic V3 — re-judged on current evidence (R7)

Apache 2.0, 12 GB, 8-step, genuinely cheap to run. **Three things demote it:**
1. **Frozen since 2026-01-22** while LongCat shipped 1.5.
2. Documented envelope is **768×768 square** — a 9:16 short means off-spec use or crop-and-pad.
3. **Hard 138-frame ceiling** (5.5 s @ 25 fps) → 60 s needs ~11 chained windows, precisely where
   colour and identity drift bite.

It has **no published wall-clock anywhere**, and `docs/spikes/echomimic-v3-validation.md` is
still `status: pending` — meaning **the incumbent has never been quality-validated on this
hardware.** The April EchoMimic plan was a *hosted-API* benchmark, not a local one.
**It carries no incumbency credit.** Keep only as a cheap, fast control.

### LeapTalk / SoulX-FlashHead — the side bet

[repo](https://github.com/zhangrongxiang/LeapTalk), 2026-07-29, Apache-2.0,
[arXiv:2608.00079](https://arxiv.org/abs/2608.00079). Claims 1-NFE inference and "up to 200 FPS
in the Lite setting" — **with the GPU unnamed in both repo and abstract**, no VRAM published,
no ComfyUI node. If even a third survives contact with a 3090 the economics change completely.
**Highest information-value-per-hour available; lowest evidence quality in this survey.**
Time-boxed afternoon side bet, *not* a shortlist candidate.

---

## Family 2 — Video / identity-driven

**Recommendation: not worth pursuing for this use case.** The reasoning is recorded so it is
not re-litigated.

**Wan2.2-S2V-14B** (2025-08-26, **Apache 2.0** — confirmed, with a conduct clause but no
commercial restriction; materially more permissive than the Wan2.1-era licence people remember)
is now genuinely unblocked. But:

- **Step count, not model choice, decides the budget.** At stock 20–40 steps, a 14B undistilled
  model on a 3090 extrapolates to **13–19 h for 60 s — FAILS.** With the 4-step
  Lightning/lightx2v LoRA it drops to ~1.5–2.5 h and passes.
  ⚠️ **Never benchmark the undistilled path and conclude the family is unviable.**
- **The ComfyUI native path runs at 16 fps**, 77 frames per pass = 4.8125 s per chunk (~13
  extensions for 60 s). The HF card says 24 fps — **an unresolved spec conflict**. 16 fps is
  choppy for social video and needs RIFE interpolation to reach 30 fps: another stage, another
  failure mode.
- Superseded by LongCat-1.5, which ships distillation natively.

### Identity-LoRA training is the part that genuinely doesn't fit

[musubi-tuner](https://github.com/kohya-ss/musubi-tuner) (actively maintained, changelog
2026-07-14) supports Wan2.1/2.2 and HunyuanVideo LoRA and states plainly:
**"24 GB or more for video training."** A 3090 sits **exactly on that floor** — reduced
resolution and memory-saving flags, with **no published training-hour figures**.

**The strategic point that resolves this family:** LongCat-1.5, StableAvatar, MagiHuman and
Stand-In all do identity from a **single reference image**. If one-shot identity holds for this
specific face, **LoRA training is a cost never paid** — and it is the one path where the 3090's
24 GB actually hurts. **Test one-shot first; reach for LoRA only if it fails.**

Keep Wan2.2-S2V as a **documented fallback in distilled configuration only**.

---

## Family 3 — Lip-sync over real footage ← the family the prior project never tried

**This is where the evidence is strongest, and probably where the answer is.**

### LatentSync 1.6 — the mature baseline, and the only candidate with measured timings

| | |
|---|---|
| Version | **1.6, 2025-06-11**; last commit **2025-06-20** — 14 months frozen |
| Licence | **Apache 2.0** (code, GitHub) / **OpenRAIL++** (weights, HF card) — both permit commercial use; the split is worth noting precisely |
| VRAM | 18 GB (v1.6). ComfyUI wrapper states **"optimized to run on 20GB VRAM (RTX 3090 compatible)"** |
| Resolution | **512×512 face region** — 2× MuseTalk's 256², and the reason v1.6 fixed v1.5's blurry teeth |
| ComfyUI | [ShmuelRonen/ComfyUI-LatentSyncWrapper](https://github.com/ShmuelRonen/ComfyUI-LatentSyncWrapper) |

**Measured speed** — [issue #365](https://github.com/bytedance/LatentSync/issues/365),
RTX 5070 Ti 16 GB, 512×512, 20 steps:

| Backend | 9.68 s clip | s per output-s | 30.08 s clip | s per output-s |
|---|---|---|---|---|
| PyTorch eager | 397.5 s | **41.1** | 1779.1 s | **59.1** |
| TensorRT-RTX | 268.2 s | **27.7** | 779.7 s | **25.9** |

TensorRT preserved quality (0.99999 cosine similarity, 0.98 SSIM). Scaling PyTorch eager to a
3090 (~1.5–2× slower) gives **roughly 1–2 h for 60 s — inside budget with 4–8× margin.**
DeepCache (April 2025) is a further lever.

**Why this family is structurally strong here:** the face is genuinely real, so **identity
preservation is perfect by construction — it cannot drift, because it was never generated.**
Against a rubric with "uncanny-valley believability" and "identity likeness" as separate
dimensions, this family **starts at ceiling on both.** It is also the highest realism per
GPU-hour available.

**The real limitations, stated plainly:**
- **[Issue #326] VRAM grows during the inference loop** — 17 GB → 20 GB → 23 GB, OOM at 3+
  minutes on a 4090. At 60 s probably fine, but **23 GB breaches the repo's own ≤22 GB
  peak-VRAM guard.** Measure early in Unit 2.
- **Chunk seams.** The same issue reports "noticeable seams at chunk transitions" when splitting
  video — a direct echo of the `avatar-lip-sync-desync-across-segments-2026-04-05` learning.
  **Measure sync post-assembly, per segment.**
- **Requires 25 FPS input, frontal faces, face visible throughout, no large head rotation.**
  This constrains the Unit 4 capture spec concretely.
- **It only moves the mouth.** Head motion, gestures and framing all come from recorded base
  footage. **This is the decisive open question for the family:** a 60 s short needs ~60 s of
  usable base footage, and reusing/looping takes is detectable. It trades generative freedom
  for realism.

### Others in this family

- **MuseTalk 1.5** (2025-03-28, **MIT**, commercial OK) — real-time, 30 fps+ on a V100, ~5 min
  for 8 s even on a 4 GB card. But face region is **256×256**, and the README itself concedes
  **identity preservation issues** (moustache, lip shape/colour) and **"some jitter"** from
  single-frame generation. Too low-fidelity to publish under one's own name. Useful as a fast
  draft/preview pass, or as the plan's deferred R7 refinement step.
- **VideoReTalking** (Apache 2.0, 7.3k stars) — mature but old (SIGGRAPH Asia 2022); documented
  failure on extreme poses. Fallback only.
- **Wav2Lip — EXCLUDED on licence.** "Personal/research/non-commercial purposes only… any form
  of commercial use is strictly prohibited." Mouth region **192×288**. The authors' commercial
  route is Sync Labs' hosted API — **there is no open commercial path here.** This also answers
  the sync.so question: no open weights.

---

## Open-source end-to-end shorts pipelines worth studying

- **[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo)** — **MIT, ~103.9k
  stars, active through 2026.** The most useful architectural reference: script → TTS
  (Edge/Azure/ElevenLabs) → footage match → **subtitles from either TTS timestamps or local
  Whisper** → audio mix → 9:16 output, exposed as AI Agent / WebUI / **REST API** / CLI. That
  subtitle fork is directly relevant to the R5 word-level-timing question and to whether output
  can feed `_build_ass_captions`.
- **YumCut** (848 stars, TypeScript, updated ~2026-08-14) — prompt → vertical video for
  TikTok/Reels/Shorts.
- **AI Faceless Video Generator** (482 stars) — script + voice + talking face, notebook-form.

---

## Exclusion list, with reasons

### Failing the 8 h / 60 s budget
- **Jogg-Avatar** — README: "~9 minutes for one second of output on two RTX 4090s". 9 min × 60 =
  **9 h on 2×4090 ≈ 40+ h on one 3090. Fails by ~5×.**
- **Wan2.2-S2V at 20–40 steps** — 13–19 h extrapolated. Fails **undistilled only**.
- **InfiniteTalk / MultiTalk undistilled** — real 3090 reports: [#64, 2025-08-31] 40 s video
  abandoned after **3 h incomplete on a 3090**; [#197, 2026-02-12] 1 h on **four** 3090s.
  The closest thing to Ampere ground truth in this survey, and it says undistilled 14B Wan does
  not fit the budget.

### Failing VRAM on a 3090
- **LTX-2.3-22B AV talking-head LoRA** — **77.08 GB peak**, trained on an RTX PRO 6000 96 GB.
  Also wrong licence. Excluded twice over.
- **LiveAvatar (Alibaba Quark)** — 80 GB minimum; FP8 only reaches 48 GB. Will not load at any
  shipped precision. Re-check in ~3 months.
- **HuMo** — the *small* 1.7B variant is documented at **32 GB**, above 23.5 GB. The 17B fits via
  ComfyUI-Wan but caps at 97 frames (3.9 s) with **no continuation mechanism** → ~16
  independently-generated segments for 60 s.

### Failing licence for commercial use
- **Wav2Lip / Easy-Wav2Lip** — non-commercial, explicitly.
- **Sonic** — CC BY-NC-SA 4.0; README directs commercial users to Tencent Cloud.
- **FLOAT** — CC BY-NC-ND 4.0, commercial use prohibited.
- **TalkVerse-5B (Snap)** — Snap Non-Commercial Licence. Genuinely painful: best technical fit
  on paper (native minute-long, 720p/1080p, runs on a 4090, "comparable to 14B Wan-S2V at 10×
  lower cost"). **Licence blocks it.**
- **LTX-2.3 AV-LoRA** — research/personal; commercial requires permission.

### Excluded as stale, dormant, or wrong-shaped
- **HunyuanVideo-Avatar** — dormant since 2025-06-06; 24 GB documented as "very slow" for 129
  frames; ComfyUI "forthcoming" for over a year; **licence UNVERIFIED — the LICENSE file 404'd
  and the README does not restate terms. Do not assume Apache. Read it before shipping.**
- **Hallo3** — 18 months stale; reference images must be 1:1 or 3:2, **no 9:16**.
  **No Hallo4 exists** — no evidence of a successor.
- **FantasyTalking** (512² square, 81 frames, stale 2025-07) and **FantasyPortrait**
  (**video-driven, not audio-driven** — wrong family).
- **Ditto** — Apache 2.0, but VRAM/resolution/length all undocumented; lower fidelity ceiling
  (warping-class).
- **OmniHuman** — **no open weights.** Both plausible ByteDance repo URLs 404. API-only.
- **AptAvatar** (Alibaba, 2026-06-29) — **inference code only, weights not released.** Watch item.
- **Wan-Animate-2 / Wan-Dancer** — not audio-driven lip-sync (motion transfer, music-to-dance);
  tuned for 8×A800; ComfyUI still on the Todo list.
- **HunyuanVideo-1.5** — fast and 3090-comfortable, but **no audio-driven or lip-sync variant
  exists.**
- **MoDA** — **not reached before fetch budget ran out. Unknown, not "absent".**

---

## Open questions only an actual run can settle

1. **The real 3090 conversion factor.** Every headline number here is extrapolated from a
   5070 Ti, 4090 or H100. **Run StableAvatar's documented "5 s in 3 min" case first** — one
   measurement recalibrates the whole table.
2. **Identity and colour drift across chained windows.** A 60 s LongCat clip is ~19 sliding
   windows with 13-frame overlap; EchoMimic ~11; Wan-S2V ~13. Sliding-window architectures are
   *classically* where colour drift and identity creep appear, and **every vendor claim of
   "temporal stability" here is marketing with no third-party measurement behind it.**
   Protocol: generate 60 s, sample frames 0/375/750/1125/1499, compare face-embedding distance
   and mean RGB.
3. **Does LatentSync breach the 22 GB guard at 60 s?** Issue #326 shows growth to 23 GB. This is
   the single measurement that could disqualify the primary candidate, and it is cheap to take.
4. **How much base footage does family 3 really need, and does reuse read as looped?** The
   decisive product question for LatentSync — it bounds how many shorts one capture session
   can serve.
5. **Does one-shot identity hold for this specific face?** If yes, LoRA training is avoided
   entirely and family 2 stays closed. If no, the 3090 sits exactly on musubi-tuner's 24 GB floor.
6. **Post-assembly per-segment lip-sync drift.** The April failure was isolated clips looking
   perfect and the assembly not. Every candidate here chains segments. **Score after assembly,
   never on isolated clips.**
7. **Does 16 fps Wan output survive interpolation to 30 fps** without artifacts, if S2V is ever
   promoted from fallback?
8. **Do LeapTalk's FPS claims survive contact with Ampere?** Unknown VRAM, unnamed benchmark GPU.
9. **HunyuanVideo-Avatar's actual licence terms** — must be read before any use.

---

## Corrections to repo state produced by this survey

- **`docs/plans/2026-04-15-001-feat-wan22-avatar-provider-plan.md`** is marked
  `status: blocked-upstream` on a blocker that **was never real** — the kijai fp8 file existed at
  the time. The unblock condition ("Option A: kijai uploads the scaled safetensors") was already
  satisfied.
- **`docs/spikes/echomimic-v3-validation.md`** remains `status: pending`, and the April EchoMimic
  plan was a *hosted-API* benchmark, not a local one. **EchoMimic V3 has never been
  quality-validated on this hardware** — which is why it enters this survey with no incumbency
  credit, as R7 requires.
