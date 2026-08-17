# The shorts pipeline

One command produces a finished vertical short from a URL:

```bash
python -m shorts --source https://example.com/article --id my-short
python -m shorts --source https://github.com/owner/repo --id repo-reel
python -m shorts --id my-short --resume            # reuse completed stages
```

Everything runs on the owner's own hardware or subscription. Measured cost per
60-second short: **about 35–45 minutes wall clock and roughly $0.30 of
electricity**, against $4.80–9.00 for the avatar alone on the metered VEED path.

---

## Stages

| Stage | Does | Where |
|---|---|---|
| `load_source` | URL / repo / text → facts | `shorts/sources.py` |
| `write_script` | narration + per-story visual identity | `claude -p` |
| `generate_voice` | cloned voice, chunked, mastered to −14 LUFS | Chatterbox on the 3090 |
| `transcribe_and_align` | word timings, then captions from the SCRIPT | GPU Whisper large-v3 |
| `plan_segments` | 9–14s narration segments | — |
| `fetch_broll` | plan + render a varied b-roll slate | `shorts/broll_director.py` |
| `render_avatar` | lip-sync over real footage, per segment | LatentSync on the 3090 |
| `render_designs` | anchored motion graphics | `claude -p` + HyperFrames |
| `assemble` | spans, layout, captions, mux | `shorts/stages.py` |
| `make_thumbnail` | channel-template cover | `shorts/branding.py` |

Each stage writes artifacts to the run directory, so `--resume` skips completed
work. A failed design no longer costs a 28-minute avatar render.

## The b-roll director

Twelve types. The director chooses one per beat AND produces its payload in a
single call, because they are one decision — choosing `tweet_reveal` is useless
without an author and quote.

| Type | Needs | For |
|---|---|---|
| `highlight` | article body | the source's own sentence, swept word-group by word-group in a phone mockup |
| `annotate` | URL + a phrase | the real page with ONE phrase boxed, everything else dimmed |
| `macro` | URL + an element | extreme push onto one button, badge or label |
| `mechanism` | a described process | a built flow: stages in order, connectors, typewriter result |
| `stats_card` | one figure | counter landing on a number |
| `headline_burst` | a claim | punchy text, built word by word |
| `split_screen` | two comparables | stacked two-panel comparison |
| `cinematic_chart` | comparable numbers | bars growing from a baseline |
| `code_walkthrough` | code or config | editor pane, lines typing in |
| `tweet_reveal` | a named person quoted | social-post card |
| `ai_video` | opt-in + nothing concrete to show | generated scene — **off: see below** |
| `pageroll` | a URL | held or travelling page view — the fallback |

Types are **capability-gated before the planner sees them**: no URL means no
`pageroll`, no quoted human means `tweet_reveal` is never offered. The planner
cannot choose something unrenderable.

`ai_video` needs a second gate, and the distinction matters. LTX-Video 2B runs
fine here (80–98s for a 3s clip) so the capability check passes — but the output
is a blue smear with no recognisable subject, measured across a terse prompt at
30 steps and a long LTX-style description at 40. "Can render" is not "should
render", so it also requires `ai_video_enabled`, which is **off**. The renderer
and its VRAM isolation stay wired for a stronger local model.

Everything except `highlight`, `pageroll`, `annotate`, `macro` and `ai_video`
becomes a HyperFrames brief, so one design system carries one quality bar.

## Quality gates

**Vision review.** Every designed graphic is opened and judged by a vision pass,
then re-rendered once with the specific defect fed back. HyperFrames' own lint
and layout checks passed a card whose hero numeral overlapped its own support
line and a terminal whose block cursor sat on the first letter of a word —
neither is detectable without looking.

**Captions come from the script, not the transcript.** The pipeline transcribes
its own synthesised narration for TIMING; the words are the script's. Trusting
the transcript put "GPT-5.6 sold" and "John Krapidze" on screen.

**Clips are conformed.** Every b-roll clip is forced to its declared duration and
the panel's exact geometry before assembly. Generators return whatever their
content needed, and the assembler places clips at computed offsets.

**The panel is never empty and never frozen.** Between designed graphics the
panel frames one paragraph of the source at a time, highlighted with an accent
bar, striding through the piece so consecutive views differ. It is rendered from
the source text rather than captured from the publisher: the live page put an
Oracle advert and a podcast promo carrying an unrelated headshot into the video,
and no DOM rule reliably separated the article from an embedded transcript. The
evidence types still use the real page, where the point is that the claim is
visible on the publisher's own site.

## Measured against the references

Analysis: `docs/reference/2026-08-17-competitor-frame-analysis.md`.

Measured on the **content panel**, not the whole frame. Whole-frame scene
detection cannot see change confined to the top half, where the continuous
presenter dominates the score — it reported 3 cuts for a build whose panel
turned over 20 times.

| | One change every | Median | Max hold |
|---|---|---|---|
| Grok reference | 2.45s | 1.67s | — |
| **This pipeline** | **2.66s** | 2.44s | 6.12s |
| Researcher reference | 1.07s | 0.62s | — |

The researcher video's ~1s cadence needs full-frame presenter alternation, which
conflicts with the standing rule that the avatar is never full-screen. Grok tempo
is reached inside the split layout.

## Host requirements

On the rendering host: `commoncreed_latentsync` and `commoncreed_chatterbox`
services, the `claude` CLI with the `hyperframes` plugin and
`CLAUDE_CODE_OAUTH_TOKEN`, Node ≥ 22, Chrome, Playwright + Chromium, FFmpeg,
numpy and Pillow. `PEXELS_API_KEY` is optional — stock is skipped without it.

Headless Chrome needs `--no-sandbox --disable-dev-shm-usage` everywhere. Without
the second flag the default 64 MB `/dev/shm` cannot hold a framebuffer, and it
fails as a hang or as `Protocol error (Page.captureScreenshot)` rather than as a
clear error. This has now bitten three separate call sites.

## Known limits

* **Footage is the ceiling on cadence.** 59.25s of usable frontal footage exists;
  a 60s short consumes nearly all of it, so consecutive videos reuse framings.
  The pipeline logs when it reuses rather than looping silently. More filming
  buys more than any code change here.
* **Avatar render is the long pole** — ~25s of compute per second of video at
  1080p, so ~25 minutes for a 60s short.
* **A design can still ship flawed.** After two rejected attempts the vision loop
  ships the clip and logs it, rather than blocking the video.
