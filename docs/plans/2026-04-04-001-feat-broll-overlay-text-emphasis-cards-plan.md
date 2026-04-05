---
title: "feat: Bold overlay text on b-roll + mid-body emphasis cards"
type: feat
status: active
date: 2026-04-04
origin: User feedback comparing pipeline output to reference video (Axios attack)
---

# feat: Bold overlay text on b-roll + mid-body emphasis cards

## Overview

Two improvements to close the remaining quality gap with the reference video:

1. **Bold title overlay on browser b-roll** — Large semi-transparent text (like "AXIOS JUST GOT ATTACKED") overlaid on the first browser segment. Massively increases perceived production value with near-zero cost.

2. **Mid-body emphasis cards** — 1-2 styled transition cards ("The Fix", "Why It Matters") inserted at natural break points during the body. These create the visual rhythm of the reference video's "speaker breather" moments without requiring additional avatar generation.

## Problem Frame

The reference video alternates between immersive full-screen browser screenshots, large bold title text, and brief speaker appearances. Our pipeline now does full-screen b-roll (good) but the segments blend together without visual punctuation — no title overlay, no transition beats. The result feels monotone compared to the reference.

## Requirements Trace

- R1. Browser b-roll segments can carry large overlay text (topic title or key phrase) rendered semi-transparent over the Ken Burns clip
- R2. Timeline planner can insert "emphasis" segments at transition points (1-2 per video) — styled dark cards with a single large phrase that creates a visual pause
- R3. The emphasis card style is distinct from `headline_burst` — minimal, dark background, single centered phrase in white, subtle accent (reference: "The Fix", "What Happened", "Why It Matters")

## Scope Boundaries

- No changes to avatar generation or timing (speaker mid-body would require longer avatar clips — deferred to when fal.ai supports duration param or cost drops)
- No changes to stats_card or stock_video generators
- No changes to voiceover or caption styling

## Key Technical Decisions

- **Overlay text via FFmpeg drawtext on browser clips** — applied inside `_render_browser_clip()` when the segment carries an `overlay_text` field. Cheaper and more reliable than Pillow overlay since the clip is already being processed by FFmpeg for Ken Burns.
- **Emphasis cards as a new segment type "emphasis"** — not reusing `headline_burst` because the visual style is deliberately different (dark/minimal vs flat bold colors). Rendered via Pillow like headline_burst but with a single-phrase centered design.
- **Timeline planner controls placement** — Claude Haiku decides where emphasis cards go based on script content, so they appear at natural topic transitions.

## Implementation Units

- [ ] **Unit 1: Bold overlay text on browser b-roll segments**

**Goal:** Browser segments can carry optional overlay text that renders as large semi-transparent text over the Ken Burns clip.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Modify: `scripts/broll_gen/browser_visit.py`

**Approach:**
- Add `overlay_text` field to `_TIMELINE_SCHEMA` segment items (optional string, ≤30 chars)
- Update `_TIMELINE_SYSTEM_PROMPT` to instruct Claude: "For the FIRST browser segment, add an `overlay_text` field with a short punchy title (2-5 words, ALL CAPS) summarizing the topic. Only on the first 1-2 browser segments."
- Update `_render_browser_clip()` to accept an optional `overlay_text` param. When present, add a FFmpeg drawtext filter AFTER the zoompan filter: large bold text (fontsize ~100), centered, semi-transparent white with dark shadow, positioned at center-bottom (y=h*0.6). Use fontcolor alpha for the semi-transparency: `fontcolor=white@0.7` with `shadowcolor=black@0.9:shadowx=4:shadowy=4`.
- Update `_render_all_segments()` to pass `overlay_text` from the segment dict to `_render_browser_clip()`.

**Patterns to follow:**
- Existing `_render_browser_clip()` FFmpeg filter chain (zoompan → setpts)
- `video_edit/video_editor.py` `_CAPTION_FONT_FFMPEG` pattern for font handling

**Verification:**
- A smoke run where the first browser segment has large overlay text visible in the output

---

- [ ] **Unit 2: Emphasis card segment type**

**Goal:** New "emphasis" segment type — a dark minimal card with a single centered phrase, used as a visual transition beat mid-body.

**Requirements:** R2, R3

**Dependencies:** None

**Files:**
- Modify: `scripts/broll_gen/browser_visit.py`
- Create: `scripts/broll_gen/emphasis_card.py`

**Approach:**

*New file `emphasis_card.py`:*
- Single function: `async def render_emphasis_clip(phrase: str, duration_s: float, output_path: str, tmp_dir: Path) -> None`
- Renders frames using Pillow: dark background (near-black `(12, 12, 20)`), single centered phrase in white, large font (~120px), thin accent line above text (indigo `(99, 102, 241)`), subtle fade-in (8 frames)
- Frame rendering + FFmpeg concat pattern identical to `render_lines_clip` in `headline_burst.py` but simpler (single phrase, no cycling colors)
- Keep the visual minimal — this is a "pause" moment, not a splash card

*Changes to `browser_visit.py`:*
- Add `"emphasis"` to `_TIMELINE_SCHEMA` segment type enum
- Add `"text"` field to schema (string, required for emphasis type, ≤20 chars)
- Update `_TIMELINE_SYSTEM_PROMPT`: "emphasis: a dark minimal transition card with a single short phrase (2-4 words). Use at transition points between topics. Max 1-2 per video. Examples: 'THE FIX', 'WHY IT MATTERS', 'WHAT HAPPENED'."
- Add `elif t == "emphasis":` branch in `_render_all_segments()` that calls `render_emphasis_clip(seg["text"], per_segment_s, clip_path, seg_tmp)`

**Patterns to follow:**
- `broll_gen/headline_burst.py` `render_lines_clip()` — frame rendering + FFmpeg concat pattern
- `broll_gen/headline_burst.py` `_try_font()` — font loading pattern

**Verification:**
- A smoke run produces at least one dark emphasis card visible in the output video at a natural transition point
