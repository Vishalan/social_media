# CommonCreed SFX Library — Manifest & License

This directory holds the 15 short sound effects used by the v2 Engagement
Layer (cut / punch / reveal / tick categories).  All clips are mono 16-bit
PCM WAV at 44.1 kHz and are peak-normalized to roughly -3 dB.

## Sourcing

A two-tier strategy was used per clip:

1. **Tier 1 — CC0 download.**  We attempted best-effort `urllib` fetches
   from curated CC0 sources (Pixabay / Mixkit).  These hosts normally
   block hotlinking, so the download fell through to Tier 2.
2. **Tier 2 — in-repo synthesis.**  Synthesized deterministically by
   `scripts/audio/_generate_sfx.py` using `numpy` + the stdlib `wave`
   module.  Each recipe is a short audible waveform (white-noise burst,
   swept sine, half-cycle sine × exp decay, etc.) documented in the
   generator's docstrings.

For this checked-in version **every file was generated via Tier 2**
because no Tier 1 URL was available at build time (sandbox has no
network access).  Re-running `python -m scripts.audio._generate_sfx`
produces byte-identical output (recipe RNGs are seeded).

## License

All Tier-2-synthesized clips in this directory are released under
**CC0 1.0 Universal** by the CommonCreed project.  You may reuse,
remix, and redistribute them without attribution.

If any Tier-1 downloads are ever added, the manifest below must
document the source URL and that source's license verbatim.

## Manifest

| File | Source | License | Recipe / Notes |
|------|--------|---------|----------------|
| `cut_whoosh.wav`    | synthesized in-repo | CC0 | 100 ms white-noise burst, 10 ms attack + 40 ms exp decay, 50-tap box LPF |
| `cut_swoop.wav`     | synthesized in-repo | CC0 | 180 ms swept sine 800→200 Hz, 80 ms Hann tail |
| `cut_swish.wav`     | synthesized in-repo | CC0 | 120 ms filtered noise burst, 45 ms exp decay |
| `pop_short.wav`     | synthesized in-repo | CC0 | 40 ms half-cycle 800 Hz × exp decay τ=20 ms |
| `pop_high.wav`      | synthesized in-repo | CC0 | 35 ms half-cycle 1200 Hz × exp decay τ=15 ms |
| `pop_low.wav`       | synthesized in-repo | CC0 | 50 ms half-cycle 400 Hz × exp decay τ=30 ms |
| `ding_clean.wav`    | synthesized in-repo | CC0 | 300 ms 1500 Hz sine × exp decay τ=150 ms |
| `ding_chime.wav`    | synthesized in-repo | CC0 | 300 ms (1000 + 1500) Hz sines × exp decay τ=160 ms |
| `tick_soft.wav`     | synthesized in-repo | CC0 | 25 ms 2 kHz sine × 20 ms Hann |
| `tick_hard.wav`     | synthesized in-repo | CC0 | 20 ms noise burst, first-difference HPF × exp decay |
| `thud_soft.wav`     | synthesized in-repo | CC0 | 200 ms 80 Hz sine × exp decay τ=100 ms |
| `thud_dramatic.wav` | synthesized in-repo | CC0 | 250 ms 60 Hz sine × exp decay τ=120 ms |
| `whoosh_long.wav`   | synthesized in-repo | CC0 | 400 ms swept filtered noise (heavy→light box LPF) × Hann |
| `swipe_in.wav`      | synthesized in-repo | CC0 | 220 ms swept sine 300→1200 Hz × Hann |
| `swipe_out.wav`     | synthesized in-repo | CC0 | 220 ms swept sine 1200→300 Hz × Hann |

## Regeneration

```bash
python -m scripts.audio._generate_sfx
```

The generator is idempotent and overwrites the directory.  Output
sizes land in the 1.8 – 35 KB range, comfortably under the 50 KB
per-file budget.
