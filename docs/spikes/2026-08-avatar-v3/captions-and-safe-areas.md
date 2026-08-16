# Unit 3 — Caption Typography & 9:16 Safe Areas

**Date:** 2026-08-15 · **Covers:** R3 (caption placement/styling), feeds R5 · **Status:** Part A (safe areas) researched; Part B (typography) is convention + derivation, **not** sourced — search budget exhausted

Labels: `[E]` evidence-adjacent (platform doc, published standard, real dataset) · `[F]` folklore/vendor convention · `[D]` derived here

---

## ⚠️ The provenance situation — the most important finding

**No platform officially publishes an organic safe-area pixel spec.** This invalidates essentially every confident table on the internet.

- **YouTube** — official Shorts help page was fetched directly. It specifies *only*: vertical, max 1080p, ≤3 min. **Zero** guidance on safe areas, UI overlay, or text placement. `[E]`
- **Meta** — an official doc exists ("About text overlays and the safe zone for ads in Stories and Reels") but Meta blocks scraping; only the title was retrievable. Note the scope: **ads, not organic.** `[E]` that it exists; contents unverified.
- **TikTok** — spec pages failed to fetch. Unverified.

Every pixel number circulating online traces to **tool-vendor blogs, not platform documentation**. The top ~30 search results are near-certainly AI-generated SEO farms publishing mutually contradictory numbers under 2026 datelines. Treat them as **one weak, self-referential source**, not many.

---

## Part A — Safe areas

### A1. The contradictions, left intact

| Source | Date | TikTok (T/B/L/R) | IG Reels | Shorts |
|---|---|---|---|---|
| motionpilot | **2026-07-23** | — | top 10%, bottom 20%, right 10–12% | — |
| behaviour.digital | 2026-05-08 | — | 14%/35%/6% = **269/672/65** | — |
| postplanify | upd 2026-04-07 | 108/320/60/120 | 210/310/–/84 | 120/300/–/96 |
| kreatli | 2026-01-05 | 130/250/60/60 | 108/320/60/60 | avoid bottom 10–15% |
| ad-spec aggregate | 2026 | **130/484/44/140** | — | 160/320/–/150 |

**TikTok bottom margin ranges 250 px to 484 px — a 2× disagreement on the single most important number.** Nobody measured; they copied each other with drift.

The most credible source is the **most recent and least confident**: motionpilot explicitly discloses it did no empirical measurement, says *"treat the margins as directional rather than gospel,"* and makes the structural point everyone else misses — **the safe area is dynamic; your own caption length changes it.** `[E]` for honest methodology disclosure.

### A2. The "universal safe zone" is arithmetically broken `[D]`

Vendors converge on **"900×1400 centered."** On 1080×1920 that means 90 px sides and **260 px top and bottom**. Those same vendors publish TikTok bottom margins of 320–484 px. **Their universal zone violates their own per-platform numbers.** Do not use it.

The real intersection is the **max of each margin**, and it is **strongly asymmetric — bottom ≫ top**.

### A3. Recommended parameters `[D]`

```python
FRAME = (1080, 1920)

# TIER 1 — CONSERVATIVE. Survives all 3 platforms + ads placement.
SAFE_STRICT  = dict(top=280, bottom=500, left=70, right=180)

# TIER 2 — ORGANIC-REALISTIC. Recommended default.
SAFE_ORGANIC = dict(top=200, bottom=420, left=64, right=160)
#   usable box: x 64..920 (856w), y 200..1500 (1300h)

# Per-destination variants:
TIKTOK = dict(top=140, bottom=480, left=60, right=180)  # widest bottom + rail
REELS  = dict(top=270, bottom=400, left=65, right=140)  # widest TOP (Meta 14%)
SHORTS = dict(top=180, bottom=400, left=60, right=150)
# Meta ADS only: bottom=672 (35%) — CTA button. Ignore for organic.
```

Binding constraints: **top set by Instagram**, **bottom and right set by TikTok**.

### A4. Claimed 2025–26 changes — all `[F]`, none citing a changelog

- **Meta unified Stories + Reels into one 9:16 safe zone (~Mar 2026)** and moved from pixels to **percentage-based** margins to cover 20+ phone aspect ratios; Stories bottom went 20% → 35%. Most consequential claim, plausible, directionally consistent across two sources. Moderate confidence.
- Meta Ads Manager gained a **"Safe zone guardrail"** preview toggle that shades UI-covered regions. **If real, this is the closest thing to an authoritative measuring instrument available** — see Next Actions.
- TikTok "Add to Playlist" grew the right rail ~20 px; IG audio bar +~50 px; Shorts subscribe button +~30%. All weak.

**Percentages now beat pixels.** Store margins as fractions of frame height/width, not absolute px — that also makes 720p and 1080p renders agree.

### A5. Where captions actually sit `[D]`

**Centered-lower-third is obsolete.** A classic lower third lands around y≈1400–1600 — inside every platform's bottom danger zone.

```python
CAPTION_BOTTOM_MAX_Y         = 1420   # strict  (1920 - 500)
CAPTION_BOTTOM_MAX_Y_ORGANIC = 1500
CAPTION_BAND_Y               = (1150, 1400)   # ≈60–73% of frame height
MAX_TEXT_WIDTH_PX            = 830    # NOT 1080 — the right rail binds
```

**Anchor the caption block by its bottom edge and grow upward.** Line count isn't known until render in an automated pipeline; bottom-anchoring keeps the block stable as it varies.

### A6. Platform auto-captions vs burned-in — a real conflict `[F]`, high practical importance

Multiple sources claim platform auto-captions are now **default-on**. If true, this is the biggest risk to a burn-in pipeline: the viewer sees **two caption tracks stacked** — yours, and the platform's rendering in the bottom UI band, exactly where a naive pipeline puts its own.

Mitigations:
1. Keep burned-in captions **above y=1400**, clear of where platform captions render.
2. On upload, disable auto-captions / omit a caption track where the API allows (YouTube Data API permits this; TikTok and IG less so).
3. Consider a per-platform `burn_captions: bool` — some operators disable burn-in for Shorts specifically and rely on YouTube's own, which are least intrusive and indexed for search.

**Unverified — flag as the #1 thing to check manually.**

---

## Part B — Typography

> **Honesty flag from the researcher:** primary sources were not reached for this section (search + fetch budgets exhausted). What follows is established convention plus derivation. **None of these numbers carry a verified 2026 citation.** Treat as a starting parameter set to validate, not as findings.

### B1. Typefaces — the cliché stack is a liability

**Reads as "AI slop" in 2026** `[F]`:
- **Montserrat ExtraBold/Black**, Impact-alikes ("TheBoldFont") — the Hormozi look, maximally saturated
- **Komika Axis** — older MrBeast/gaming-clip look, dated
- **Poppins Bold, Bebas Neue, Anton** — heavily overused

**The specific combination that fingerprints automated content:** Montserrat ExtraBold + all-caps + yellow/green word highlight + scale-pop. That is the Submagic/Opus Clip default stack, and audiences pattern-match it to low-effort AI.

**Less-fingerprinted alternatives** (all SIL OFL, free for commercial use — matters for an automated pipeline) `[D]`: **Inter** (Bold/ExtraBold), **Figtree**, **Outfit**, **Sora**, **Archivo/Archivo Expanded**, **Instrument Sans**, **Geist**.

**Pin font files in-repo** — do not rely on system fonts, or renders will silently differ between the dev machine and the 3090 box.

*Note for the Vesper workstream:* the bold-geometric-sans convention actively fights horror branding. A condensed grotesque or high-contrast serif at lower size, bone `#E8E2D4` on near-black, would differentiate far more than font choice usually does.

### B2–B4. Size, stroke, highlight `[F]`/`[D]`

```python
FONT_SIZE_PX      = 72        # 3.75% of frame height; range 58–96 (3.0–5.0%)
FONT_WEIGHT       = 700       # 700–800; avoid 900 (the cliché weight)
LINE_HEIGHT       = 1.15
LETTER_SPACING    = -0.01     # em
MAX_TEXT_WIDTH_PX = 830

STROKE_WIDTH_PX = 6           # ~8% of font size; round joins (miter spikes on bold geometrics)
STROKE_COLOR    = "#000000"
SHADOW = dict(dx=0, dy=4, blur=12, color="#000000", opacity=0.55)
# Fallback: semi-transparent plate (#000 @45–60%, radius 12, pad 24)
# enabled conditionally when the background is busy/low-contrast — see B8.

HIGHLIGHT_ENABLED = True
HIGHLIGHT_COLOR   = "#5C9BFF"  # brand token, NOT yellow/lime
HIGHLIGHT_SCALE   = 1.06       # NOT 1.15–1.25
HIGHLIGHT_ANIM_MS = 90
```

**Is word-highlighting burned out?** In its loud form, largely yes `[F]`. The tell is specifically **`#FFFF00`/`#00FF00` + 1.2× scale-pop + all-caps Montserrat**. The *underlying mechanic* — subtle emphasis tracking the spoken word — still aids readability. Keep the tracking, drop the pop to ≤1.06, use a brand colour. Retains function, sheds the fingerprint.

Express sizes as **% of height**, and normalise on **cap height** rather than point size if the family changes, or apparent size will jump.

### B5–B7. Cue structure and case

```python
MAX_WORDS_ON_SCREEN = 4       # 3–5
MAX_LINES           = 2       # 1 preferred, never 3
MAX_CHARS_PER_LINE  = 24
MIN_CUE_DURATION_MS = 900
MAX_CUE_DURATION_MS = 3000
```

**Phrase-timed blocks with word-level highlighting inside them** beats pure word-by-word, which forces constant re-fixation and destroys reading rhythm `[F]`. No credible A/B data exists either way.

**All-caps:** legibility research is old, consistent, and against it — caps removes ascender/descender word-shape cues and slows reading `[E]` — but that research concerns paragraphs, not 3-word bursts, so the penalty is small here. **Recommend sentence/Title case anyway:** costs nothing legibility-wise and all-caps is part of the cliché fingerprint. Reserve caps for a 1–2 word emphasis beat.

### B8. Accessibility — the only genuinely evidence-backed numbers

| Spec | Value | Source |
|---|---|---|
| Contrast, normal text | 4.5:1 | WCAG 2.2 SC 1.4.3 `[E]` |
| **Contrast, large text** (≥24 px, or ≥18.66 px bold) | **3:1** | WCAG 2.2 `[E]` |
| Reading speed, adult | 20 CPS | Netflix TTSG `[E]` |
| Reading speed | 160–180 wpm | BBC Subtitle Guidelines `[E]` |
| Max chars/line | 42 (Netflix) / 37 (BBC) | `[E]` |
| Max lines | 2 | Netflix + BBC `[E]` |
| Min / max cue duration | 833 ms / 7 s | Netflix TTSG `[E]` |

All caption text at 72 px is "large text", so **3:1 is binding** — but against *moving video*, worst-case frame. Black stroke at 6 px effectively guarantees it, which is the real reason stroke is convention.

**Automatable check:** sample luminance under each caption across its frames; if min contrast < 3:1, enable the background plate.

**Honest tension:** 4 words in 900 ms ≈ 267 wpm, which **exceeds BBC's 180 wpm ceiling**. That is inherent to short-form — these captions are an emphasis layer over audible speech, not a substitute for it. Standards-compliant captions would be a separate track.

### B9. "Captions improve retention" — mostly laundered marketing `[F]`

- **"85% of Facebook video watched on mute"** — a 2016 Digiday figure, never an official Meta stat, and **contradicted by Meta itself** at the time.
- **"Captions increase view time 12%"** — Facebook internal 2016, no methodology, no n.
- **"80% more likely to watch to completion"** — Verizon/Publicis 2019, a survey of viewer *self-report*, not measured watch time.
- **Contrary:** TikTok is sound-first with far higher sound-on rates than Facebook feed — undercutting the mute argument for the very platform most people cite it for.

**Honest position:** captions on short-form are near-universal convention with essentially **no public credible causal evidence of retention lift**. Worth doing for accessibility, sound-off viewers, and comprehension of TTS narration — but do not model a specific % lift, and treat any vendor quoting one as marketing.

---

## Highest-value next actions

1. **Meta Ads Manager "Safe zone guardrail" preview** — upload one 1080×1920 frame with a pixel ruler burned in; screenshot the shaded overlay. Yields Meta's *actual* current numbers and beats every source above. **~10 minutes, and it is the single highest-value action in this document.**
2. **Ruler-frame test post** on each platform (unlisted/private), screenshot on a real device, measure. Gives ground truth for all three, re-runnable when UI drifts.
3. **Verify whether platform auto-captions are default-on** — the burn-in collision (A6) is the biggest concrete risk to the pipeline.
4. Re-run Part B in a fresh session with search budget; it is convention, not findings.

**Store margins as percentages with a `last_verified` date in `config/settings.py`.** Platform UI drift is the entire problem here, and a stale hardcoded pixel value is how this breaks silently.
