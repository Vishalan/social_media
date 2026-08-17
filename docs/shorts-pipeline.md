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
| `ai_video` | **nothing concrete to show** | generated cinematic scene — last resort |
| `pageroll` | a URL | held or travelling page view — the fallback |

Types are **capability-gated before the planner sees them**: no URL means no
`pageroll`, no quoted human means `tweet_reveal` is never offered, no local video
model means no `ai_video`. The planner cannot choose something unrenderable.

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

## Measured against the references

Analysis: `docs/reference/2026-08-17-competitor-frame-analysis.md`.

| | One cut every | Median hold |
|---|---|---|
| Grok reference | 2.45s | 1.67s |
| **This pipeline** | **2.55s** | 2.60s |
| Researcher reference | 1.07s | 0.62s |

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
