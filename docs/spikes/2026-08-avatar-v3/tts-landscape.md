# Unit 3 — Local TTS Landscape (R2)

**Date:** 2026-08-15/16 · **Verdict: do not switch wholesale — but upgrade within Chatterbox, and the plan's justification for skipping this research was wrong.**

Every number below traced to a primary repo, model card, LICENSE file, arXiv paper, or the blind-vote arena itself, with fetch date. The search space around this topic is heavily polluted by SEO farms recycling vendor claims.

---

## 1. ⚠️ The "64% beats ElevenLabs" claim does not survive inspection

This matters because **the plan used that claim to justify narrowing R2 to a spot-check.** The justification was weaker than it looked.

Pulled the actual source (Podonos report linked from Resemble's own model card, fetched 2026-08-15):

| Result | Share |
|---|---|
| Chatterbox strongly preferred | 38.75% |
| Chatterbox moderately preferred | 25.00% |
| Neutral | 8.75% |
| ElevenLabs moderately preferred | 16.25% |
| ElevenLabs strongly preferred | 11.25% |

38.75 + 25.00 = **63.75%** — that is the origin of "beats ElevenLabs in ~64%".

**The basis is 8 audio files and 80 listener responses.** No test date published. ElevenLabs model/settings unspecified. Podonos is a third-party eval *platform*, but the study is commissioned and published by Resemble. **Classify as vendor marketing, not independent measurement.**

### Independent counter-evidence — Artificial Analysis blind-vote Elo (fetched 2026-08-15, reflects July 2026)

| Open-weights model | Elo | Rank | Licence | Commercial? |
|---|---:|---:|---|---|
| Fish Audio S2 Pro | 1124 | 24 | Fish Research Licence | **No** |
| Step Audio EditX | 1110 | 28 | Apache 2.0 | **Yes** |
| Voxtral TTS (Mistral) | 1081 | 39 | CC BY-NC | **No** |
| Magpie-Multilingual 357M | 1066 | 47 | gated | unknown |
| Kokoro 82M | 1059 | 51 | Apache 2.0 | Yes — **no cloning** |
| Maya1 | 1047 | 59 | Apache 2.0 | Yes — **no reference cloning** |
| Higgs Audio V3 | 1041 | 61 | Boson Non-Commercial | Restricted |
| **Chatterbox** | **1021** | **70** | MIT | **Yes** |
| XTTS v2 | 920 | 84 | Coqui non-commercial | **No** |

No open-weights model reaches the overall top 10 — those are all proprietary (Speechify Simba 3.2 @1239, Qwen-Audio-3.0-TTS-Plus @1237, ElevenLabs v3 @1177).

**Two caveats that cut in Chatterbox's favour:** the arena entry is almost certainly the original 2025 model, not Turbo/v3/Flash — so it is *not* what you would deploy today. And arena voting tests **default voices, not zero-shot clone fidelity**, which is the thing that actually matters here.

---

## 2. Chatterbox has three variants we don't have

Our deployment is roughly the **June 2025** model. All below are MIT, verified on Resemble/HF 2026-08-15:

- **Chatterbox Turbo** — 350M, updated 2025-12-15. Keeps `exaggeration` + `cfg_weight`. 23+ languages, ~6× realtime.
- **Chatterbox Multilingual v3** — released **2026-06-10**. 0.5B Llama backbone, 25 languages, English CER 0.65%. Resemble explicitly states MOS and speaker-similarity benchmarks are **not yet done** — quality-vs-v2 is unsubstantiated.
- **Chatterbox Nano** (110M) and **Flash** (0.5B) — both **2026-07-06**. Nano: 10× realtime GPU, 5-second reference clip, native paralinguistic tags `[laugh] [sigh] [chuckle] [cough]`. **Flash: block-diffusion decoder, RTF 0.076–0.107 (~9–13× realtime), TTFP 103 ms.**

Flash has a real arXiv paper (2605.30748, 2026-05-29). Its benchmark table is the most useful cross-model data found — self-run, but on public benchmarks with published baselines:

| Model | Params | Seed-TTS SIM-o / WER / UTMOS |
|---|---:|---|
| OmniVoice | 0.8B | **0.741** / 1.60 / 3.91 |
| Qwen3-TTS | 1.1B | 0.708 / **1.54** / **4.16** |
| IndexTTS2 | 1.7B | 0.706 / 2.33 / 3.65 |
| Chatterbox-Flash | 0.5B | 0.704 / 1.96 / 4.09 |
| CosyVoice3 | 1.1B | 0.696 / 2.17 / 3.96 |
| Chatterbox (base) | 0.5B | 0.685 / 2.20 / 4.10 |
| F5-TTS | 0.4B | 0.664 / 1.85 / 3.72 |

**F5-TTS is now clearly mid-tier** — worst speaker similarity in the set. No 2026 F5/E2 successor found.

---

## 3. Licence traps — the decisive filter for a monetised channel

Most of the higher-Elo models are commercially unusable. All verified against primary LICENSE/model card 2026-08-15:

| Model | Licence reality |
|---|---|
| **Fish Audio S2 Pro** | Research/non-commercial free; **commercial requires separate Fish licence** |
| **Voxtral TTS** (Mistral) | **CC BY-NC** — non-starter |
| **IndexTTS-2.5** (released 2026-08-10) | bilibili licence: "for commercial usage, contact indexspeech@bilibili.com" |
| **OmniVoice** | Code Apache 2.0, **weights CC-BY-NC** |
| **Higgs Audio v3** | Boson Non-Commercial — **BUT has a "Creator Use Grant": digital creators may monetise content with attribution.** Worth reading in full. |
| **XTTS-v2** | Coqui defunct (last update 2023-12-11), licence non-commercial. **Dead end — do not build on it.** |

**Clean commercial licences with real zero-shot cloning:** Chatterbox (MIT), Step Audio EditX (Apache 2.0), Fun-CosyVoice 3.0 (Apache 2.0), Qwen3-TTS (Apache 2.0), VoxCPM-0.5B (Apache 2.0).

---

## 4. Prosody / emotion — where Chatterbox is genuinely weakest

This is the real upgrade available, and it matters disproportionately for a **hook** in the first 1–3 seconds.

| Rank | Model | Control mechanism | Blocker |
|---|---|---|---|
| 1 | **IndexTTS-2.5** | Emotion reference audio + **8-float emotion vector** + natural-language emotion prompts + `duration_factor` 0.5–2.0× speaking-rate control (genuinely useful for fitting narration to cut timings) | **Licence** |
| 2 | Fish Audio S2 Pro | 15,000+ free-form inline tags | **Licence** |
| 3 | Higgs TTS 3 | Inline `<\|emotion:\|> <\|style:\|> <\|prosody:\|> <\|sfx:\|>` tags | Creator Use Grant may cover us |
| 4 | **Step Audio EditX** | Iterative emotion/style editing; emotion accuracy 71.6% → 83.4% over 3 passes. 12 GB VRAM (6–8 GB at AWQ4) | **None — Apache 2.0** |
| 5 | Fun-CosyVoice 3.0 | Natural-language emotion/speed/volume instructions | None — Apache 2.0 |
| — | **Chatterbox** | **A single scalar `exaggeration`.** No instruction-following. | — |

That last row is a real capability gap versus everything above it.

**Not cloning models despite the hype:** Kokoro-82M (no cloning at all) and Maya1 (voice *design* from text descriptions, not reference-audio cloning) — though Maya1 is interesting for a faceless brand where matching a specific voice is not required.

---

## 5. Recommendation — three moves, in value order

**Do not switch wholesale.** No commercially-licensed model beats Chatterbox by a margin justifying re-integration and re-validation of the voice clone.

1. **Upgrade within Chatterbox first — nearly free.** We run the 2025 model. Multilingual v3 and Flash are same-family, same MIT, same API surface. **Flash at RTF 0.076–0.107 would take 1 minute of speech from ~18 s to roughly 5–7 s on the 3090.** Lowest risk, highest certainty.
2. **Trial Step Audio EditX against Chatterbox on actual hook copy.** The only model that is simultaneously Apache 2.0, +89 Elo on independent blind voting, and has genuine emotion control. 12 GB is a non-issue on our box. Fun-CosyVoice 3.0 is the fallback if EditX's English cloning disappoints.
3. **Read the Higgs TTS 3 Creator Use Grant properly.** If it covers monetised YouTube content, it gives the strongest tag-based prosody control outside the licence-blocked tier.

**Sequencing note:** do all of this *after* the `cfg_weight` fix in `config-wins.md`. Our current deployment never passes `cfg_weight` at all, so it runs on a library default — benchmarking a tuned competitor against an untuned incumbent would produce a wrong answer.

---

## 6. Gaps and health warnings

- **Magpie-Multilingual 357M** (Elo 1066, above Chatterbox) is gated on HuggingFace, returned 401. Licence unverified — worth a manual look.
- Could not obtain a HuggingFace TTS Arena snapshot to corroborate Artificial Analysis (renders client-side).
- Search budget exhausted mid-task; the sweep for very recent entrants leaned on HF trending/recent listings rather than search.
- Several SEO sources confidently asserted "Chatterbox beat ElevenLabs" **without ever noting it was 8 samples.**

## 7. Consequence for the plan

The plan's Key Decision reads: *"Narrow R2 (voice) to validation. The Chatterbox clone is backed by a documented blind A/B result."*

**That justification is now known to be weak** — 8 files, 80 responses, vendor-commissioned. The *conclusion* (don't switch) survives on different and better grounds: **licence filtering**, not measured superiority. Nearly everything ranked above Chatterbox on independent blind voting is commercially unusable.

R2 should therefore be re-scoped from "validate the incumbent" to: **upgrade within the family (Flash), fix `cfg_weight`, and run one licence-clean challenger (Step Audio EditX) on real hook copy.** That is more work than the plan allowed for, and it is justified.
