# Unit 3 — Editing Grammar Research, Part 2

**Date:** 2026-08-16 · **Covers:** hooks, caption typography + safe areas, audio, stat cards
**Companion to:** `editing-grammar.md` (cut cadence + layout vocabulary, 2026-08-15)

Confidence tags, same scheme as Part 1:
**[E]** evidence-adjacent — dataset, methodology, platform docs, or a published standard ·
**[F]** folklore / vendor convention — widely repeated, unsourced ·
**[D]** derived here from adjacent constraints ·
**[X]** traced and found to be fabricated

---

## ⚠️ Read this first — the search space for hook data is actively poisoned

Part 1 warned that cadence guidance was vendor SEO. Hook guidance is worse: a large share of
"2026 hook statistics" trace to AI-generated SEO farms that **invent studies with plausible
names and sample sizes**. Each of the following was chased to a primary source and failed:

| Claim | Appears on | Status |
|---|---|---|
| "Tubular Labs 2025 analysis of 50M short-form videos; scroll-past 62%→78%" | greenfroglabs + derivatives | **[X]** No such publication. Tubular's real 2025 output is share-of-views (77% of global YouTube views from sub-60s video). |
| "Meta 2025 Attention Study, 12M Reels impressions, eye-tracking, users decide in 1.3s" | greenfroglabs, aggregators | **[X]** Untraceable. The *real* Meta/Realeyes study used **16,835 impressions, >300 participants per placement** — three orders of magnitude smaller — and reports no 1.3s figure. |
| "TikTok Creator Digest 2025: hook lifespan fell 8 weeks → 3.5 weeks" | hypenest.ai, greenfroglabs | **[X]** No such TikTok publication. |
| "Paddy Galloway found VvSA 70–90% optimal, <60% collapses" | humbleandbrag, shortimize | **[X]** Real study, invented numbers. Galloway's actual 3.3B-view study (33 channels, 5,400 Shorts, Apr 2023) gives no VvSA thresholds — only "make your first second really punchy." |
| "hook in first 2s → +19% retention"; "67% decide within 3s"; "70–85% retention → 2.2x views"; "+58% retention on faceless Shorts with a consistent AI avatar"; "front-load premise in 2s → +38% swipe-through" | conbersa, aibrify, virvid, autofaceless, joyspace, later | **[X]** No methodology, no n, no primary source anywhere. |

One recycled figure is real but badly mislabelled: **"1.7 seconds to form an impression"** is a
genuine **Facebook IQ mobile-feed study from 2016**, not new research. Later restates it as
current ([Later, 15 Apr 2026](https://later.com/blog/scroll-stopping-content/)). **[E, but ten years old]**

**Do not encode any [X] number as a pipeline threshold.**

---

## 1. Hook construction, first 1–3 seconds

### 1.1 Platform metric definitions *are* the swipe-away windows — the hardest evidence available

| Platform | Hook metric | Window | Source |
|---|---|---|---|
| **TikTok** | 2-second video views ÷ impressions (**2sVTR**) | **2.0 s** | TikTok/Vidmob joint study |
| **Meta / Reels** | 3-second video plays ÷ impressions; **Skip Rate** = % skipping within first 3 s | **3.0 s** | Instagram, Aug 2025 |
| **YouTube Shorts** | Viewed vs Swiped Away; Engaged Views | **undisclosed** | YouTube Help |

**[E]** Instagram added Skip Rate and a Reels retention curve on **24 Aug 2025**, replacing View
Rate. Instagram's own wording: *"a high skip rate means that people didn't find the opening of
your Reel engaging"*; on the retention chart, *"the flatter the line, the more engaged your
audience is."*
[socialmediatoday, 24 Aug 2025](https://www.socialmediatoday.com/news/instagram-adds-retention-insights-reels/758464/)

**[E]** There is **no official Instagram skip-rate benchmark**. Metricool states it plainly:
*"there is no official Instagram source (so far) on what percentage equals good performance."*
[Metricool, 4 Feb 2026](https://metricool.com/instagram-reel-analytics/)

**[E]** YouTube changed Shorts view counting on **31 Mar 2025**: a view counts when a Short
*starts to play or replay*, with **no minimum watch time**. Monetization runs off the separate
**Engaged Views** metric. YouTube has **never published the engaged-view second threshold**.
[YouTube Help, Mar 2025](https://support.google.com/youtube/thread/333869549/a-change-to-how-we-count-views-on-shorts)

**[E]** Cross-platform hook-rate comparison is therefore **invalid** — TikTok measures at 2 s,
Meta at 3 s. Never average them.

**[D] The binding constraint:** ship one master cut built to the **tightest** gate. The verbal
hook must be **complete and the value proposition legible by 2.0 s**; seconds 2.0–3.0 *confirm*,
never *introduce*. Designing to 3 s fails TikTok's gate on every upload.

### 1.2 Hook-rate benchmark bands (paid, cold traffic)

**[E]** [Spark UGC, 21 Jul 2026](https://www.sparkugc.com/resources/hook-rate-benchmarks-2026) —
aggregates a Ryze 500M+ impression panel, Vaizle, MHI Growth Engine; measured after ≥2,000
impressions on cold prospecting.

- **Meta (3 s plays ÷ impressions):** <15% dead on arrival · 15–20% recut · 20–25% workable ·
  25–35% good · 35–45% elite
- **TikTok (2 s views ÷ impressions):** <20% weak · 20–30% average · 30–40% good · 40%+ excellent

**[E]** Corroborated by Pixis (real adtech vendor): strong hook rate 2026 is **>30%, top
performers 40–50%**.
[Pixis, 25 Mar 2026](https://pixis.ai/blog/ugc-in-2026-whats-working-whats-stale-and-how-to-refresh-your-hook-library/)

⚠️ **These are paid ads on cold traffic.** Organic Shorts/Reels from a warm audience run
materially higher. Use them as **relative** movement detectors across your own variants, never
as absolute targets.

### 1.3 Visual / verbal / text hook — the three channels

**VISUAL — [E], and it directly validates this format.**
Best evidence found: **Vidmob × TikTok "Science of the Hook"** — **1,678 ads, 7.3 billion
impressions, 1 Jan – 15 Oct 2023**, computer-vision-tagged attributes regressed against
2sVTR/6sVTR/brand lift. [vidmob.com](https://vidmob.com/resource/tiktok-hook-analysis)

| Element | Measured effect |
|---|---|
| **Direct-to-camera / talking-head framing** | **+14% 2sVTR**, hooking power **+50%** |
| Everyday person (not celebrity) | **1.7× more likely to hook** |
| Celebrity talent | **−13% 6 s view-through** |
| Creator whose category matches content | **1.5× more likely to hook** |
| Shot outdoors | **−26% 6 s view-through** |
| **Logo shown alone** | **−14% 6sVTR** |
| Successful hook overall | 2× engagement, +43% purchase intent |

A talking head shot direct-to-camera is the **highest-hooking visual open TikTok has measured**,
beating celebrity and production value. Ads-side and 2023 — treat direction as robust, magnitude
as indicative.

**[E] Production quality does not predict retention.** *"Delving Deep into Engagement Prediction
of Short Videos"* (Li et al., **ECCV 2024**, 90,000 real Snapchat UGC videos): *"Mean Opinion
Scores from previous video quality assessment datasets do not strongly correlate with video
engagement levels."* [arXiv 2410.00289](https://arxiv.org/abs/2410.00289)
→ Do not spend render budget on visual fidelity expecting a retention return.

**VERBAL — [E] with real caveats.**
[The Content Labs, 20 Apr 2026](https://thecontentlabs.app/blog/what-goes-viral-in-2026-data-study)
— **3,997 videos, 109 creators, Jun 2025 – Apr 2026, 53% Reels / 47% TikTok**, each tagged by
hook archetype.

- **Hot Take** and **Investigator** hooks: **~140,000 average views**
- **Story** hooks opening "So the other day…": **7,127 average views — ~20× worse**
- Guidance: *"Start in the middle of the take, not at the beginning of the story."* Explicitly
  avoid **"So basically"** and **"Here's what happened."**

**[D] Caveat:** observational, not randomised. The same study's 31× duration gap (90 s+ =
170,228 views vs 0–15 s = 5,406) is almost certainly confounded by creator size — bigger
creators make longer videos. The **archetype** comparison is more credible than the duration
comparison because archetype varies *within* creators. Their line *"the algorithm decides within
the first 1.5 seconds"* is **[F]**, unsourced.

**[F] "You have one second."** Jenny Hoyos, on YouTube's own blog alongside Shorts product lead
Todd Sherman: *"I really do think you have one second to hook someone, especially on Shorts."*
[blog.youtube, 28 Jan 2025](https://blog.youtube/creator-and-artist-stories/youtube-shorts-deep-dive/)
Highest-authority *statement* on Shorts hook timing, but expert opinion, not measurement. Note
the venue published it without contradiction.

**TEXT — evidence is genuinely absent.**
**No controlled study on burned-in title cards in the opening seconds was found.** Everything
specific in circulation ("4–7 words, high contrast, top/bottom safe zones") is **[F]** from AI
content farms. What *is* defensible: **[D]** all three platforms autoplay muted on some
surfaces, so a text hook is the only channel guaranteed to survive a sound-off impression. That
is a **robustness** argument, not a measured lift. Do not claim otherwise.

### 1.4 What is burned out in 2026

**[E]** Pixis (25 Mar 2026), based on client testing including BFCM 2025:

**Dead:**
- **Ring-light testimonial** — *"Audiences have learned to pattern-match this format as an ad
  within the first half-second."* Note the detection latency: **0.5 s, faster than your hook can
  finish.**
- **Forced-enthusiasm demo** — retired phrases: *"this changed my life," "I was skeptical but,"
  "you need to try this," "obsessed."*
- **Talking-head value list** — *"Opening with a list signals that what follows is a commercial,
  not a conversation."* ← **directly relevant.** "3 AI tools you need" is named as burned, and it
  is this niche's default format.
- **Vague before/after** — audiences pre-discount unspecified transformation claims.

**Still working:** hot take / contrarian · **scenario hook** (open mid-scene) · reaction ·
third-person social proof · **direct diagnostic** ("If your X drops off at Y, here's why").
Pixis reports scenario hooks consistently beating direct testimonial opens on ROAS.

**[E] Fatigue cycle: ~10 days** for paid creative (peak days 1–3, warning 4–7, 30–50% CTR drop by
days 8–10). Standard fatigue trigger is a **15–20% hook-rate drop against a 7-day rolling
baseline**.

**[F] — and this matters:** the specific claims that *"Stop scrolling," "Nobody is talking about
this," "Wait for it,"* and *"POV:"* are burned out have **zero measurement behind them**. The
*mechanism* (audiences pattern-match ad formats in ~0.5 s) is evidenced; the *phrase blacklist*
is not.

**[D] Heuristic that survives the uncertainty:** don't maintain a static banned-phrase list.
Treat hook templates as **depreciating assets** — track hook rate per template against a rolling
7-day baseline and auto-retire any template falling >15% below its own trailing mean.

### 1.5 The first frame — the honest answer is "almost no evidence"

**[D] Frame 0 has no thumbnail role in-feed.** Shorts, Reels and TikTok all autoplay in-feed. The
cover/thumbnail is a **profile-grid, Explore and Search** asset, not a feed asset. "The first
frame is your thumbnail" is structurally wrong for the surface where distribution is decided.
Metricool's 2026 Reels guide recommends custom covers **for grid consistency and branding**, not
retention. [Metricool, 22 Jun 2026](https://metricool.com/instagram-reels-guide/)

**[E] Indirect support for a face at the open** comes only from Vidmob's direct-to-camera finding
— which is about framing style *across the hook window*, not literally frame 0.

**No evidence found for:** starting mid-motion vs static · face vs text vs b-roll on the opening
frame · hard cut at frame 0 vs held frame. The parameter "first frame must contain a human face
occupying >25% of frame" has **no published support**. It is a reasonable prior given Vidmob, but
it is a hypothesis to A/B test, not a finding.

### 1.6 Timing granularity

**No study isolates 1 s vs 2 s vs 3 s hook length.** The entire hook-length literature is **[F]**.

Defensible numbers only:
- **[E] 2.0 s** — TikTok's measurement boundary. Hard constraint.
- **[E] 3.0 s** — Meta's measurement boundary. Hard constraint.
- **[F] 1.5 s** — "first 1.5 s to stop the scroll; pattern change every 1–2 s; loop every 5–8 s"
  ([Shortimize, 20 Jan 2026](https://www.shortimize.com/blog/youtube-shorts-retention-rate)).
  Shortimize is candid that this is *"observed patterns from client accounts — not published
  research studies,"* and explicitly refuses to publish a benchmark number.
- **[F] 1–2 s interrupt then 2–3 s context**, promise delivered by 3 s
  ([OpusClip, 11 Nov 2025](https://www.opus.pro/blog/instagram-reels-hook-formulas)). Their
  headline claim (3 s hold >60% → 5–10× reach) has no n and no method — vendor marketing.

**Genuinely unstudied publicly:** audio onset latency / leading silence · opening speech rate
(WPM) · time-to-first-cut.

### 1.7 Tech / AI-news specifically — one finding cuts against us

**[E]** *"Short-Form Video Viewing Behavior Analysis and Multi-Step Viewing Time Prediction"*
(**24 Mar 2026**, [arXiv 2603.22663](https://arxiv.org/html/2603.22663)) — 100 videos across 20
categories, 50 participants, 5,000 viewing sessions:

- **~70% of viewing sessions end before reaching 20% of video duration**
- average video 34.95 s
- *"Entertainment and nature videos showed better retention, while **educational content
  exhibited higher abandonment rates**."*
- ~92% of user viewing sequences were statistically stationary — consistent skipping within a
  session

**[D] Implication:** AI/tech news sits in the high-abandonment educational band. The hook has to
do *more* work than generic short-form benchmarks imply, and those benchmarks likely **overstate
the realistic ceiling** for this niche. Set internal targets below published bands.

**No evidence found for:** named-entity openings ("OpenAI just…") · recency framing ("just
released") · AI-voice vs human talking head for tech retention.

---

## 2. Caption typography and platform safe areas

### 2.1 The safe-area situation — read this before trusting any table

**[E] No platform publishes an official safe-area specification for organic vertical video.**
This was chased directly: TikTok's ads help pages, YouTube's Shorts help pages and Meta's ads
guide were all attempted. YouTube's Shorts documentation confirms only *"maximum resolution of
1080p"* and vertical orientation — **no aspect ratio spec, no safe-zone spec, no text-placement
guidance** ([YouTube Help](https://support.google.com/youtube/answer/10059070)). TikTok's help
domain blocks automated retrieval entirely.

**Consequence: every safe-area pixel table in circulation is a tool vendor measuring the app by
hand.** They are useful — someone has to measure it — but they are **[F]**, they disagree with
each other, and they go stale silently whenever a platform ships a UI change. Treat any such
table as a measurement with an unknown expiry date, and re-verify by screenshotting the three
apps before the reference short locks.

### 2.2 What can actually be anchored

**[E] WCAG 2.2 (W3C Recommendation, 12 Dec 2024)** — a real standard, and the one part of
caption design that is not folklore:
- SC 1.4.3 (AA): contrast ratio **≥ 4.5:1**; **≥ 3:1 for large text**
- "Large text" = **≥ 18 pt, or ≥ 14 pt bold**
- SC 1.4.6 (AAA): **≥ 7:1**; 4.5:1 for large text

**[D]** Burned-in captions at short-form sizes are unambiguously "large text," so the formal
floor is **3:1**. But WCAG assumes a *static* background; captions here sit over **moving video
with changing luminance**, where the effective contrast varies frame to frame. **Design to the
4.5:1 normal-text threshold and enforce it against the worst-case frame**, not the average. This
is why stroke or shadow is non-negotiable rather than stylistic — it guarantees the floor
regardless of what is behind the text.

**[E] Caption timing and sizing** — [vsubtitle, 13 Jul 2026](https://vsubtitle.com/subtitle-font-size-and-reading-speed-2026/),
squarely in the target window and the most specific source found:

| Parameter | Value |
|---|---|
| **Vertical mobile size (TikTok/Reels/Shorts)** | **36–48 px, often 48–60 px** on 1080-wide |
| Ratio standard | **1/20 to 1/10 of frame height** |
| Reading speed | 15–17 CPS target; 20 CPS hard ceiling |
| Min cue duration | **5/6 s**, ideally ~1 s · max ~7 s |
| Gap between cues | ≥ 1 frame |
| Max lines per cue | **2** |
| Line length | 42 chars (streaming standard); 32–37 (BBC style) |
| Weight | **medium-to-bold** |
| Stroke / shadow | **2–4 px dark stroke or drop shadow** |
| Treatment | white or off-white on dark outline, or semi-transparent box |
| Line spacing | 1.2–1.6× font size |
| **Vertical position** | **60–75% of frame height from top**, clear of platform UI, 5% title-safe margin from edges |

⚠️ Note the tension: `1/20 to 1/10 of frame height` on a 1920-tall frame is **96–192 px**, which
contradicts the same article's own `36–48 px`. The ratio is presumably meant for the 1080 **width**
or for horizontal frames. **[D] Trust the pixel figures, not the ratio** — 48–60 px on 1080-wide
is consistent with what the apps actually render and with the 36–48 px floor.

**[D] Position, reconciled.** vsubtitle's "60–75% of frame height from top" = **1152–1440 px** on a
1920-tall frame. Part 1 §A6 independently derived `safe_zone: top 8%, bottom 20% clear` — i.e.
usable band **154–1536 px**. The two agree, and the intersection is the defensible answer:
**place the caption baseline in the 1150–1440 px band.** That sits above the bottom-20% UI strip
and below centre, which is where the presenter's face is.

**[E] Words on screen.** legibility.info's graphic-text rules cap on-screen text at **≤30
characters per line and ≤3 lines**. Part 1 §A6 set `text_words_max: 6` **[F]**.
**[D] For word-timed captions, 2–4 words on screen is the working range** — Part 1's
`bold-overlay` reference style (the local `video-use` skill's shipped short-form preset) uses
**2-word chunks, UPPERCASE, break on punctuation, bold, white-on-outline** — which is the genre
convention, and it is well inside every legibility constraint above.

### 2.3 Highlight-word treatment — the slop risk

**No evidence was found that karaoke-style word highlighting improves retention.** It is
universally deployed and entirely **[F]**.

⚠️ **And Part 1 §A6 documents the opposite risk:** the Aug 2026 slop signature is *"constant
auto-zoom locked to speech + **word-by-word auto-captions** + evenly-spaced whooshes"*
(SlopDetector, Jun 2026, citing Kapwing's finding that ~21% of sampled YouTube Shorts contained
AI content). **Word-by-word highlighting is named as a component of the machine-made tell.**

**[D] Resolution:** this does not mean abandon word timing — it means avoid the *uniform,
mechanical* application of it. Highlight on **stressed or semantically loaded words only**
(entities, numbers, the verb carrying the claim), not on every word in sequence. That is the same
principle Part 1 reached for zooms and SFX: the technique is fine, the metronome is the tell.

### 2.4 What nobody publishes

Stated plainly, since absence is actionable: **official safe-area specs for organic video on any
of the three platforms** · **whether captions measurably improve short-form retention** (widely
asserted, no study found) · **word-timed vs phrase-timed performance comparison** · **all-caps vs
sentence case legibility evidence for this format** · **whether any platform auto-caption feature
now collides with burned-in captions**.

---

## 3. Audio

Part 1 had no audio stage at all; this is a genuine gap being filled, and the loudness section is
the only part of this whole briefing anchored in **published standards** rather than vendor blogs.

### 3.1 Loudness targets — what is official and what is guesswork

**[E] The single most important honest finding: TikTok, Instagram and Meta have never published
a LUFS target.** Every fixed number circulating for those platforms is an estimate.
[Forasoft, 5 Jun 2026](https://www.forasoft.com/learn/audio-for-video/articles-audio/lufs-targets-per-platform-2026)
tabulates this explicitly:

| Platform | Target | True peak | Officially published? |
|---|---|---|---|
| **YouTube** (incl. Shorts) | **−14 LUFS** | −1 dBTP | **Yes** |
| Spotify / TIDAL / Amazon / SoundCloud | −14 LUFS | −1 dBTP | Yes |
| Apple Music | −16 LUFS | −1 dBTP | Yes |
| Apple Podcasts | −16 LUFS (±1) | −1 dBTP | Yes |
| Netflix (cinematic) | −27 LKFS, dialog-gated | −2 dBTP | Yes |
| EBU R128 (broadcast) | −23 LUFS (±0.5) | −1 dBTP | Yes |
| ATSC A/85 (US broadcast) | −24 LKFS | −2 dBTP | Yes |
| **TikTok / Instagram / Meta** | **none** | −1 dBTP advised | **No** |

**[E] YouTube's normalization is asymmetric** — this is the mechanically important part:
louder than −14 LUFS gets **turned down**; quieter than −14 LUFS is **left alone, no gain
added**. Normalization is applied at playback; the uploaded file is not altered.

**[D] Consequence for an automated pipeline:** overshooting is punished (you get turned down and
lose the dynamic range you crushed to get there); undershooting is merely quiet. Since the
penalty is asymmetric, **target −14 LUFS integrated and never exceed it**. A single master at
−14 LUFS / −1.0 dBTP is the value that survives all three platforms.

⚠️ Vendor sources recommending **−10 to −12 LUFS for TikTok/Instagram**
([OpusClip, 17 Nov 2025](https://www.opus.pro/blog/best-loudness-normalizers)) are **[F]** —
they are guessing at an unpublished target. Following them means crushing dynamics for a spec
that may not exist, and being turned down on YouTube. **Do not chase them.**

**[F]** Dialogue-heavy content is often advised toward **−16 LUFS** on YouTube to preserve speech
dynamics (same OpusClip source). Reasonable, unsourced.

### 3.2 Music bed under a talking head

**[E-adjacent]** Convergent across two independent July 2026 sources — the tightest agreement in
this entire briefing:

- Music sits **15–20 dB below dialogue** while speech is present
  ([LunaBloom, 30 Jul 2026](https://blog.lunabloomai.com/video-sound-effects/))
- Music sits **−18 to −25 dB below the voice** while speech is present, ≈70–85% reduction
  ([Zella, 19 Jul 2026, reviewed 7 Aug 2026](https://zellahq.com/blog/music-ducking-explained/))

**[D] Take the overlap: −18 to −20 dB below dialogue during speech.** Both sources land inside it.

**Ducking curve [E-adjacent]:**
- **Automatic/dynamic ducking, not static** — Zella notes nobody sustains manual keyframing at
  "dozens per minute" of sentence boundaries. For an automated pipeline this is free.
- **Attack: under ~300 ms** when speech starts
- **Release: slower than attack** — produces "breathing" rather than "pumping." Zella gives no
  number; **[D] 400–800 ms** is the conventional range and should be tuned by ear once.
- Duck depth: **3–5 dB** of *additional* gain reduction on top of the static bed level is the
  film-mix convention (VI-Control practitioner consensus) **[F]**.

**Whether to have a bed at all:** **no retention evidence either way was found.** Part 1's
finding that raw/single-take straight-to-camera is outperforming polished on Instagram
(NewEngen 31 Jul, Lightreel 8 Aug 2026) **[E-adjacent]** argues for a *quiet* bed or none, not a
prominent one. Treat the bed as texture that prevents dead air, not as energy.

### 3.3 SFX

**[E-adjacent]** LunaBloom (30 Jul 2026) names the 2026 clichés precisely:
**whooshes on every text reveal · risers on every zoom · sharp hits ending every sentence ·
swells on every title card.** *"Whooshes, swishes, and risers are the sounds most likely to get
overused."*

The operative rule is **not a level, it is a placement rule**: apply transitional SFX only to
**actual structural changes**, never to every cut or title card, because constant decoration
makes audiences *"hear the edit instead of the content."*

**Their test, which is directly automatable as a review gate:** remove the effect. If nothing
changes except energy level, the sound was decorative — cut it.

⚠️ **This aligns exactly with Part 1's documented slop signature** (§A6): *constant auto-zoom
locked to speech + word-by-word auto-captions + evenly-spaced whooshes*. SFX density is
therefore a **slop risk**, not a production-value lever.

**[D] Density budget:** given "structural changes only" and Part 1's 4–8 layout changes per 60 s,
**≤6 non-diegetic SFX in 60 s**, all placed on semantic boundaries. Never on a timer.

### 3.4 Music licensing — the cross-posting trap

This is the section with real legal consequence, and the finding is sharper than expected.

**[E] TikTok's general sound library does not cover this use case.** It licenses **personal,
non-commercial** content only. The **Commercial Music Library (CML)** requires switching to a
**Business Account** (free), which then restricts the in-app editor to CML-cleared tracks.
[Soundstripe](https://www.soundstripe.com/blogs/tiktok-music-licensing-rules) ·
[Third Chair](https://usethirdchair.com/blog/tiktok-commercial-library-what-brands-can-really-use)

**[E] And the CML does not travel.** *"If the same video will also run on Instagram, YouTube,
ads, or client channels, the CML is not enough."* UMG catalogue remains unavailable via CML for
commercial brand content; some CML tracks are "Premium" and carry fees against ad inventory.

**[E] YouTube Audio Library has the mirror-image problem.** Official terms
([YouTube Help](https://support.google.com/youtube/answer/3376882)) confirm tracks are
Content-ID-safe and monetizable in YPP, attribution not required for standard-license tracks
(CC-licensed ones do require artist credit). **But the documentation only addresses in-platform
use — it does not grant off-YouTube rights.**

**[D] Conclusion for a create-once-distribute-everywhere pipeline: neither platform library is
usable.** Both are scoped to their own platform. A **single third-party license covering all
platforms** is the only architecture that works, and it must be acquired before the audio stage
ships.

**Options [E] on terms, prices as published:**

| Source | Commercial tier | Notes |
|---|---|---|
| **Uppbeat** | Free tier: 3 downloads/mo, 25% catalogue, individual license. Paid from ~₹299–₹999/mo | Marketed "safe for all platforms… copyright-safe for worry-free monetization"; Pro tier extends to organizations, digital ads, client content. [uppbeat.io/pricing](https://uppbeat.io/pricing) |
| **Epidemic Sound** | Personal from $6/mo (annual); **Business $29.99/mo** | Owns its full catalogue outright — cleanest rights position. Stems included. |
| **Artlist** | Pro ~$16.58/mo (annual) | Artists are PRO-affiliated, which *"could lead to extra payments"* — a real distinction from Epidemic. |

⚠️ **Content ID caveat [E]:** Uppbeat music is registered with YouTube Content ID, so uploads
*will* be flagged with a claim — clearable via their whitelist process, but it is an extra
pipeline step, not a non-event.

**[D] Recommendation:** Epidemic Sound Business or Uppbeat Pro. Epidemic's outright ownership is
the lower-risk rights position for an automated pipeline publishing without human legal review;
Uppbeat is materially cheaper but adds a Content ID clearance step per track.

---

## 4. Statistics cards and data reveals

**Honest framing first: there is no short-form-specific research on statistic cards.** No study
was found on count-up animations, chart types in 9:16, or numeral reading time in vertical video.
What follows derives from **adjacent domains that do have real standards** — subtitling,
on-screen graphic text legibility, and UI motion research — which is a far better foundation than
the vendor blogs, but the transfer is mine, not measured.

### 4.1 How long a number must be readable — three converging anchors [E]

| Anchor | Rule | Domain |
|---|---|---|
| **Netflix / streaming subtitle standard** | Minimum cue duration **5/6 s (0.83 s)**, "ideally closer to 1 s," even for a single word. Max ~7 s. | Subtitles |
| **legibility.info — rules for text in videos** | On-screen graphic text: **13 characters/second**; animated text must be **stationary 1 s per 13 characters**; ≤30 chars/line; ≤3 lines | Graphic text |
| **Subtitle reading speed** | 15–17 CPS comfortable, 20 CPS hard ceiling | Subtitles |

Note the important asymmetry: **graphic text gets 13 CPS, subtitles get 15–20 CPS.** Graphic text
is *glanced at* while the viewer is also tracking the presenter and the caption line; subtitles
are *tracked continuously*. A stat card competes for attention, so the slower figure is correct.

**[D] Derived dwell formula for a stat card:**
```
dwell_s = max(1.5, 0.83 + total_chars / 13)
```
A card reading "400M weekly users" (18 chars) → **max(1.5, 2.2) = 2.2 s stationary**, *after* any
entrance animation completes.

This is consistent with, and slightly more conservative than, Part 1 §A3's independently derived
`≈3 s + 0.5–0.7 s per word` for text holds. **Use the larger of the two.** Both agree that a
1–3 word label needs **2.5–4 s** — which is longer than the b-roll shot length (1.8–3.5 s), so
**a stat card must extend its shot, not ride an existing one.**

### 4.2 Entrance animation

**[E, adjacent domain]** [NN/g, 9 Feb 2020](https://www.nngroup.com/articles/animation-duration/)
— UI motion research, citing Head (2016), Saffer (2014), Pratt et al. (2010, *Psychological
Science*):

- Simple feedback: **~100 ms**
- Substantial screen changes: **200–300 ms**
- General range **100–500 ms**; **400–500 ms "becomes cumbersome and annoying"**
- Linear motion reads unnatural — **easing required**
- *"Find the shortest time an animation can take without being jarring"*; animations are far more
  often too long than too short

**[D] Transfer:** a stat card entrance is a "substantial screen change" → **200–300 ms, eased,
never linear, hard ceiling 400 ms.** Entrance time does **not** count toward the dwell in §4.1 —
the number is not readable while it is moving.

**[D] On count-up / odometer animations: use with caution.** A count-up is precisely a period
during which the number is *unreadable*, and it competes with the narration. If used, cap it at
**≤400 ms** and hold the settled value for the full §4.1 dwell afterwards. **No evidence exists
that count-ups improve anything** — they are a motion-design convention, not a measured lift.

### 4.3 Lead the word — the one craft rule with cross-domain agreement

**[E-adjacent]** Two independent sources converge:
- Part 1 §A4: *"B-roll should lead the word,"* appearing slightly before the noun is spoken
  (`broll_lead_word_ms: [200, 400]`)
- The manim-video production reference (local craft skill): *"The visual should appear slightly
  BEFORE the narration describes it. When the viewer sees a circle appear and THEN hears
  'consider a circle,' the visual primes their brain. The reverse — hearing first, seeing second
  — creates confusion because they're searching the screen for something that isn't there yet."*

**[D] Apply the same 200–400 ms lead to stat cards.** The card should be settled and readable at
the moment the presenter speaks the number, not arriving on it.

⚠️ This contradicts Part 1's `text_delay_after_speech_ms: [200, 400]` **[F]**, which has captions
*trailing* speech. Both cannot be right for the same element. **[D] Resolution: captions trail
(they transcribe what was said); stat cards lead (they prime what is about to be said).**
Different elements, opposite timing. Worth verifying on the reference short.

### 4.4 Spoken and shown, or one or the other?

**No evidence found.** The redundancy question — whether saying "four hundred million" while
showing "400M" helps or splits attention — is unstudied for this format. **[D]** Dual coding
theory would predict it helps when the two channels carry the *same* content in *different*
codes, which is exactly this case. Weak theoretical support, no measurement. Treat as a default,
not a finding.

### 4.5 Charts in 9:16

**No published guidance found.** Reasoning from arithmetic, the same way Part 1 §B6 handled
split-screen:

**[D]** A chart in the top panel of a stacked split gets **1080×960**. At the §4.1 legibility
floor (13 CPS, and axis labels needing ~40 px minimum to read on a phone), that space supports:
- a **single big number** with a short label — always safe
- a **bar chart of ≤4 categories** with direct labels, no legend, no axis
- **not** a line chart with a time axis, **not** anything requiring a legend, **not** multi-series

**[D]** Prefer the single big number. It is the only form that survives at phone scale with
certainty, and it matches the dwell budget — a chart requires materially more than 2.2 s to read,
which exceeds the shot-length budget for anything but a payoff beat.

### 4.6 Sourcing and attribution

**No evidence found** on whether on-screen source attribution affects trust, comments, or
retention. **[D]** Worth doing anyway on a defensive basis: Part 1 §A6 and the AI-slop literature
both identify *"vague, unverifiable claims without named sources or dates"* as a machine-made
tell ([SlopDetector, 30 Jun 2026](https://slopdetector.org/blog/how-to-spot-ai-slop)). A small
source line under a statistic is cheap and directly counters a documented slop signature. Size it
at ~40% of the caption size and exempt it from the dwell formula — it is a credibility signal,
not something the viewer is expected to read.

---

## Starting parameter set

Extends the block in `editing-grammar.md`. Same tags. **Every `[F]` and `[D]` value is a
convention or a derivation, not an optimisation target** — they exist so the pipeline has a
defensible default, not because they are known to be optimal.

```yaml
# ================= HOOK =================
hook_window_s:            2.0    # TikTok 2sVTR gate — the binding one          [E]
hook_confirm_window_s:    3.0    # Meta 3s / Skip Rate gate                     [E]
ASSERT: verbal hook complete AND value proposition legible by 2.0s.
        Seconds 2.0-3.0 CONFIRM, never INTRODUCE.                               [D]
hook_visual:              direct_to_camera_talking_head  # +14% 2sVTR, +50%
                                                         # hooking power        [E]
hook_setting:             indoors        # outdoors -26% 6s view-through        [E]
hook_persona:             everyday_person  # 1.7x vs celebrity -13%             [E]
hook_archetype:           [hot_take, investigator, diagnostic, scenario]        [E]
hook_text_overlay:        true   # sound-off insurance ONLY, not a measured lift [D]

BAN_at_open:
  - logo_card                     # -14% 6sVTR                                  [E]
  - story_preamble                # "So the other day/basically" ~20x worse     [E]
  - list_open                     # "5 AI tools you need" — named burned 2026   [E]
  - ring_light_testimonial        # pattern-matched as ad within 0.5s           [E]
  - forced_enthusiasm             # "changed my life", "skeptical but"          [E]

hook_template_decay:              # replaces a static banned-phrase list
  baseline_window_days: 7
  retire_if_hook_rate_below_trailing_mean_pct: 15                               [E]

alert_hook_rate_floor:  {meta_3s: 0.20, tiktok_2s: 0.20}   # cold traffic only  [E]
NEVER average or compare hook rates across platforms — 2s vs 3s definitions.    [E]

# ================= CAPTIONS =================
caption_font_px:          [48, 60]     # on 1080-wide; hard floor 36            [E]
caption_weight:           bold          # medium-to-bold                        [E]
caption_case:             UPPER
caption_chunk_words:      [2, 4]                                                [D]
caption_lines_max:        2                                                     [E]
caption_chars_per_line_max: 30                                                  [E]
caption_stroke_px:        [2, 4]        # dark stroke or drop shadow            [E]
caption_line_spacing:     [1.2, 1.6]                                            [E]
caption_min_cue_s:        0.83          # 5/6 s, streaming standard             [E]
caption_max_cps:          17            # 20 = hard ceiling                     [E]
caption_baseline_px:      [1150, 1440]  # on 1920-tall: below centre, above
                                        # the bottom-20% UI strip               [D]
caption_contrast_ratio_min: 4.5         # WCAG 2.2 AA normal-text threshold,
                                        # enforced vs WORST-CASE frame          [E]
highlight_words:          semantic_only # entities, numbers, claim-verb.
                                        # NOT every word in sequence.           [D]

safe_zone:                             # ALL VENDOR-MEASURED, NO OFFICIAL SPEC  [F]
  top_pct:    8
  bottom_pct: 20
  side_pct:   5
  RE-VERIFY by screenshotting all 3 apps before the reference short locks.

# ================= AUDIO =================
loudness_integrated_lufs: -14.0   # YouTube's ONLY published target;
                                  # TikTok/IG/Meta publish NONE                 [E]
true_peak_max_dbtp:       -1.0                                                  [E]
ASSERT: never exceed -14 LUFS. YouTube turns loud down but does NOT
        raise quiet up — the penalty is asymmetric.                             [E]
REJECT vendor advice to master -10..-12 LUFS for TikTok/IG:
       it targets a spec that does not exist.                                   [F]

music_bed_level_db_under_voice: [-20, -18]   # overlap of two Jul 2026 sources  [E-adj]
ducking_mode:             dynamic_sidechain  # not static                       [E-adj]
ducking_attack_ms:        [150, 300]                                            [E-adj]
ducking_release_ms:       [400, 800]         # slower than attack = "breathing" [D]
ducking_extra_depth_db:   [3, 5]                                                [F]
music_bed_role:           texture_preventing_dead_air, NOT energy               [D]

sfx_max_per_60s:          6                                                     [D]
sfx_placement:            semantic_structural_changes_only                      [E-adj]
SFX_GATE: remove the effect — if nothing changes but energy, cut it.            [E-adj]
ANTI_SLOP: never place SFX on a timer, on every cut, or on every text reveal.
           Whoosh-per-reveal is a documented 2026 tell.                         [E]

music_license:            third_party_all_platform   # Epidemic Business or
                                                     # Uppbeat Pro              [D]
NEVER use: TikTok general sound library (personal/non-commercial only)          [E]
           TikTok CML for cross-posted assets (TikTok-scoped only)              [E]
           YouTube Audio Library off-YouTube (no off-platform rights granted)   [E]

# ================= STAT CARDS =================
statcard_dwell_s:         max(1.5, 0.83 + total_chars / 13)   # 13 CPS for
                                                              # GRAPHIC text    [E]
                          # cross-check vs Part 1: 3.0 + 0.6*words. USE LARGER.
statcard_entrance_ms:     [200, 300]    # hard ceiling 400; eased, never linear [E-adj]
statcard_entrance_excluded_from_dwell: true   # unreadable while moving         [D]
statcard_countup_ms_max:  400           # optional; NO evidence it helps        [D]
statcard_lead_word_ms:    [200, 400]    # card SETTLED before the number is
                                        # spoken — leads, unlike captions
                                        # which trail                           [E-adj]
statcard_form:            single_big_number > bar_chart(<=4, direct-labelled)
                          NEVER: line chart w/ time axis, legends, multi-series  [D]
statcard_source_line:     true, ~40% caption size, exempt from dwell            [D]
ASSERT: a stat card EXTENDS its shot beyond b-roll shot length (1.8-3.5s).
        It cannot ride an existing shot.                                        [D]
```

---

## The four things most worth acting on

1. **Build the hook to 2.0 s, not 3.0 s.** TikTok's gate is the binding constraint, and it is
   one of the few genuinely evidenced numbers here. A hook designed to 3 s fails on TikTok every
   time. This is a one-line rule that a lot of published advice gets wrong.
2. **Master to −14 LUFS and stop there.** YouTube is the only platform of the three that
   publishes a target, its normalization is asymmetric (loud gets turned down, quiet does not get
   turned up), and the −10/−12 LUFS advice for TikTok/IG chases a spec that does not exist.
3. **The music licensing architecture must be decided before the audio stage is built.** Both
   platform-native libraries are scoped to their own platform, so neither works for
   create-once-distribute-everywhere. This is a legal constraint, not a preference.
4. **Every anti-slop finding in Parts 1 and 2 converges on the same rule: uniformity is the
   tell.** Word-by-word caption highlighting, whoosh-per-reveal, timer-based SFX, speech-locked
   zoom — each is individually fine and collectively damning when applied mechanically. For an
   automated pipeline, whose default failure mode is exactly uniformity, **semantic placement
   over metronomic placement** is the single highest-leverage principle in both documents.

## Where to stop trusting this document

- **§2 safe areas are the weakest section**, and not for lack of trying: no platform publishes a
  spec, so the numbers are vendor hand-measurements with unknown expiry. Screenshot-verify.
- **§4 is entirely derived.** No short-form research on stat cards exists. The anchors are real
  (Netflix, legibility.info, NN/g) but the transfer to 9:16 video is mine.
- The hook §1.7 educational-abandonment finding (n=50 participants) is a small study; direction
  is plausible, magnitude should not be quoted.
- Vidmob's hook data is **paid ads from 2023**. Direction robust, magnitude indicative, and it
  may not transfer cleanly to organic.
- Two Part 1 / Part 2 conflicts are flagged and resolved by reasoning, not evidence:
  caption-trails vs statcard-leads (§4.3), and the px-vs-ratio caption sizing contradiction
  (§2.2). Both should be settled empirically on the reference short.

---
