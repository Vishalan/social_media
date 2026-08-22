# Chatterbox sidecar

`server.py` is the TTS service running in the `commoncreed_chatterbox`
container at `/app/server.py`.

**This file is the source of truth.** The running copy lives in the
container's writable layer, so recreating the container from its image
silently reverts it — and the symptom is not an error but a 404 on
`/tts_blend`, or worse, a plain `/tts` that quietly behaves like an older
build. After any `docker compose up --force-recreate` or image rebuild,
copy this file back in and restart:

    docker cp services/chatterbox/server.py commoncreed_chatterbox:/app/server.py
    docker restart commoncreed_chatterbox

## Endpoints

* `POST /tts` — single reference, unchanged.
* `POST /tts_blend` — two references, interpolating the speaker identity
  between them while taking delivery wholesale from one.

## Why blending needs a server-side endpoint

Chatterbox conditions on two separable things, and only one of them can be
mixed arithmetically:

* `t3.speaker_emb` and `gen["embedding"]` are continuous identity vectors —
  WHO is speaking. These interpolate.
* `cond_prompt_speech_tokens`, `gen["prompt_token"]`, `gen["prompt_feat"]`
  are discrete tokens and frame features taken from the reference — HOW they
  speak: cadence, settledness, how consonants land. Averaging token IDs
  yields a third token meaning something unrelated, so delivery is taken
  whole from whichever reference `prompt_from` names.

Both are computed inside `prepare_conditionals()` and never exposed over
HTTP, which is why this cannot be done from the client.

Interpolation is spherical (`_slerp`), not linear. The embeddings are
L2-normalised, so a straight average of two unit vectors is SHORTER than
either — at the halfway point that reads as weaker conditioning and a
blander voice, precisely where the blend should be most interesting.
