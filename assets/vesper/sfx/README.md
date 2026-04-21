# Vesper SFX Pack

Horror-channel SFX pack (registered via
`scripts.audio.sfx.register_pack` at pipeline startup).

**Status:** scaffold. The actual `.wav` files are sourced pre-launch
per the Vesper launch runbook (`docs/operational/vesper-launch-runbook.md`,
Unit 13). Until sourced, `pick_sfx(..., pack="vesper")` will raise
`FileNotFoundError` — which is the correct fail-loud behavior.

## Category layout

Vesper's pack uses the same stable category/intensity axes as
CommonCreed, but the actual filenames (without `.wav`) below map to
horror-tuned sounds rather than whooshes / UI dings:

| Category | Intensity | Expected filenames (without `.wav`) |
|----------|-----------|--------------------------------------|
| `cut`    | `light`   | `cut_rev_short`, `cut_dust_drop`    |
| `cut`    | `heavy`   | `cut_sub_slam`, `cut_reverb_tail`   |
| `punch`  | `light`   | `punch_wooddrop`, `punch_tape_tick` |
| `punch`  | `heavy`   | `punch_subhit`, `punch_bone_snap`   |
| `reveal` | `light`   | `reveal_glass_chime`, `reveal_breath_in` |
| `reveal` | `heavy`   | `reveal_drone_enter`, `reveal_shadow_pass` |
| `tick`   | `light`   | `tick_watch_faint`                   |
| `tick`   | `heavy`   | `tick_clock_hard`                    |

## Sourcing

- Primary: Freesound.org with CC0 filter + commercial-use license tag.
- Hero beats: Sonniss horror pack (one-time purchase, royalty-free).
- Never: Epidemic/Artlist (subscription-locked; rotates out if lapsed).

## Anti-tone-mismatch rules (enforce in code + ops review)

Vesper's pack must NOT include:
- Positive UI whooshes or swooshes
- Notification dings / keyboard clicks
- Dubstep drops or EDM impacts
- Vocoded speech SFX
- White-noise washes (without a narrative purpose)

These are CommonCreed-appropriate but kill the horror register.

## Registration

Vesper's pipeline registers this pack during init via
`register_pack(SfxPack(name="vesper", root_dir=..., category_files=...))`.
The exact `category_files` map is locked in `channels/vesper.py` (Unit 5).
