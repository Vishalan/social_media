# Unit 3 — Chatterbox deep findings (supersedes parts of `tts-landscape.md`)

**Date:** 2026-08-16 · All parameters verified against `chatterbox-tts` 0.1.7 source (PyPI sdist, upload 2026-03-26) cross-checked against git master.

---

## 1. ⚠️ Flash/Turbo/Nano **discard** the expressiveness knobs — this breaks the earlier recommendation

`src/chatterbox/tts_turbo.py`, master, lines 290–291:

```python
if cfg_weight > 0.0 or exaggeration > 0.0 or min_p > 0.0:
    logger.warning("CFG, min_p and exaggeration are not supported by "
                   f"the {self.model_label} version and will be ignored.")
```

`ChatterboxTurboTTS.generate()` defaults are `exaggeration=0.0, cfg_weight=0.0`. **Turbo, Nano and Flash share this architecture — the expressiveness controls are inert on all of them.**

**This directly contradicts the recommendation in `tts-landscape.md` §5** ("upgrade to Flash first — nearly free"). Flash buys ~3× speed (RTF 0.076–0.107) and **costs the only prosody controls the model has**. For a channel whose hook lives or dies in the first 1–3 seconds, that is not a free upgrade — it is a trade.

**Revised sequencing:**

| Priority | Action | Rationale |
|---|---|---|
| 1 | **Tune `exaggeration`/`cfg_weight` on the CURRENT `ChatterboxTTS`** | Free, and we are demonstrably mis-set — see §2 |
| 2 | Trial **Step Audio EditX** (Apache 2.0, +89 Elo, real emotion control) | The only licence-clean path to *better* expressiveness |
| 3 | Consider Flash **only** for bulk/non-hook narration | Speed where delivery matters least |

Speed was never the constraint anyway — the render budget is 8 h per short, and TTS at ~18 s/minute is nowhere near binding.

---

## 2. Our deployment is tuned FLATTER than stock — the opposite of what short-form wants

Verified stock defaults in `ChatterboxTTS.generate()`:

```python
exaggeration=0.5, cfg_weight=0.5, temperature=0.8,
repetition_penalty=1.2, min_p=0.05, top_p=1.0
```

`deploy/chatterbox/server.py` passes **`exaggeration=0.3`** — below the 0.5 stock default — and never passes `cfg_weight` at all.

**So the earlier framing in `config-wins.md` was too generous.** This is not merely "an untuned parameter": we are running **deliberately flatter than default**, on a channel that needs punchy narration.

**Vendor-documented expressive preset** (README "Original Chatterbox Tips", on master 2026-08-16):
- `exaggeration=0.5, cfg_weight=0.5` — works for most prompts
- **Expressive/dramatic: `cfg_weight ≈ 0.3`, `exaggeration ≈ 0.7+`**
- *"Higher `exaggeration` tends to speed up speech; reducing `cfg_weight` helps compensate with slower, more deliberate pacing."* — the interaction is **vendor-documented, not folklore**
- Fast-speaking reference clip → `cfg_weight ≈ 0.3` improves pacing

**Test 0.7 / 0.3 against stock 0.5 / 0.5 against current 0.3 / default.** No independent study measures these; guidance is vendor + folklore, and one HN report says raising CFG too far degrades into gibberish — so sweep, don't assume.

---

## 3. Reference clip: only the **first 10 seconds** matter — changes the capture spec

From source:

```python
ENC_COND_LEN = 6  * S3_SR      # 16 kHz → first  6 s → T3 speech-conditioning tokens
DEC_COND_LEN = 10 * S3GEN_SR   # 24 kHz → first 10 s → s3gen decoder reference
# only ve_embed (speaker embedding) consumes the full clip
```

On our 30-second `vishalan_voice_ref.wav`, **only the first 10 seconds drive prosody and timbre.** The remaining 20 seconds feed nothing but the speaker embedding.

**Consequences for Unit 4's capture spec:**
- **Put the best-delivered, most on-tone passage at the HEAD of the file.** This is a free quality win and nobody would guess it from the docs.
- 24 kHz mono is exactly right — `S3GEN_SR = 24000`, so no resampling penalty on the decoder path.
- **The original `ChatterboxTTS` does not loudness-normalise the reference at all** (Turbo/Nano normalise to −27 LUFS; the model we run does not). So the absolute level of a demucs-isolated clip is an **uncontrolled variable** across runs. Normalise it ourselves for run-to-run consistency.

---

## 4. The 63.75% claim is weaker still — it tested a **pre-release** build

Beyond the 8 clips / ~80 ratings already noted: embedded timestamps show the evaluation ran **2025-05-16 to 2025-05-22**. Chatterbox's public release was **PyPI 0.1 on 2025-05-28**. **The study tested a pre-release model.**

Statistical detail: per-file standard errors against per-file CIs give **n ≈ 10 ratings per file** — roughly *10 listeners*, not 80. Per-file means range −1.30 to **+0.20**; one clip actually favoured ElevenLabs and two have CIs straddling zero. The ElevenLabs version is never identified.

The direction is genuine (mean −0.6375 reproduces the report's −0.64), but **cite it as "Resemble's own May-2025 study, 8 clips, ~10 listeners, unspecified ElevenLabs version, pre-release build" — never as established fact.**

**Two independent arenas, both observed 2026-08-16, rank Chatterbox below every ElevenLabs model:**

| Arena | Chatterbox | Best ElevenLabs |
|---|---|---|
| HuggingFace TTS Arena V2 (35,478 votes) | #32, Elo 1480, 1767 votes | Turbo v2.5 #15, Elo 1511 |
| Artificial Analysis Speech Arena | #70, Elo 1021, 4845 votes | v3 #10, Elo 1177 |

Even Resemble's own *paid* Chatterbox HD sits at #33, below Eleven v3.

**The honest justification for Chatterbox is cost, self-hosting and the MIT licence — not measured parity.**

*Independent academic datapoint* (arXiv 2607.23027, 2026-07-25): baseline Chatterbox scores UT-MOS 3.34, WER 11.48% — **better intelligibility than the 17.31% ground truth** — but loses on speaker similarity, with the specific criticism being **"accent flattening"**: clean, accent-neutral output. Relevant for an owner-voice channel where the accent *is* part of the identity.

---

## 5. Open upstream bugs we will hit

All verified open 2026-08-16:

| Issue | Problem |
|---|---|
| **#424** | Turbo hallucinates beyond ~350 chars |
| **#388** | Long hallucinations / silence / breathing at tail end |
| **#519** | `long_tail` detection fires early → token repetition before forced EOS |
| **#549** | Anti-repetition guard checks 2 tokens while docs/logs claim 3 |
| **#548** | **IndexError crash on text ≤5 tokens** — root cause of #201/#435. Directly hazardous to naive sentence splitting |
| **#536** | Persistent **~4900 Hz background tone** + elevated silence floor, traced to the vocoder |

**The best available defence** is `petermg/Chatterbox-TTS-Extended`'s QC loop: generate **N candidates per chunk**, transcribe each with Whisper, compare against input text, retry on divergence, fall back to best similarity. The fork is stale (~12 months) but the pattern is trivially portable — and hallucination has no upstream fix in sight.

Note the synergy: we already need Whisper for captions. The same GPU-resident `large-v3` serves both caption timing **and** TTS validation.

---

## 6. Post-processing: the April learning was right, and now we know why

The most feature-maximalist fork in the ecosystem (`petermg`) converged on exactly three steps: **denoise (RNNoise) → trim (auto-editor) → loudness-normalise (ffmpeg EBU R128)**. **No pitch shift, no EQ, no compressor, no de-esser** — and none in `devnen` either. That is consensus by omission across the whole ecosystem, and it independently confirms the April finding that pitch/EQ post-processing made output *worse*.

**Mechanism** for why the usual voice-recording chain is the wrong reflex: the output is already dry, clean and gain-controlled — no room, no proximity effect, no plosives, no take-to-take variance. Compressor and de-esser exist to fix problems that aren't present, and **compression makeup gain amplifies the documented #536 vocoder hiss during quiet passages** (classic pumping noise floor). A high-shelf boost sits right on top of ~4.9 kHz.

**The one justified corrective EQ** is a narrow notch at the measured #536 tone — repair of a documented defect, not tonal taste.

**Recommended chain:** trim → gentle high-pass ~60–80 Hz → optional targeted denoise → **two-pass `loudnorm` with `linear=true`** → light peak limiting as safety only.

Two-pass matters: one-pass `loudnorm` applies *time-varying* gain, which is exactly the uncontrolled compression to avoid on vocoder output. Measure first, feed values back with `linear=true` for a single static gain.

**Targets:** YouTube / TikTok / Spotify **−14 LUFS**, true peak **−1.0 dBTP** (−2 dBTP if the master is loud, to survive transcoding).

`pyloudnorm` is what Chatterbox uses internally — the natural in-process choice if we want to avoid a subprocess.

---

## 7. Watermarking — worth knowing

Chatterbox embeds Resemble's **PerTh** watermark on every generated file (`tts.py:271`). Resemble claims it survives MP3 compression and common edits; **no independent test of survivability under EQ, compression or pitch shift exists.** If we ever rely on watermark detection to audit our own output, verify it survives our chain rather than assuming. Removing it is not recommended — it is the provenance mechanism, and it connects to the AI-disclosure obligations in the plan's Security Posture (S-h).

---

## 8. Adoption reality check

HuggingFace 30-day downloads: **2,112,048 for the original English model** vs **0 for Turbo, Nano and Flash.** Likes 1738 / 677 / 19 / 14. Practically the entire user base is still on the original — so community troubleshooting, forks and tooling all target what we already run. Another argument against jumping to Flash.
