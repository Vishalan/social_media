# Voice options — all local, all free

Every option below runs on the 3090 and costs nothing per video. No paid API
is involved and none is needed.

## Where the voices come from

Chatterbox is a zero-shot cloner: it copies whatever voice it is given as a
reference. So the choice of voice is really a choice of REFERENCE CLIP, and
the pool of references is what limits the options — not the model.

Two references carry natural Indian English: `k_hm_psi.wav` and
`k_hm_omega.wav`, generated once from Kokoro-82M's Hindi male voices
(Apache-2.0, commercial use, no attribution). They speak Hindi in the
reference clip purely to establish WHO is speaking; Chatterbox then puts that
speaker onto English text.

## How the palette is larger than the reference pool

`/tts_blend` (see services/chatterbox/) sources two things separately:

* DELIVERY — cadence, phrasing, and crucially ACCENT — taken whole from the
  reference named by `prompt_from`, because it lives in discrete tokens that
  cannot be averaged.
* IDENTITY — the speaker embedding, interpolated by `alpha`.

Because accent travels with delivery, holding `prompt_from` on an Indian
reference keeps the Indian English fixed while identity is borrowed from any
other voice. Two Indian references therefore generate a whole palette rather
than two options.

## The set

| name | recipe | F0 | range | dyn |
|---|---|---|---|---|
| omega | psi/omega solo, prompt+id from omega | 135.9 | 15.3 st | 24.6 |
| psi | solo, prompt+id from psi | 133.9 | 13.1 st | 22.9 |
| psi+omega | omega identity into psi delivery, a=0.50 | 128.6 | 14.0 st | 17.0 |
| omega deep | am_onyx identity into omega delivery, a=0.45 | 126.4 | 14.4 st | 22.1 |
| psi deep | am_onyx identity into psi delivery, a=0.45 | 115.2 | 13.7 st | 19.6 |
| psi rich | bm_lewis identity into psi delivery, a=0.45 | 125.7 | 12.8 st | 24.3 |

For comparison the owner's natural voice measures F0 135.5, range 14.7 st,
dynamics 17.0; the pipeline as previously configured produced 151.2 / 11.1 /
12.4 — higher, flatter and more compressed than the owner actually is.

## Blocked, not abandoned

Indic Parler-TTS (AI4Bharat, Apache-2.0) is the strongest local Indian
English option and is installed at /home/vishalan/pvenv. It is gated on
HuggingFace and needs the owner to accept the licence and supply a token
before it can be evaluated. Piper has no en_IN voices at all; XTTS-v2 is
non-commercial and so is wrong for a channel intended to earn.
