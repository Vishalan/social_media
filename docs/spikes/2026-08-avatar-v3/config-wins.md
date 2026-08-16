# Free wins found in existing config (verified 2026-08-16)

Two findings surfaced during Unit 3 research and **verified directly against the repo**.
Both are configuration defects, not tooling gaps — so they cost nothing but a parameter
change, and they must be corrected *before* any comparison is run, or the spike will
measure the wrong thing.

---

## 1. Caption transcription runs the smallest model, on CPU, quantised — on a box with an idle RTX 3090

**Verified:**

- `scripts/commoncreed_pipeline.py:708`
  `WhisperModel("base", device="cpu", compute_type="int8")` — hardcoded.
- `scripts/vesper_pipeline/captions.py:55-59`
  `transcribe_voice(model_name="base", device="cpu", compute_type="int8")` — same defaults,
  though at least parameterised.

This is the **smallest** Whisper model, on **CPU**, at **int8** precision. Every one of those
three choices costs word-timing accuracy, and all three were presumably set when the box had
no usable GPU. The GPU now works and idles at ~23.5 GB free.

**Why it matters for R5.** The plan treats "word-level caption timing accurate enough to
publish unedited" as a research question needing a possible tooling change. It may be almost
entirely a config question: `large-v3` on GPU at `float16` versus `base` on CPU at `int8` is a
large accuracy gap, at zero new dependencies.

**Action — do this before evaluating any caption tooling:** re-run existing audio through
`large-v3` / `cuda` / `float16` and measure the word error rate delta against the current
baseline. Only if a real gap survives that change is a tooling switch (WhisperX, stable-ts,
forced alignment) worth considering. Otherwise R5 closes with "fix the config".

**Secondary note.** Two divergent transcription implementations exist — one in
`vesper_pipeline/captions.py`, one inline in `commoncreed_pipeline.py`. Unit 6 must name which
one it consumes (already flagged in the plan). Fixing the config in one and not the other would
leave a silent accuracy split between channels.

---

## 2. Chatterbox runs FLATTER than stock, and never passes `cfg_weight`

> **Updated 2026-08-16** — deeper source verification showed this is worse than first described.
> Stock `ChatterboxTTS` defaults are `exaggeration=0.5, cfg_weight=0.5`. We pass **`exaggeration=0.3`**,
> which is *below* stock — i.e. deliberately flatter — on a channel that needs punchy hook delivery.
> The vendor-documented expressive preset is **`exaggeration≈0.7, cfg_weight≈0.3`**, and the two
> interact by design: higher exaggeration speeds speech up, lower cfg_weight slows and deliberates it.
> **Also critical: Turbo / Nano / Flash discard both parameters entirely** (`tts_turbo.py:290`), so
> "upgrade to Flash for speed" would forfeit the only prosody controls the model has.
> Full detail in `tts-deep-findings.md`.

**Verified:** `deploy/chatterbox/server.py:187-190`

```
wav = model.generate(
    text,
    audio_prompt_path=ref,
    exaggeration=req.exaggeration,   # default 0.3
)
```

`exaggeration` is plumbed through the API (default `0.3`, range 0.0–1.0). **`cfg_weight` is
never passed at all**, so it takes whatever the library defaults to. In Chatterbox, `cfg_weight`
and `exaggeration` interact — they are the pair that governs delivery, and tuning one without
the other leaves the voice in an untested corner of the parameter space.

**Why it matters for R2.** The plan's TTS question is "has anything beaten Chatterbox since
April". But the current deployment has never had its two expressiveness controls tuned together.
If delivery feels flat for short-form narration, that may be a parameter default rather than a
model ceiling — and tuning is far cheaper than swapping models and re-validating a clone.

Relevant prior learning: post-processing the audio (pitch shift, bass EQ) made output *worse*;
the raw clone won. That finding says nothing about generation-time parameters, which remain
unexplored.

**Action — before any TTS switch is considered:** sweep `exaggeration` × `cfg_weight` on the
same reference clip and script, and judge on hook delivery specifically (the first 1–3 s carries
disproportionate weight). Only recommend a model change if the best-tuned Chatterbox still falls
short.

---

## Why both belong in the spike, not the build

The spike exists to avoid the April failure mode of building before validating. These two
findings are the same principle applied one level down: **do not benchmark a subsystem against
alternatives while it is running on defaults nobody chose.** A comparison run now would
attribute a config deficit to the model, and the recommendation would be wrong in a way that
costs real work to unwind.

Both fixes are cheap enough to land inside Unit 3.
