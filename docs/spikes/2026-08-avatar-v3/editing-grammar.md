# Unit 3 — Editing Grammar Research (partial)

**Date:** 2026-08-15 · **Covers:** R3 (cut cadence, layout vocabulary) · **Status:** cadence + layout complete; hooks, caption typography/safe-areas, audio/LUFS, stat-cards incomplete (session search budget exhausted)

---

## ⚠️ Read this first — epistemic health warning

Research-grade evidence for short-form cut cadence **essentially does not exist**. Nearly all 2026 published guidance is SEO content marketing from AI-editing vendors (OpusClip, CapCut, Clippie, Shortzly, Aibrify, ChatCut, CutScore, ContHunt). Those numbers are:

- **mutually contradictory** — recommended cut interval spans **1.0 s to 5.0 s** for the same genre
- almost never tied to a stated dataset, sample size, or methodology
- frequently **laundered** — one unsourced figure restated by five blogs until it looks like consensus

Confidence tags used throughout: **[E]** evidence-adjacent · **[F]** folklore/convention · **[D]** derived here from adjacent constraints, unsourced.

Treat **[F]** numbers as *conventions worth matching* (they define the genre's visual grammar), **not** as optimisation targets.

**Specifically distrust:** the widely-cited "2.5 s average shot length → 35% higher completion" (VidPros, May 2025). Unsourced, no methodology, and correlational over top performers — selection-biased by construction. Drop it from decisions.

---

## Part A — Cut cadence

### A1. The published range

| Source | Date | Talking head | B-roll |
|---|---|---|---|
| CutScore | Jun 2026 | **4–8 s** | 2–5 s |
| Shortzly | **Aug 8 2026** | TikTok 1.5–3 s / Reels 2.5–4 s / Shorts 3–5 s | — |
| Aibrify | Apr 2026 | — | **1.5–3 s**; 5–7 visual changes per 10 s |
| OpusClip | Nov 2025 | one cut every 2–4 s | — |
| ContHunt | Apr 2026 | 2–3 s, max static 2.8 s | — |
| Captions.ai | Jun 2026 | — | establishing 2–4 s / detail 1.5–3 s / reaction 1–2 s |
| Kudoflix | Jul 2026 | — | 2–5 s vertical |

**Three 2026 shifts that matter more than any single number:**

1. **From "cut" to "visual change."** The unit is now *stimulus events*, not edits — a cut, camera push, text swap, zoom, or reveal all count. A slow push-in **substitutes for** a cut. This is the single most important reframing, and it's liberating for a talking-head pipeline: you can hit stimulus density without shredding the A-roll. **[F]**
2. **From uniform to variable** — see A2.
3. **Slower for information-dense content.** Educational/explainer consistently gets a longer floor than entertainment across every source that segments by type.

**Is there a backlash toward slower editing?** Yes — but against *ornamental* editing, not fast cutting per se. Two independent Instagram trackers in the target window (NewEngen Jul 31; Lightreel Aug 8 2026) report raw/single-take straight-to-camera outperforming polished. For an info-dense tech short, this does **not** license slow cutting; it licenses fewer decorative transitions and more variance. **[E-adjacent]**

### A2. Cadence must vary across the 60 s arc — highest-confidence finding

Unanimous across every 2026 source, though still **[F]**. Direction is **front-loaded fast → settle → controlled slow-down at payoff** — the opposite of the music-video model.

The one structural claim with an analytics basis: for 30–60 s videos the **40–60% mark is the critical failure zone** (~24–36 s in a 60 s piece); "tighten the middle" is the highest-leverage edit (Retensis, Apr 2026, from TikTok Studio retention curves, sample size undisclosed). **[E-adjacent]**

Counter-mechanism worth heeding: retention "falls off a cliff" around **second 6** when cutting rhythm becomes *predictable*, with viewers mapping the structure by **seconds 8–9** (Sparkhouse, May 2026). **[F]** but falsifiable — and it argues that **variance itself is the parameter**, not mean cadence.

### A3. When a longer hold beats fast cutting

- **Punchline / reveal** — land the punch on a snappy cut, then hold the next shot a beat longer; contrast does the work.
- **Payoff beats: hold 3–4 s** (Aibrify — the only source giving a number). **[F]**
- **Dense information / statistics** — tutorial/how-to 5–9 s per shot (CutScore). For on-screen numbers the binding constraint is legibility, not pacing: **≈3 s + 0.5–0.7 s per word**; a 1–3 word label needs **2.5–4 s**. **[E]**
- **General principle everyone converges on:** anchor cuts to *meaning shifts*, not a clock. "Cut a shot the moment it stops earning its place, and not a frame before."

### A4. Talking head vs b-roll — do NOT cut them at the same rate

Structural asymmetry, broadly agreed: talking-head shots carry the argument and must survive a full clause; b-roll is illustrative and reads in ~1.5 s.

**Critical distinction for the pipeline:** talking head appears to "cut often" only because those are **jump cuts from silence removal** — the shot doesn't change, the *time* does. Do not conflate the two counts.

- **A/B ratio: ~60% A-roll / 40% B-roll** **[F]** — the only ratio anyone states.
- **Contrarian and genuinely useful:** OpusClip's own corpus found **only 6.0% of analysed clips use b-roll at all** (Jun 2026). **[E]** — b-roll is rare in the wild, making it a differentiator rather than table stakes.
- **B-roll should lead the word**, appearing slightly *before* the noun is spoken and ending shortly after — not laid over dialogue "like wallpaper."

### A5. Silence removal — the most actionable section

Thresholds by content type (ChatCut, May 2026), detection = below ≈**−35 dB** for longer than:

| Content | Min gap before removal |
|---|---|
| Conversational podcast | 0.8–1.2 s |
| **Solo talking head** | **0.5–0.7 s** (default 0.7) |
| Tutorial / explainer | 0.3–0.5 s |

**The single highest-value finding in this report — a stated *failure threshold*, not a target:**

> "Aim for a cleaned version that's **80–90% of the original duration, not 60–70%**. The deepest cuts read as over-edited; the moderate ones read as professional."
>
> "Aggressive silence removal is the most common tell of an automated edit. If every pause under 0.5 seconds is gone, your speaker sounds like they never breathe and viewers feel the anxiety even if they can't name it."

**Encode as a hard pipeline assertion:** `0.80 ≤ out_duration/in_duration ≤ 0.90`. One line, and it's the cheapest guard against output reading as machine-edited. **[E-adjacent]**

Also: **cut at zero-crossings** to avoid clicks — signal processing, not opinion, non-negotiable **[E]**. **Do not delete all breaths** — duck them instead; breaths are part of speech **[E-adjacent]**. J/L cuts at **one every 3–4 exchanges** — constant offsetting tires, selective reads as craft **[F]**.

**Cutting on the stressed syllable:** no rigorous source exists. Real editor practice, undocumented with data. **[F]**

### A6. Retention editing — and where it now reads as slop

Pattern-interrupt intervals span **4–12 s** across sources (a 3× spread illustrating how soft this is). Zoom specs: **10% punch** for emphasis **[F]**; **progressive zoom 1.5–2%/s** on a talking head, notable because it *substitutes for a cut* in the stimulus budget **[F]**.

**The techniques are not dead — uniform, speech-synchronised, every-N-seconds application of them is the tell.**

The documented Aug 2026 slop signature: **constant auto-zoom locked to speech + word-by-word auto-captions + evenly-spaced whooshes**. SlopDetector (Jun 2026) cites a Kapwing analysis finding ~21% of sampled YouTube Shorts contained AI content, and names the editing tell as tools "automatically applying AI captions, intelligent auto-zooms synchronized to speech, and platform-optimized formatting — creating a formulaic look viewers increasingly associate with low-effort content." **[E-adjacent]**

**Mitigation: place interrupts on *semantic* boundaries** (new claim, new entity, contradiction, number) rather than on a timer.

---

## Part B — Layout vocabulary

**Part B is substantially weaker-sourced than Part A.** There is a real literature on cut cadence; there is **essentially none on layout switching in vertical short-form**. Several questions below have *no published guidance at all* — flagged rather than invented.

Indicator of the gap: vertical accounts for >90% of TikTok views, yet **only ~15% of split-screen tutorials address 9:16 composition directly** (Direct AI, May 2026).

### B1. What each layout signals **[F]**

| Layout | Meaning |
|---|---|
| **Full-screen presenter** | "The claim rests on me." Max parasocial contact, zero evidence on screen. Currently ascendant on IG. |
| **Full-screen b-roll** | "Look at the thing, not me." Max evidentiary weight; presenter recedes to narrator. |
| **Split-screen** | **Equal weight — a comparison or pairing.** Use when both panels matter equally. |
| **PIP** | **Explicit hierarchy — b-roll is subject, presenter is commentary.** |

**Best editorial formulation found, and the rule worth encoding:**

> "The layout should answer one decision first: **what should the viewer compare, follow, or feel?** Don't choose the split style because it looks trendy."

Clean mapping for tech news: **split = comparison** (model A vs B, before/after) · **PIP = presenter annotating evidence** · **full b-roll = evidence speaks for itself** · **full presenter = assertion, stakes, CTA**.

### B2. Switch triggers **[D — synthesised, not sourced]**

The genuine editorial logic: **evidence on screen when the sentence is falsifiable; presenter on screen when the sentence is a judgement.**

### B3. Minimum dwell before switching back — **NO PUBLISHED GUIDANCE EXISTS**

Searched specifically; found nothing. Anyone quoting a layout dwell number is inventing it.

Best proxies: b-roll comprehension floors (detail 1.5–3 s, establishing 2–4 s) **[E]**, and the reorientation-cost argument — a layout change is a *harder* reorientation than a cut within a layout, because the viewer must re-locate the face.

**Derived floor: 2.5 s minimum dwell, 3.5 s for split-screen** (two panels = two things to parse). **[D]**

### B4. How many layout changes per 60 s — **NO DATA**

A real gap, not a search failure. Reasoned from the stimulus budget (30–42 events per 60 s, of which layout changes are the most expensive class) and reorientation fatigue:

**Derived heuristic: 4–8 per 60 s reads intentional; >12 restless; <3 static.** Roughly one per structural beat, not per cut. **[D — encode as a lint check, not a target.]**

The one sourced anchor: layout changes should track **narrative structure**, with turning points every 20–30 s (Retensis) — scaled to 60 s, a major shift every 10–20 s.

### B5. Round PIP — findings are largely negative

- **No published sizing, positioning, or usage convention exists.** Filmora's Jul 2026 PIP guide — the most recent thorough reference — gives mechanics and **explicitly no standard sizes, corner conventions, shape preference, or 9:16 guidance.**
- Round facecams are documented almost entirely as a **livestream/OBS** convention, not an edited-short one.
- Round crop is established as a **TikTok reaction-cam** move, carrying a specific connotation: *informal, second-screen, responding to someone else's content.*

**The connotation risk exceeds the datedness risk.** Round PIP reads *streamer/reaction*, which mismatches authoritative tech-news framing. **Recommend rectangular with rounded corners (~16–24 px radius at 1080 wide)**, reserving round for genuine reaction segments. **[Opinion — clearly unsourced]**

⚠️ **This directly contradicts the plan's assumption that round PIP is a required layout.** Worth revisiting in Unit 6 — see Open Questions.

### B6. Split-screen for 9:16 — one solidly-reasoned convention

**Horizontal split (stacked top/bottom) is correct, and this is arithmetic rather than opinion [E]:** a vertical split of 1080×1920 gives each panel 540×1920 — a 1:3.5 slot that fits essentially no real footage. Stacking gives 1080×960, a 9:8 near-square that crops acceptably from both 16:9 and 9:16 sources. **Side-by-side split is effectively unusable in 9:16.**

**Panel order — derived from sourced safe zones [D]:** platform UI eats the **bottom 12–20%**. So put **the thing that must be read (evidence/chart/screenshot) in the TOP panel and the presenter in the BOTTOM**, where partial occlusion of a face costs nothing.

Ratios 50/50 or 60/40 **[F]** (template-vendor defaults, no performance data).

---

## Recommended pipeline parameters

Genre: talking-head tech/AI news + b-roll, 45–60 s, 9:16, cross-posted Shorts/Reels/TikTok.

```yaml
# ---- GLOBAL STIMULUS BUDGET ----
visual_change_rate:
  target_per_10s: [5, 7]         # cuts, punch-ins, layout swaps, text swaps,
                                 # reveals — NOT just cuts                     [F]
  hard_floor: no 5s block with zero visual change                              [F]

# ---- SHOT LENGTH ----
shot_len_talking_head_s: [3.5, 6.0]   # slower than generic advice: info-dense [E/F]
shot_len_broll_s:        [1.8, 3.5]                                            [E/F]
shot_len_max_static_s:   4.0                                                   [F]
payoff_hold_s:           [3.0, 4.0]                                            [F]

# ---- 60s ARC (three cadence registers) ----
hook   : 0.0 - 3.0s   -> shot_len [0.6, 1.4]  # first cut by 1.5s              [F]
body_a : 3.0 - 24.0s  -> shot_len [2.5, 4.5]
body_b : 24.0 - 36.0s -> shot_len [2.0, 3.5]  # TIGHTEN: 40-60% failure zone   [E]
close  : 36.0 - 60.0s -> shot_len [3.0, 5.0]  # decelerate into payoff         [F]
cadence_variance_min: 0.35   # stdev/mean; guards "predictable by second 8"    [F]

# ---- SILENCE REMOVAL ----
silence_floor_db:     -35
min_gap_to_cut_s:     0.60
keep_pad_ms:          80          # leave breath head/tail; do NOT zero        [E]
cut_at_zero_crossing: true        # non-negotiable                             [E]
ASSERT: 0.80 <= out_duration/in_duration <= 0.90  # <0.80 reads AI-edited      [E]
j_cut_every_n_edits:  [3, 4]                                                   [F]

# ---- B-ROLL ----
a_roll_fraction:       [0.55, 0.65]                                            [F]
broll_lead_word_ms:    [200, 400]   # image arrives BEFORE the noun            [F]
broll_min_on_screen_s: 1.5                                                     [E]
broll_max_on_screen_s: 5.0

# ---- MOTION / INTERRUPTS ----
progressive_zoom_pct_per_s: [1.5, 2.0]   # substitutes for a cut               [F]
punch_in_pct:               10                                                 [F]
interrupt_interval_s:       [4, 8]       # on SEMANTIC boundaries              [F]
ANTI_SLOP: never lock zoom/whoosh to a fixed timer or to every clause.
           Uniform speech-synced auto-zoom + word-by-word captions
           is the documented 2026 tell of low-effort AI content.               [E]

# ---- TEXT ----
text_delay_after_speech_ms: [200, 400]                                         [F]
text_hold_s:                max(1.5, 3.0 + 0.6 * word_count)                   [E]
text_words_max:             6                                                  [F]
safe_zone: top 8%, bottom 20% clear (worst case across 3 platforms)            [E]

# ---- LAYOUT ----
split_orientation:      horizontal_stacked_only  # side-by-side unusable 9:16  [E]
split_ratio:            [0.50/0.50, 0.60/0.40]                                 [F]
split_panel_order:      evidence_TOP / presenter_BOTTOM  # UI clips bottom     [D]
pip_shape:              rounded_rect (~20px @1080w); AVOID circle unless
                        the segment is genuinely reaction/commentary           [D]
pip_width_pct:          [0.28, 0.34]                                           [D]
layout_min_dwell_s:     2.5   (split_stacked: 3.5)                             [D]
layout_changes_per_60s: [4, 8]   warn >12, warn <3                             [D]
layout_trigger: semantic only —
  falsifiable_claim | demo | artifact  -> full_broll or pip_presenter
  comparison | before_after            -> split_stacked
  judgement | stakes | CTA | punchline -> full_presenter
```

---

## Three highest-value takeaways

1. **The `0.80–0.90` duration-ratio assertion** is the cheapest, highest-leverage guard against output reading as machine-edited — the only place a source stated a *failure threshold* rather than a target.
2. **Budget "visual changes," not cuts.** A 1.5%/s progressive zoom spends from the same budget as a cut, so stimulus density is achievable without shredding the A-roll.
3. **Variance is the parameter.** Three independent sources converge on *uniformity* — not speed — as what kills retention and marks automation. An automated pipeline's default failure mode is exactly uniformity, so `cadence_variance_min` should be a first-class output metric.

## Where to stop trusting this document

- Every **[D]** number in Part B is derived here, not from literature. B3, B4, B5 have no published guidance.
- The "2.5 s → 35% completion" figure is unsourced and selection-biased — drop it.
- One cited source (Strategia-X) returned inconsistent date metadata and is single-sourced; its numbers appear nowhere else.
- The session search budget was exhausted partway through Part B, which is why B3–B5 are thin. Strong suspicion: the guidance genuinely doesn't exist, and the answer is to A/B test layout dwell and switch count in the pipeline itself.

## Still outstanding for R3/R5 (search budget exhausted)

- Hook construction, first 1–3 s — patterns that hold in 2026 vs burned out; first-frame specifics
- Caption typography — typeface/weight/size floor/stroke, and authoritative platform safe-area numbers
- Audio — music bed conventions, ducking curves, LUFS targets, commercially usable sources
- Statistics-card presentation conventions
