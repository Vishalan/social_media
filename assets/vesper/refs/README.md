# Vesper Archivist Reference Audio

Voice-clone reference clip for Vesper's Archivist narrator.

**Status:** scaffolding. The actual `archivist.wav` is sourced
pre-launch by the owner per the Vesper launch runbook (Unit 13):

- **Length:** 30-60 s, single speaker, no background noise
- **Format:** WAV, 24 kHz+, mono preferred
- **Register:** low, tense, semi-whispered, mid-pitch male
- **Sample line:** "This was shared with me. A trucker near
  Amarillo told me…"

## Biometric classification (Security Posture S3)

**This file is biometric-equivalent.** A leaked reference clip lets
an attacker synthesize arbitrary speech in the narrator's voice.

- **NEVER commit**: `/assets/**/refs/**` is blocked in `.gitignore`.
- **NEVER print** in logs, Telegram messages, or PR comments.
- **Mount read-only** into the chatterbox sidecar (`- assets:/app/refs:ro`).
- **Rotate every 6 months.** Bump the version ID in
  `channels/vesper.py::VoiceProfile` alongside each rotation so
  analytics can trace which videos used which clip (enables
  batch-unpublish on suspected breach).
- **Breach runbook:** `docs/operational/vesper-deepfake-breach-runbook.md`

## Verification before first run

1. Copy the sourced `archivist.wav` to `assets/vesper/refs/archivist.wav`
   on the dev host.
2. On the Ubuntu server: copy to `/opt/commoncreed/assets/vesper/archivist.wav`.
3. Confirm via `curl http://commoncreed_chatterbox:7777/refs/list`
   — output must include `"vesper/archivist.wav"` among entries.
4. Run the Unit 8 characterization test (chunking still works for
   5-min scripts) to confirm no regression.
