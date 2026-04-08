---
title: Content Curation Source TOS Review
date: 2026-04-09
status: blocking-gate-for-plan-2026-04-08-001
---

# Content Curation Source TOS Review

Scope: determine whether each of the 11 proposed curation sources permits the CommonCreed use case, which is:

1. Programmatically fetching content (API or scraping),
2. Re-encoding / overlaying a credit on media assets,
3. Re-uploading the resulting derivative to CommonCreed-owned **monetized** Instagram and YouTube accounts (targeting $5k/month via AdSense).

This is a stricter bar than "can I read the feed" — it requires an explicit or clearly implied permission to redistribute third-party content on a commercial surface.

Research method: WebFetch against each source's developer terms / TOS pages on 2026-04-09. Where a fetch failed (Reddit, X, Substack) the best available public secondary source is used and flagged inline. All quotes are verbatim from the fetched page unless marked `[paraphrased — fetch failed]`.

## Summary table

| # | Source | Verdict | One-line rationale |
|---|---|---|---|
| 1 | Reddit Data API | Fail | Post-2023 Data API Terms restrict commercial use and redistribution; we are not a licensed partner. |
| 2 | Hacker News Firebase API | Conditional | API itself has no formal terms, but HN posts are user-owned; the actual target is the *linked article*, whose license is set by the third-party publisher, not HN. |
| 3 | GitHub Trending | Conditional | Trending page metadata (repo name, description, stars) is fine to surface; README images/gifs are under the repo's own license (often none granted) and cannot be blanket-reused. |
| 4 | Hugging Face Trending | Conditional | HF TOS grants other users a license to content in public repos "through our Services and functionalities"; reuploading model-page gifs to IG/YouTube is outside that functional scope unless the underlying model/space license permits it. |
| 5 | arXiv cs.AI / cs.CL RSS | Conditional | Only papers tagged CC BY or CC BY-SA are redistributable commercially. The default arXiv Non-Exclusive License explicitly "limits re-use of any type." Must filter by license field. |
| 6 | Lobste.rs RSS | Conditional | Same structure as HN: Lobsters content is community-submitted, the target is the linked article. Lobsters itself does not explicitly restrict commercial reuse but has no grant either. |
| 7 | Product Hunt API | Fail | API docs state "The Product Hunt API must not be used for commercial purposes." |
| 8 | Substack RSS | Fail | Substack TOS explicitly prohibits crawling/scraping and storing "any significant portion of the content"; RSS republishing rights are not granted. |
| 9 | Instagram creator media (Graph API) | Fail | No 2026 API surface exists for fetching media from creators the developer does not own. Basic Display API was deprecated Dec 4, 2024. Confirmed. |
| 10 | X / Twitter List timelines | Fail | X Developer Agreement restricts off-platform redistribution of Content; reuploading media to IG/YouTube is not a permitted use. (Secondary-source confirmation — developer.x.com returned HTTP 402.) |
| 11 | YouTube trending (Data API v3) | Fail | YouTube API Services Developer Policies explicitly prohibit "download, import, backup, cache, or store copies of YouTube audiovisual content" and require playback only through the embedded player. |

Result: **3 fail hard, 5 conditional, 0 clean yes, 3 require per-item license filtering.** The conditional sources are only useable if we restrict ourselves to metadata + linking out (or, for arXiv, filter by CC license tag).

## Per-source analysis

### 1. Reddit

**Verdict:** Fail

**Relevant clause (direct quote):** Fetch of `reddit.com/wiki/api-terms` and `redditinc.com/policies/data-api-terms` was blocked by Reddit (WebFetch returned "unable to fetch from www.reddit.com"). Per well-documented public record of the June 2023 Reddit Data API Terms update and the 2024 Google and OpenAI data-licensing deals, the Data API Terms require a separate commercial agreement for any non-personal, non-researcher commercial use, and prohibit using Reddit User Content to train models or to redistribute outside of Reddit's embed surfaces without a license. `[quote unavailable — fetch blocked]`

**Source:** https://www.redditinc.com/policies/data-api-terms (fetch blocked 2026-04-09)

**Analysis:** Even leaving aside rate-limit pricing, the redistribution clause alone is disqualifying: CommonCreed would be republishing user-submitted media on a monetized YouTube/IG surface, which is exactly the scenario the 2023 terms were written to stop. We are not a licensed data partner and cannot become one at our scale.

**Fallback if No:** Drop from scope. Reddit trends can inform *topic selection* (a human reads Reddit, picks a topic, we generate original content about it) but Reddit content itself cannot enter the pipeline.

### 2. Hacker News

**Verdict:** Conditional

**Relevant clause (direct quote):**
> "Please email api@ycombinator.com if you find any bugs."

Per the Firebase HN API README, there is **no** explicit license, terms of service, or usage restrictions stated in the API documentation itself.

**Source:** https://github.com/HackerNews/API

**Analysis:** The HN API surfaces story metadata: title, URL, score, author, comments. The media we would actually reshare is **the linked article**, not the HN post. That means the governing TOS is the publisher's (NYT, a personal blog, arXiv, etc.), not HN's. HN comments are user-owned and cannot be reproduced without attribution and permission, but we don't need comments for the curation pipeline. The HN API itself is usable for topic discovery.

**Fallback if No:** N/A — conditional. Use HN only for story discovery (title + URL + score). Never reproduce HN comment bodies. For the linked article, the per-publisher check moves to a different guardrail (robots.txt + per-domain allowlist).

### 3. GitHub Trending

**Verdict:** Conditional

**Relevant clause (direct quote):**
> "If you set your pages and repositories to be viewed publicly, you grant each User of GitHub a nonexclusive, worldwide license to use, display, and perform Your Content through the GitHub Service and to reproduce Your Content solely on GitHub as permitted through GitHub's functionality (for example, through forking)." — §D.5

> "You retain all moral rights to Your Content ... including the rights of integrity and attribution." — §D.7

**Source:** https://docs.github.com/en/site-policy/github-terms/github-terms-of-service

**Analysis:** §D.5 is critical: the license granted to other users is to reproduce content **solely on GitHub**. That does not grant us the right to take a README gif or a repo screenshot and republish it on Instagram. Repo metadata (name, description, star count, language) is factual and not copyrightable, so surfacing it is fine. But any visual asset (README images, demo gifs, screenshots) is owned by the repo author under the repo's own license, which is usually either unspecified (= all rights reserved) or MIT/Apache (which cover code, not necessarily media).

**Fallback if No:** Use GitHub Trending **only** for metadata-driven topic cards (repo name + one-line description + star delta + link). Never reupload README media. If a repo's LICENSE explicitly covers media under a permissive license (rare), it can be promoted to full reshare, but this must be a per-repo manual check — not a pipeline default.

### 4. Hugging Face Trending

**Verdict:** Conditional

**Relevant clause (direct quote):**
> "If you decide to set your Repository public, you grant each User a perpetual, irrevocable, worldwide, royalty-free, non-exclusive license to use, display, publish, reproduce, distribute, and make derivative works of your Content through our Services and functionalities"

> "Certain items provided with the Services may be subject to 'open source' or 'creative commons' or other similar licenses... The Open Source license terms are not intended to be replaced or overridden by the license and other terms of these Terms"

**Source:** https://huggingface.co/terms-of-service

**Analysis:** HF's TOS grants a redistribution license but scopes it to "through our Services and functionalities" — same failure mode as GitHub §D.5. The escape hatch is the second clause: each model and space has its own license field (Apache-2.0, MIT, CC-BY, OpenRAIL, etc.), and if the per-item license permits commercial redistribution, we can use assets under that license. The HF API exposes this license field per model, so filtering is automatable.

**Fallback if No:** Filter trending feed to items whose `cardData.license` is in a permissive allowlist (`apache-2.0`, `mit`, `cc-by-4.0`, `cc-by-sa-4.0`, `cc0-1.0`, `bsd-*`). Drop everything else (including `openrail`, `llama2`, unlicensed, and `other`). For those filtered items, model-card text and images are reusable with attribution.

### 5. arXiv cs.AI / cs.CL

**Verdict:** Conditional

**Relevant clause (direct quote):**
> "This license gives limited rights to arXiv to distribute the article, and also limits re-use of any type from other entities or individuals."

Permitted author-selected licenses are CC BY 4.0, CC BY-SA 4.0, CC BY-NC-SA 4.0, CC BY-NC-ND 4.0, and CC0.

**Source:** https://info.arxiv.org/help/license/index.html

**Analysis:** The arXiv default ("Non-Exclusive License to Distribute") explicitly "limits re-use of any type." For commercial reshare we need CC BY, CC BY-SA, or CC0. CC BY-NC-* is disqualifying because the target account is monetized. CC BY-ND is disqualifying because we make derivative works (overlay credit, re-encode for Reels). The arXiv API exposes the license in each paper's metadata, so filtering is automatable.

**Fallback if No:** Filter to papers tagged `http://creativecommons.org/licenses/by/4.0/`, `http://creativecommons.org/licenses/by-sa/4.0/`, or `http://creativecommons.org/publicdomain/zero/1.0/`. For everything else (the majority), we can still use title + abstract under fair-use quoting + a link, but cannot reproduce figures or full PDFs.

### 6. Lobste.rs

**Verdict:** Conditional

**Relevant clause (direct quote):** Lobsters provides public RSS feeds and has no explicit commercial-reuse restriction in its About/rules page. Site source is 3-clause BSD, but that covers the software, not user-submitted stories.

**Source:** https://lobste.rs/about

**Analysis:** Structurally identical to Hacker News: Lobsters is a link aggregator, so the reshare target is the linked article, not the Lobsters submission. Lobsters comment bodies are user-owned. The RSS feed is fine to poll for topic discovery. As with HN, the real TOS gate moves to the linked publisher.

**Fallback if No:** Same as HN — use for story discovery only, never reproduce comment bodies, and run a per-domain robots.txt / TOS check on the linked article before any media reuse.

### 7. Product Hunt

**Verdict:** Fail

**Relevant clause (direct quote):**
> "The Product Hunt API must not be used for commercial purposes. If you would like to use it for your business, please contact us at hello@producthunt.com."

**Source:** https://api.producthunt.com/v2/docs/store/terms_and_conditions

**Analysis:** This is a flat, explicit prohibition on commercial use of the API. CommonCreed is monetized. Requesting a commercial partnership is theoretically possible but out of scope for v1 and unlikely to be granted to a small account.

**Fallback if No:** Drop from scope for v1. If Product Hunt partnership ever becomes interesting, revisit via a signed commercial API agreement.

### 8. Substack

**Verdict:** Fail

**Relevant clause (direct quote):**
The Substack TOS fetch surfaced explicit prohibitions on:
> "Crawls," "scrapes," or "spiders" any page, data, or portion of Substack
> "Copies or stores any significant portion of the content on Substack"

And:
> "you grant all other users of Substack a license to access the Post, and to use and exercise all rights in it, as permitted by the functionality of Substack"

**Source:** https://substack.com/tos

**Analysis:** Two separate disqualifiers. First, the anti-scraping clause rules out the approach of hitting multiple newsletter RSS feeds on a schedule and storing their content — even if each newsletter has a public RSS feed, the platform-level TOS prohibits storing "any significant portion" of the content. Second, the inter-user license is scoped "as permitted by the functionality of Substack," which is the same embed-only scope GitHub and HF use, and does not extend to IG/YouTube reupload.

**Fallback if No:** Drop from scope. Individual newsletter authors may grant us direct reuse rights via email — but that is a manual per-author deal, not a pipeline source. Removing Substack eliminates Platformer, Stratechery, Ben's Bites, Import AI as pipeline inputs. They can still inform the human topic-selection step.

### 9. Instagram creators (Meta Graph API)

**Verdict:** Fail

**Relevant clause (direct quote):**
Meta Platform Terms §3.a enumerates prohibited data uses and additionally states that developers may only use Platform Data for the purposes documented in Meta's Developer Docs. The Instagram Platform documentation (https://developers.facebook.com/docs/instagram-platform) only exposes two API surfaces in 2026: "Instagram API with Instagram Login" (accesses the authenticated user's own account) and "Instagram API with Facebook Login for Business" (accesses IG Business/Creator accounts the developer has been **authorized by the account owner** to manage). Neither exposes media from creators the developer does not own or manage.

Meta announced the Instagram Basic Display API deprecation on September 4, 2024 with full shutdown on **December 4, 2024**. As of 2026-04-09 it is fully off.

The `hashtag_search` endpoint returns metadata for recent hashtag posts but explicitly excludes owned media download rights and is rate-limited and scoped to business discovery, not republishing.

**Source:** https://developers.facebook.com/docs/instagram-platform and https://developers.facebook.com/terms/

**Analysis:** The plan's adversarial-review claim is confirmed: there is no 2026 API that lets a developer fetch media from an arbitrary Instagram creator they do not own or manage. Even if such data could be obtained (e.g. via scraping), doing so would violate Meta Platform Terms §3.a's prohibition on processing Platform Data outside "permitted uses in Meta's Developer Docs."

**Fallback if No:** Drop from scope entirely. If the product requires IG creator content, the only legal path is a direct licensing deal with each creator (manual, per-creator, signed). Not a pipeline source.

### 10. X / Twitter List timelines

**Verdict:** Fail

**Relevant clause (direct quote):** Fetch of developer.x.com returned HTTP 402. Per well-documented public record of the X Developer Agreement (current as of the 2024 paid-tier restructuring): the Developer Agreement and Policy restrict redistribution of X Content off-platform except via X's official embed and sharing tools, and the Display Requirements document mandates that Tweets be displayed via the embedded Tweet widget, with prohibitions on reposting media outside of that widget. Monetized redistribution of X media on third-party surfaces is a paid-tier / enterprise-only use case and requires a separate commercial agreement at the Pro ($5,000/month) or Enterprise level. `[quote unavailable — developer.x.com returned 402]`

**Source:** https://developer.x.com/en/developer-terms/agreement-and-policy (fetch returned HTTP 402 on 2026-04-09)

**Analysis:** Even at the paid Basic tier, the Display Requirements prohibit taking a video from X and reuploading it to IG/YouTube with an overlay. The only permitted display is X's embed widget. This is disqualifying for the reupload-with-credit use case regardless of tier.

**Fallback if No:** Drop from scope. X List timelines can still inform human topic selection, but no X Content enters the pipeline.

### 11. YouTube trending (Data API v3)

**Verdict:** Fail

**Relevant clause (direct quote):**
> "download, import, backup, cache, or store copies of YouTube audiovisual content without YouTube's prior written approval"

> "separate, isolate, or modify the audio or video components of any YouTube audiovisual content"

Additionally: developers may not "make content available for offline playback" and may not "modify, build upon, or block any portion or functionality of a YouTube player."

**Source:** https://developers.google.com/youtube/terms/developer-policies

**Analysis:** This is the clearest disqualification in the set. The YouTube API is fine for reading video metadata (title, channel, view count, category) from `videos.list?chart=mostPopular`, but fetching the actual video bytes, transcoding them, and reuploading to a different channel is precisely what the Developer Policies prohibit. Additionally, reuploading another creator's YouTube video to our YouTube channel would trigger Content ID and put the monetized channel at strike risk, which is a second, independent blocker.

**Fallback if No:** Use YouTube Data API v3 for metadata-only trending signals (topic discovery). Never fetch video bytes. Never reupload YouTube video content to any surface. If we want to reference a trending video, link to it on YouTube and let viewers click through.

## Recommended v1 source list

**Passed (use for metadata + topic discovery only, no media reshare):**
- Hacker News — via Firebase API, story titles + links, no comment reproduction.
- Lobste.rs — via public RSS, story titles + links, no comment reproduction.
- GitHub Trending — via scraping or GraphQL, repo name / description / star delta only, no README media.
- Hugging Face Trending — via `/api/trending`, filtered to permissive licenses only, model/space name + description.
- arXiv cs.AI and cs.CL — via `export.arxiv.org/rss/cs.AI` and `cs.CL`, filtered to CC BY / CC BY-SA / CC0, title + abstract + link. Figures only if the paper is explicitly CC BY.
- YouTube Data API v3 trending chart — metadata only, zero byte-level media access, link out.

**Dropped entirely (cannot be used in the pipeline, even for topic discovery at scale):**
- Reddit — Data API terms and rate-limit cost. Keep as a manual topic-research surface for the human operator.
- Product Hunt — API explicitly forbids commercial use.
- Substack — TOS prohibits crawling and bulk storage.
- Instagram creators — no 2026 API surface exists.
- X / Twitter Lists — Display Requirements forbid off-platform reupload.

**Require a different approach (link-out / embed only, never reupload):**
- All six "passed" sources above — the v1 pipeline must be restructured so it generates **original** media (scripts, voice, visuals produced by ComfyUI and ElevenLabs) **about** the trending topics surfaced from these sources, rather than **reusing** third-party media. This matches the existing CommonCreed project design in CLAUDE.md (faceless AI-generated content) and avoids every TOS issue above.

## Hard blockers for the plan

Two findings require the main session to reshape the plan before implementation:

1. **There is no source in the v1 list that permits the "download media, overlay credit, reupload to monetized account" pattern at the platform level.** The curation track as originally framed is not legally viable across any of the 11 sources. The plan should be updated so curation = "topic signal sourcing" and production stays faceless-AI-generated, as in the existing CommonCreed pipeline.

2. **Instagram creator media access does not exist as an API.** The plan's adversarial-review claim is confirmed. Any plan step that assumes fetching IG creator posts must be deleted, not deferred.

## Fetch failures (for transparency)

- `www.redditinc.com/policies/data-api-terms` — WebFetch blocked by Reddit.
- `www.reddit.com/wiki/api-terms` — WebFetch blocked by Reddit.
- `developer.x.com/en/developer-terms/agreement-and-policy` — HTTP 402.
- `developer.x.com/en/developer-terms/policy` — HTTP 402.

For these three pages, verdicts rely on well-documented public record of the current terms rather than fresh verbatim quotes. Before implementation, a human should confirm the Reddit and X clauses verbatim via a browser.
