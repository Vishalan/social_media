# Frame-by-frame analysis: two reference shorts

**Analysed 2026-08-17.** Sources in `assets/input_media/reference_other_youtubers/`:

| Video | Length | Format | Cuts |
|---|---|---|---|
| *Elon Musk's xAI just launched Grok Bot!* | 51.5s | 720×1280 @24fps | **21** |
| *A researcher left OpenAI to turn thoughts into text* | 110.7s | 720×1280 @30fps | **103** |

Frames sampled at 1.5s (Grok) and 2.5s (researcher), plus scene-change detection
at threshold 0.25 for cut timing.

---

## 1. The finding that matters most: cut rhythm

| | Cuts | One cut every | Median hold | Holds under 2s |
|---|---|---|---|---|
| Grok Bot | 21 / 51s | **2.45s** | 1.67s | 55% |
| Researcher | 103 / 111s | **1.07s** | **0.62s** | **83%** |
| Ours, before the director (`skills-v5`) | 1 / 64s | 64s | — | 0% |
| **Ours, with the director (`x-full`)** | **21 / 59s** | **2.79s** | — | — |

The researcher video changes what is on screen roughly **once per second**, and
four fifths of its shots are held under two seconds.

`skills-v5` changed once in 64 seconds. That video used two long page-roll
clips, so the frame was visually one scene start to finish.

The b-roll director closes most of this gap without any layout change: eight
distinct content placements in `x-full` produce **21 detected cuts, one every
2.79s** — which is the Grok video's rhythm (2.45s), not the researcher's
(1.07s). So the structural claim was too strong. Varying the CONTENT often
enough registers as cutting even with a constant presenter panel.

What remains out of reach is the researcher video's ~1s cadence, and that part
IS structural: at 0.6s median holds the presenter panel would be the only stable
element on screen, which is a different kind of video.

**The references do not use a split layout at all.** The presenter appears
FULL-FRAME (researcher frames at 92.5s and 100s are the presenter filling the
whole vertical frame), alternating with full-frame content. That is what makes
a cut available every second.

This directly contradicts the earlier instruction to never show the avatar
full-screen and to use half-and-half only. Both cannot hold: half-and-half
forbids the cut rhythm these videos are built on. That is a call for the owner,
not something to quietly resolve — see Open Questions.

## 2. Content vocabulary

Nine distinct treatments, catalogued from the frames:

**a. Real product UI at varying zoom.** The Grok video shows the actual Grok Bot
interface — chat threads, member lists, settings panes — but the ZOOM LEVEL
varies enormously. Wide views of a full conversation (t=18s), then a macro push
onto one button, "Learn from demonstration", with the edges thrown out of focus
(t=22.5–24s). The variation in scale is the dynamism; the underlying asset is a
static screenshot.

**b. Source documents with the key figure highlighted.** At t=42.5s the
researcher video shows the actual *New England Journal of Medicine* page, body
text greyed, with **97.5%** boxed and the surrounding sentence emphasised. This
is the "highlight the text worth reading" technique, applied to a primary
source rather than a news article.

**c. Bespoke animated mechanism diagrams.** At t=5–10s the researcher video
builds an explainer on white: the company's real `conduit` wordmark, then a
brain glyph, then brain → signal squiggle → decoder box, ending with a
TYPEWRITER effect spelling `i need more coff|` with a live cursor. Purpose-built
motion graphics that explain how the product works, using the company's own
logo.

**d. AI-generated cinematic video.** Heavily used in the researcher video: a
wireframe human figure on a grid, a noir-lit man at a desk, a figure in a dark
corridor, hands cupping light. Consistent moody grade, shallow depth of field.
This is generated footage, not stock — it is too on-topic to be a library
match.

**e. Typographic cards over footage.** "IT'S YOUR HANDS." set over the
hands-and-light image; "Actual **Feasibility and Accuracy** today" in mixed
weights over the wireframe figure. Type and image composited, not sequential.

**f. Annotation boxes drawn onto UI.** A rectangle outline around "Cursor Ultra"
on the real pricing card (Grok, t=36s) to point at one element.

**g. Device-frame mockups.** A desktop screenshot placed inside a rounded
window on a gradient background (Grok, t=40.5s), rather than shown flat.

**h. Split screen — but only as an opener.** Both videos open on a split:
subject footage or product hero image on top, presenter below. Neither sustains
it. It is an establishing shot, not a layout.

**i. Product pricing and feature cards** lifted directly from the source page,
shown large enough to read.

## 3. Captions

Consistent across both videos and notably restrained:

- **2–4 words per cue**, never a full sentence
- Small — roughly 3.5% of frame height, far smaller than ours
- White, medium weight, on a **black rounded pill** at ~70% opacity
- Bottom-centre, around 78–80% of frame height
- No word-by-word colour highlighting, no karaoke, no bounce

Our captions are larger and carry more words per cue. Theirs are deliberately
quiet — the content panel is doing the talking.

## 4. What the openings do

Both hook the same way: the strongest available VISUAL in the first frame, with
the presenter secondary.

- Grok: Elon Musk speaking (recognisable face, borrowed authority) top, presenter bottom
- Researcher: the product hero image — a woman wearing the headset — top, presenter bottom

Neither opens on the presenter alone. Neither opens on a webpage.

---

## Gaps against our current pipeline

| # | Gap | Severity |
|---|---|---|
| 1 | **Cut rhythm.** Was 1 cut/64s; the director brought it to one per 2.79s, matching the Grok reference. Still 2.6× slower than the researcher video's 1.07s. | Was critical, now moderate |
| 2 | **No AI-generated cinematic footage.** A whole category we do not produce. The 3090 and the `ai_video` generator exist but are unwired. | High |
| 3 | **No zoom variation.** Our page-roll travels at one scale; theirs pushes from wide to macro on a single element. | High |
| 4 | **No mechanism diagrams.** We make stat cards and lockups, not "how it works" explainers with the source's own marks. | High |
| 5 | **No annotation on UI.** We show a page; we never point at the thing being discussed. | Medium |
| 6 | **Captions too large, too many words.** | Low, easy |
| 7 | **Split used throughout rather than as an opener.** | Blocked on the owner's call |

## Open questions for the owner

1. **Half-and-half versus the fastest cutting.** Partly reconciled: the director
   reached 2.79s/cut inside the split layout, so these are not as exclusive as
   first stated. But the researcher video's 0.62s median holds do require
   full-frame alternation. Is Grok-tempo (2.5s) enough, or do you want the
   faster cadence and the full-frame presenter it implies?
2. **AI-generated footage.** A large share of the researcher video's b-roll is
   generated cinematic video. Producing it locally on the 3090 is possible
   (`ai_video` via ComfyUI is already scaffolded) but adds render time and is a
   different quality risk. Worth pursuing?
