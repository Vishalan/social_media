# Avatar Shorts v3 Spike — 2026-08

Charter: `docs/plans/2026-08-15-001-feat-avatar-shorts-v3-research-spike-plan.md`

**Question:** have open-source, locally-deployable avatar models advanced enough to
replace the metered VEED/fal.ai path ($0.15/sec) on an RTX 3090?

## Verified environment (2026-08-15)

| | |
|---|---|
| GPU | RTX 3090, 24576 MiB, driver 595.84 |
| Idle free VRAM | **23.5 GB** — and it holds: Ollama idles at 9 MiB, Chatterbox at 12 MiB. **Both lazy-load**, so neither squats on VRAM. Contention is far better than the plan feared. |
| GPU in Docker | verified (`nvidia-container-toolkit`) |
| Disk free | 837 GB — not a constraint |
| Render budget | ≤ 8 h per finished 60 s short |
| Voice | Chatterbox container **up + healthy**; local clone already validated |

## Status

- [x] Unit 0 — diagnosis + GPU bring-up
- [x] **Unit 3 — landscape survey + shortlist  ← COMPLETE**
      - [x] R3 editing grammar: cut cadence + layout vocabulary → `editing-grammar.md`
      - [x] R3 remainder: hooks, captions/safe-areas, audio/LUFS, stat cards → `editing-grammar-part2.md`
      - [x] R1/R6/R7 avatar model landscape (3 families) → `landscape.md`
      - [x] Shortlist (4 candidates + 1 side bet) → `shortlist.md`
      - [x] R2 TTS vs Chatterbox → `tts-landscape.md`, `tts-deep-findings.md`
      - [x] Free config wins found en route → `config-wins.md`
- [ ] Unit 1 — rubric + scorecard
- [ ] Unit 2 — GPU-safe runner  ← **next**
- [ ] Unit 4 — capture spec + session (incl. real-footage control)
- [ ] Unit 6 — Track B reference short
- [ ] Unit 5 — Track A avatar gate
- [ ] Unit 7 — sample shorts
- [ ] Unit 8 — recommendation report


## Findings that change the plan

- **FIRST MEASURED RESULT (2026-08-16): StableAvatar 5 s @ 480×832 took 26 min on the 3090,
  peak 14.0 GB.** Passes the budget at 65 %; 60 s extrapolates to ~5.2 h. But the measured
  3090-vs-4090 factor is **~8.7×, not the 2–2.5× the survey assumed** — so every remaining
  estimate in `landscape.md` is optimistic by roughly 3–4× until measured.
  Full detail + three corrections in **`bench-3090-stableavatar.md`**.
- **The vendor's `model_full_load` config (claimed 18 GB) OOMs on a 3090 with 24 GB free** —
  it dies in VAE encode before the first diffusion step. `model_cpu_offload` is mandatory here.
- **The recommended primary candidate is lip-sync over real footage (LatentSync 1.6) — a family
  the April project never tried.** Identity preservation is perfect by construction: the face is
  real, so it cannot drift. It is also the only candidate in the entire survey with third-party
  *measured* timings. See `shortlist.md` #1.
- **The April Wan2.2-S2V "blocked-upstream" status was never real.** The kijai fp8 file existed
  the whole time, in a *second* repo (`WanVideo_comfy_fp8_scaled`, not `WanVideo_comfy`). That
  plan should be closed. `landscape.md` §"What changed".
- **EchoMimic V3 is demoted and carries no incumbency credit** — frozen 7 months, 768² square
  (not 9:16), 138-frame ceiling, no published wall-clock, and **never quality-validated on this
  hardware** (the April benchmark was a *hosted API*, not a local run).
- **Throughput, not cost, is the binding constraint.** VEED is $4.80–9.00/short vs ~$0.10–0.30 of
  electricity — a 20–50× win. But at 2–3 h/short the 3090 yields **one short per half-day**.
  Unit 8 must report shorts-per-week.
- **Almost every timing figure in the survey is extrapolated, not measured on a 3090** — and the
  3090 has *no FP8 tensor path*, so quoted fp8 speedups on Ada/Hopper/Blackwell do not transfer.
  Run StableAvatar's one documented benchmark first to calibrate the whole table.
- ~~**VRAM contention is a non-issue.** Ollama (9 MiB) and Chatterbox (12 MiB) both lazy-load.
  The full ~23.5 GB is available to an avatar candidate in practice. Unit 2's headroom guard
  is still worth having, but the deadlock risk feasibility review flagged is much reduced.~~
  **RETRACTED 2026-08-16 — measured false.** That reading was taken at *cold idle*. After
  serving a single TTS request, `commoncreed_chatterbox` holds **3.64 GB resident and never
  releases it** — this OOM'd the first real render. Since TTS always runs immediately before the
  avatar stage, the effective ceiling is **~19.9 GB, not 23.5 GB**. The deadlock risk the
  feasibility review flagged is live. Unit 2 must stop/evict Chatterbox before the avatar stage.
  See `bench-3090-stableavatar.md` §Correction 3.
- **Round PIP is questionable as a required layout.** Research found *no* published sizing,
  positioning, or usage convention for round PIP in short-form; it is documented almost
  entirely as a livestream/OBS and TikTok *reaction-cam* convention, carrying an informal
  "responding to someone else's content" connotation that mismatches authoritative tech news.
  Recommendation is rounded-rectangle. See `editing-grammar.md` §B5.
- **Side-by-side split screen is unusable in 9:16** (arithmetic: 540×1920 panels).
  Split must be horizontal/stacked, with evidence on top and presenter below,
  since platform UI clips the bottom 12–20%.
- **The hook must land by 2.0 s, not 3.0 s.** TikTok measures hook rate at 2 s (2sVTR),
  Meta at 3 s. A single master cut must clear the tighter gate, so seconds 2–3 confirm
  rather than introduce. Much published advice builds to 3 s and silently fails TikTok.
  See `editing-grammar-part2.md` §1.1.
- **Music licensing blocks the audio stage and must be decided first.** TikTok's general
  library is personal/non-commercial only; its Commercial Music Library is TikTok-scoped;
  YouTube's Audio Library grants no off-YouTube rights. None survives cross-posting — a
  third-party all-platform license (Epidemic Business / Uppbeat Pro) is required. §3.4.
- **Master to −14 LUFS.** YouTube is the only one of the three publishing a target, and its
  normalization is asymmetric — loud is turned down, quiet is not turned up. The common
  −10/−12 LUFS advice for TikTok/IG targets a spec neither platform has ever published. §3.1.
- **No platform publishes a safe-area spec for organic vertical video.** Every pixel table in
  circulation is a vendor hand-measurement with an unknown expiry date. Screenshot-verify all
  three apps before the reference short locks. §2.1.
- **A large share of circulating "2026 hook statistics" are fabricated.** Six widely-cited
  figures were traced to non-existent studies (fake Tubular Labs, fake Meta eye-tracking, fake
  TikTok Creator Digest). Listed in §0 so they are not re-imported later.
