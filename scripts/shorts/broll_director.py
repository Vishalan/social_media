"""B-roll director: choose a generator per beat, and produce its payload.

The repo already contains eight b-roll generators. Each is good at one thing
and useless at the others: `tweet_reveal` needs a quoted person, `stats_card`
needs a figure, `code_walkthrough` needs an API or SDK, `cinematic_chart` needs
comparable numbers. Wiring one of them in and using it everywhere is what made
the video feel repetitive — five cutaways to the same scrolling page.

So the director does two jobs in a single intelligence call:

1. **Choose** a type for each beat, from the types this story can actually
   support. A beat with no quoted person cannot be a tweet card.
2. **Produce the payload** that type needs. Choosing `tweet_reveal` is useless
   without an author, handle and body; the choice and its data have to be
   decided together or the dispatcher has nothing to render.

The generators expect a ``VideoJob``; ``_JobShim`` supplies the handful of
attributes each one actually reads.

Durations are normalised after generation. Generators return what their content
happens to need — one asked for 6.0s returned 4.0s because xfade transitions
eat from the tail — and the assembler places clips on a timeline, so a clip
that lies about its length shifts everything after it.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DirectorError(RuntimeError):
    """Raised when no b-roll can be planned or rendered."""


# What each type needs to exist, and what it is FOR. This text is handed to the
# planner verbatim — it is the description the choice is made from.
TYPE_CATALOG: dict[str, dict[str, str]] = {
    "highlight": {
        "needs": "article body text",
        "for": ("the source's own sentence, swept word-by-word in a phone "
                "mockup. Use when the narration is explaining something the "
                "article states in words worth reading."),
    },
    "stats_card": {
        "needs": "a specific figure stated in the source",
        "for": ("an animated counter landing on a number. Use for a single "
                "hard figure — a count, a multiple, a price."),
    },
    "headline_burst": {
        "needs": "a surprising claim",
        "for": ("punchy text on a cinematic gradient. Use for the hook or a "
                "claim that lands better as a statement than as evidence."),
    },
    "tweet_reveal": {
        "needs": "a named person quoted in the source",
        "for": ("a social-post card with the quote and an animated like "
                "counter. Use when a named human said something, not for "
                "company statements."),
    },
    "code_walkthrough": {
        "needs": "an API, SDK, CLI, config file or code artifact",
        "for": ("a syntax-highlighted code or config panel. Use when the "
                "narration describes something a developer would type or a "
                "file they would open."),
    },
    "split_screen": {
        "needs": "two comparable things",
        "for": ("a stacked two-panel comparison. Use for before/after, "
                "open/closed, us/them — never for a single subject."),
    },
    "cinematic_chart": {
        "needs": "two or more comparable numbers",
        "for": ("an animated chart. Use only when the numbers genuinely "
                "compare; a single figure belongs in stats_card."),
    },
    "mechanism": {
        "needs": "a process the source describes in steps",
        "for": ("a built diagram showing HOW the thing works — inputs flowing "
                "through stages to an output, ending in a concrete result. The "
                "single most valuable type when the story explains a mechanism, "
                "because narration alone cannot show a flow."),
    },
    "annotate": {
        "needs": "a capturable URL and one exact phrase or figure on that page",
        "for": ("the real page with ONE phrase boxed and everything else dimmed. "
                "Use when the proof is a specific line in a primary source — a "
                "figure in a paper, a licence field, a clause. Far stronger than "
                "scrolling past it."),
    },
    "macro": {
        "needs": "a capturable URL and one small element worth magnifying",
        "for": ("an extreme push into a single UI element — a button, a badge, a "
                "toggle — starting wide and landing tight. Use when the story "
                "turns on one control or label."),
    },
    "ai_video": {
        "needs": ("a beat with NO concrete artifact — no page, no number, no "
                  "quote, no file. Speculative, abstract or future-facing"),
        "for": ("generated cinematic footage: a scene, shot like film. Use ONLY "
                "when there is genuinely nothing real to show. If the source has "
                "a page, a figure or a quote for this beat, that is always "
                "stronger — generated footage of someone at a laptop is the same "
                "irrelevant filler as stock. Describe a SCENE, never a concept."),
    },
    "lockup": {
        "needs": "a name worth putting on screen — a licence, a product, a repo",
        "for": ("a large name with a badge beneath it and one sentence typing "
                "in under that. The workhorse for 'X is now Y': a licence, a "
                "release, a rename. Use when the story turns on naming a thing."),
    },
    "stock_clip": {
        "needs": "a concrete, filmable subject: a place, an object, an activity",
        "for": ("REAL FOOTAGE of the thing. Not a diagram of it, not a card "
                "naming it — actual moving imagery. Use it for atmosphere and "
                "for subjects that exist in the physical world: trading "
                "floors, city skylines, server rooms, hands on a keyboard, "
                "traffic, crowds. The query is a camera brief, so describe a "
                "SHOT and not a concept: 'stock exchange trading floor' finds "
                "footage, 'financial growth' finds nothing usable."),
    },
    "comparison_scene": {
        "needs": "two or three quantities that can be set against each other",
        "for": ("bars that GROW and numbers that COUNT UP, side by side. Use "
                "it whenever the story is 'bigger than', 'ahead of', 'more "
                "than' — which is the shape most business, money and policy "
                "stories actually have. It is the visual answer for a story "
                "with no software to point a camera at: the bar carries the "
                "meaning, so a viewer who reads nothing still sees which one "
                "is longer. Mark the story's subject with lead: true."),
    },
    "terminal_scene": {
        "needs": "a repo, a file, a command, or any concrete developer action",
        "for": ("a REAL TERMINAL running the thing. Commands are typed at a "
                "prompt and output appears under them, shot with a camera that "
                "pushes in and punches onto the line that matters. For a story "
                "about code this is the strongest possible image, because it "
                "shows the software instead of describing it. Write commands "
                "someone would actually run and output they would actually "
                "see — invented output reads as fake to the audience that "
                "cares most."),
    },
    "device_scene": {
        "needs": "an app, feed, ranking, recommendation or user-visible surface",
        "for": ("a PHONE running the product, with real posts/rows in it and "
                "the score or verdict attached to each. Use it for what the "
                "system DOES to what a person sees, where terminal_scene is "
                "for the code itself. The viewer already knows this surface, "
                "so it needs no explaining."),
    },
    "flow_scene": {
        "needs": "a process with 3-5 ordered stages that something passes through",
        "for": ("an actual DIAGRAM — numbered nodes down a spine, connectors "
                "that draw themselves between them, a token travelling the "
                "path, and the output landing at the end. Use it when the story "
                "explains how something WORKS: what goes in, what happens to "
                "it, what comes out. A flow is the one idea a diagram states "
                "and a sentence only approximates, so prefer this over "
                "mechanism whenever there is a genuine pipeline."),
    },
    "window_scene": {
        "needs": "a file, repo, config, terminal or app surface in the story",
        "for": ("THE DEFAULT for anything a developer would open — a repo, a "
                "diff, a config, a log, a terminal. Prefer it over a text card "
                "whenever the story touches a file or an interface. "
                "The subject's actual interface as a real window — chrome, "
                "title bar, syntax-coloured lines — sitting on a full-bleed "
                "field in the SUBJECT's brand colour, under an editorial "
                "title. Use it whenever the story turns on something a "
                "developer would open: a repo, a diff, a config, a log. It "
                "carries far more than a text card because the viewer sees the "
                "thing itself."),
    },
    "ai_scene": {
        "needs": ("a beat with NO concrete artifact to show — no page, no "
                  "figure, no quote, no file. Atmosphere, stakes or scale"),
        "for": ("generated cinematic footage: a real place, shot like film. "
                "PREFER IT FOR THE OPENING BEAT — an establishing shot that "
                "sets the stakes before any fact lands is exactly what the "
                "built graphics cannot do, and it is the one moment where "
                "atmosphere outperforms information. Exactly ONE per video, so "
                "if you do not spend it on the open, spend it on the closing "
                "stake and nowhere else.\n"
                "     Describe a PLACE and what the camera does, never a "
                "concept. 'A dark data centre aisle, racks receding either "
                "side, status lights blinking, slow forward push' works; 'the "
                "power of algorithms' does not. Anchor it in the SOURCE: the "
                "actual place, object or room the story is about — where this "
                "code runs, who touches it, what room the decision was made "
                "in. Never ask for text, logos, UI or screens with readable "
                "content: generated lettering is always garbled, and our "
                "typography layer owns every word the viewer reads."),
    },
    "pageroll": {
        "needs": "a capturable source URL",
        "for": ("a held or slowly travelling view of the real page. The "
                "fallback — it always works and is the least interesting, so "
                "prefer anything else that fits."),
    },
}


@dataclass
class _JobShim:
    """The attributes the generators actually read off a VideoJob."""
    script: dict = field(default_factory=dict)
    topic: dict = field(default_factory=dict)
    caption_segments: list = field(default_factory=list)
    extracted_article: dict = field(default_factory=dict)
    tweet_quote: Optional[dict] = None
    split_screen_pair: Optional[dict] = None
    chart_spec: Optional[dict] = None
    audio_url: str = ""


@dataclass
class Slot:
    """One planned b-roll cut."""
    index: int
    kind: str
    start: float
    duration: float
    narration: str
    payload: dict = field(default_factory=dict)
    why: str = ""
    path: str = ""
    error: str = ""
    # Whether this clip takes the whole frame. Decided before rendering,
    # because the render size depends on it.
    fullscreen: bool = False


_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "slots": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "beat": {"type": "integer"},
                    "kind": {"type": "string"},
                    "why": {"type": "string"},
                    "payload": {"type": "object"},
                },
                "required": ["beat", "kind", "why", "payload"],
            },
        }
    },
    "required": ["slots"],
}


def _catalog_text(available: list[str]) -> str:
    return "\n".join(
        f"  {k}\n     needs:   {TYPE_CATALOG[k]['needs']}\n"
        f"     for:     {TYPE_CATALOG[k]['for']}\n"
        f"     payload: {PAYLOAD_SPEC.get(k, '(no payload needed)')}"
        for k in available if k in TYPE_CATALOG)


_SYSTEM = """You are the b-roll director for a vertical short-form tech video. The
presenter is on camera for the whole piece; you decide what appears in the
content panel above them at specific moments.

Rules that matter more than variety:

- Choose the type that FITS the beat, not the type that is novel. A wrong-fit
  graphic is worse than the plain fallback.
- Do not repeat a type unless nothing else fits that beat.
- Every payload value must come from the SOURCE. Never invent a quote, a
  figure, a handle, or a number. If a type's payload cannot be filled from the
  source, do not choose that type.
- A beat that nothing fits should be given "pageroll". Saying "none of these
  work here" is a valid and useful answer.
- "why" must name the specific thing in the source that justifies the choice,
  not restate the narration.

Payload shapes, exactly:
  highlight        {"sentence": "verbatim sentence from the source"}
  stats_card       {"value": "72,596", "label": "GitHub stars"}
  headline_burst   {"text": "short punchy line, max 8 words"}
  tweet_reveal     {"author": "Full Name", "handle": "@handle",
                    "body": "the quote, verbatim", "verified": true}
  code_walkthrough {"language": "yaml", "filename": "SKILL.md",
                    "lines": ["line 1", "line 2"]}
  split_screen     {"left_title": "...", "left_lines": ["..."],
                    "right_title": "...", "right_lines": ["..."]}
  cinematic_chart  {"title": "...", "series": [{"label": "...", "value": 12}]}
  mechanism        {"title": "How it works",
                    "stages": ["Cortical signal", "Decoder model", "Text output"],
                    "result": "i need more coffee"}
  annotate         {"phrase": "exact phrase as it appears on the page",
                    "label": "why this line matters, max 6 words"}
  macro            {"target": "exact visible text of the element to magnify",
                    "label": "what it does, max 6 words"}
  ai_video         {"scene": "a wireframe human figure rotating slowly on a
                    dark grid, volumetric light, shallow depth of field"}
  pageroll         {}

Reply with JSON only."""


_SCENE_KINDS = frozenset({"ai_scene", "stock_clip", "terminal_scene",
                          "device_scene", "window_scene",
                          "flow_scene", "comparison_scene"})

class BrollDirector:
    """Plans and renders a varied b-roll slate for one short."""

    # Types whose whole point is a sequential build need time for it. A 2.6s
    # mechanism clip spent its first second on a bare title, because the flow
    # had not started yet — a third of the clip was empty.
    # Superseded by _DURATION_BOUNDS, which sets a floor AND a ceiling per type
    # from the card's own content. Kept only so a kind absent from the bounds
    # table still gets a sane minimum.
    MIN_DURATION: dict = {}

    def __init__(self, *, intelligence: Any, work_dir: str,
                 width: int = 1080, height: int = 998, fps: int = 25,
                 palette: Optional[list[str]] = None,
                 source_url: str = "", source_text: str = "",
                 source_title: str = "",
                 allow_ai_video: bool = False,
                 h3_budget: int = 0,
                 fullscreen_kinds: tuple = (),
                 frame_height: int = 1920) -> None:
        self.llm = intelligence
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.width, self.height, self.fps = width, height, fps
        self.palette = palette or []
        self.source_url = source_url
        self.source_text = source_text
        self.source_title = source_title
        self.allow_ai_video = allow_ai_video
        self.h3_budget = h3_budget
        self.h3_gen_size = 640
        self.h3_steps = 20
        self.h3_first_frame = ""
        self.subject_icon = ""
        self.fullscreen_kinds = frozenset(fullscreen_kinds)
        self.max_card_share = 0.20
        self.h3_placeholder = False
        self.frame_height = frame_height

    # -- capability gating ------------------------------------------------
    def available_types(self) -> list[str]:
        """Types this story could support at all.

        Gating here rather than in the prompt keeps the planner from choosing
        something the dispatcher cannot render — a page-roll with no URL, or a
        highlight with no article body.
        """
        # code_walkthrough is retired in favour of window_scene, which does the
        # same job strictly better: a real window with chrome and a brand field
        # rather than a bordered pane on a dark card. Leaving both on offer just
        # gave the planner a weaker option it kept choosing out of familiarity.
        types = ["stats_card", "headline_burst", "window_scene",
                 "split_screen", "cinematic_chart", "lockup", "flow_scene",
                 "terminal_scene", "device_scene", "comparison_scene"]
        # Real footage, when there is a key for it. Cheapest non-typographic
        # b-roll available: seconds to fetch, where generation costs minutes.
        try:
            from .stock import available as _stock_ok
            if _stock_ok():
                types.append("stock_clip")
        except Exception:              # noqa: BLE001 — optional capability
            pass
        # `highlight` — the phone mockup sweeping a sentence — is retired. It
        # rendered the source's own body copy at phone-screenshot scale inside a
        # bezel, so the actual words were small, the bezel ate frame, and the
        # result looked like a screenshot rather than a designed graphic. The
        # quote and headline compositions carry a sentence far better; annotate
        # still shows a claim in place on the real page when the point is that
        # it IS on the page.
        # `mechanism` is retired for the same reason code_walkthrough was: it
        # describes a process as stacked text, and flow_scene DRAWS it —
        # numbered nodes, connectors that trace themselves, a token moving
        # through. Offered side by side the planner kept choosing the text one
        # out of familiarity, which is exactly the "just text and design"
        # complaint. A process is the one thing a diagram states outright and a
        # paragraph only approximates, so there is no story where the text card
        # is the better answer.
        # Generated footage needs BOTH a host that can make it and an explicit
        # opt-in. The capability check alone is not enough: the weights are
        # installed on this host and the check passes, but the measured output is
        # a blue smear with no recognisable subject (see config.ai_video_enabled).
        # "Can render" and "should render" are different questions, and only the
        # second one protects the video.
        if self.allow_ai_video:
            try:
                from .aivideo import available as _ai_ok
                if _ai_ok():
                    types.append("ai_video")
            except Exception:              # noqa: BLE001 — optional capability
                pass
        # Generated footage via MiniMax H3. Offered only when it is enabled,
        # the service is up, and this video has not already spent its one clip:
        # at ~6.5 min each, a planner free to choose three would quadruple the
        # build time of the whole short.
        # Generated footage is not offered while it is being stubbed.
        #
        # A placeholder is the right trade for build time and the wrong thing
        # to fill a frame with when the point of the build is reviewing
        # graphics: ai_scene takes the whole frame, so choosing it spends a
        # full-frame slot on a card that says a render did not happen. Stock
        # is real imagery, arrives in seconds, and fits the same beats — so
        # with generation stubbed the slate should reach for it instead.
        if self.h3_budget > 0 and not self.h3_placeholder:
            try:
                from .h3_client import available as _h3_ok
                if _h3_ok():
                    types.append("ai_scene")
            except Exception:              # noqa: BLE001 — optional capability
                pass
        if self.source_url:
            # `pageroll` is retired from the slate. Its own catalogue entry
            # called it "the fallback — it always works and is the least
            # interesting", and it was there when there were few alternatives.
            # With eight designed compositions there is always something better,
            # and it carries a real cost: it films the LIVE page, so the last
            # build put a "Flash Sale — $100 off your Disrupt 2026 ticket"
            # advert on screen. annotate and macro still use the real page, but
            # they crop onto a located phrase, so page furniture never enters
            # frame. The presenter-span bed is a rendered reader page and is
            # ad-free by construction.
            types += ["annotate", "macro"]
        # tweet_reveal is offered only when the source plausibly quotes a
        # person; the planner is told never to invent one, and this stops it
        # being tempted.
        if any(m in self.source_text for m in ('" ', '," ', 'said', 'told')):
            types.append("tweet_reveal")
        return types

    # -- planning ---------------------------------------------------------
    async def _scene_prompt_for(self, narration: str) -> str:
        """A shot description for generated footage, from one beat's line.

        Kept deliberately concrete and physical. Asked for "a scene about X"
        the model returns abstractions — "innovation", "growth" — and the
        generator renders those as coloured smear, which is how the earlier
        LTX experiment failed. Naming a camera, a subject and a light source
        is what produces something recognisable.
        """
        # Deliberately short and noun-led. The same string is used two ways:
        # as a generation prompt, and as a STOCK SEARCH QUERY. A search engine
        # given 40 words of cinematography returns nothing, so the brief has to
        # be a subject a library would be indexed by, with the camera implied.
        prompt = (
            "Name ONE stock shot to sit under this line of narration:\n\n"
            f"  \"{narration}\"\n\n"
            "REGISTER — this is the part that goes wrong. Stock libraries are "
            "full of lifestyle imagery, and a literal keyword lands in it: "
            "'private rocket ride' returned a child with a toy rocket for a "
            "story about a space company's share sale. Name a shot from "
            "BUSINESS AND NEWS photography — trading floors, glass office "
            "towers, server racks, boardrooms, printed documents, city "
            "skylines, data centres, financial districts. Never homes, "
            "families, children, hobbies, celebrations, food, or anyone "
            "smiling at a camera.\n\n"
            "Prefer the shot's SETTING over its subject. A story about a "
            "company filing is not 'business people shaking hands'; it is "
            "'glass office tower at dusk' or 'stack of legal documents'. "
            "Settings are photographed well and generically; actions are "
            "photographed as stock cliche.\n\n"
            "It must be physical and filmable — no abstractions ('growth', "
            "'innovation'), no text or logos in frame, no recognisable faces. "
            "Answer in 3 to 6 words as a noun phrase, the way a picture editor "
            "would search. Reply with the phrase alone."
        )
        try:
            resp = await self.llm.messages.create(
                model="claude-sonnet-4-5", max_tokens=200,
                messages=[{"role": "user", "content": prompt}])
            return " ".join((resp.content[0].text or "").split())[:80]
        except Exception as exc:              # noqa: BLE001 — optional
            logger.warning("scene prompt failed (%s)", str(exc)[:100])
            return ""

    async def plan(self, beats: list[dict], *, max_slots: int = 5,
                   max_per_kind: int = 2) -> list[Slot]:
        """Choose a type and build its payload for every beat worth filling.

        ``max_per_kind`` is what actually keeps the video from becoming a tour
        of one graphic. A total cap cannot express that: four clips of which
        three are page-rolls is repetitive, while ten clips spread over eight
        types is not. Capping per kind lets the slate grow without letting any
        single look dominate — and page footage is the one it most often would,
        because every story has a URL and not every story has a statistic.
        """
        avail = self.available_types()
        beat_text = "\n".join(
            f'  beat {i} ({b["start"]:.1f}s, {b["duration"]:.1f}s): "{b["narration"]}"'
            for i, b in enumerate(beats))

        prompt = (
            f"SOURCE TITLE: {self.source_title}\n\n"
            f"SOURCE TEXT:\n{self.source_text[:9000]}\n\n"
            f"AVAILABLE B-ROLL TYPES:\n{_catalog_text(avail)}\n\n"
            f"BEATS TO FILL:\n{beat_text}\n\n"
            f"Choose a type and build its payload for each beat. At most "
            f"{max_slots} slots, and NO MORE THAN {max_per_kind} slots of any "
            f"one kind — a video that cuts to the same kind of graphic four "
            f"times feels like a tour of one template. Prefer a different kind "
            f"for each beat, chosen for what that beat is actually about. "
            f"Fewer slots is fine if a beat is genuinely better left on the "
            f"presenter, but a beat with something concrete to show should get "
            f"a graphic: a held shot lasting more than ~4s reads as a stall.\n\n"
            # Measured, not guessed. Over five planning runs on the same script
            # the slate came back 63% text cards, headline_burst alone took
            # 25.7% and appeared up to three times in one video, terminal_scene
            # was chosen once and device_scene never — on a story about a feed
            # and a ranking, which is precisely what device_scene is for.
            # Offered a menu with no weighting, the planner reaches for the
            # card that fits any beat rather than the scene that fits this one.
            f"COMPOSITION RULES — these decide whether the video looks made or "
            f"generated:\n"
            f"* SCENES BEFORE CARDS. stock_clip, ai_scene, terminal_scene, "
            f"device_scene, window_scene, flow_scene, comparison_scene "
            f"are SCENES: generated footage, a real "
            f"terminal, a real phone, a real window, a real diagram, each shot "
            f"with a moving camera. The rest are cards with words on them. At "
            f"AT MOST ONE IN FIVE slots may be a card. Everything else must "
            f"be a scene. stock_clip in particular fits almost any beat — it "
            f"falls through to an animated photograph when no footage exists, "
            f"so 'there is no video of this' is not a reason to reach for "
            f"type.\n"
            f"* USE ai_scene when it is offered. It is generated video — the "
            f"only type that puts real moving imagery on screen rather than "
            f"another rectangle of type — and it fits ANY story, including "
            f"ones with no software or product to show: an abstract or "
            f"atmospheric shot of the subject matter always exists. Stories "
            f"about money, companies, policy or people have no terminal and no "
            f"app, and those are exactly the videos that otherwise come out as "
            f"nothing but text cards.\n"
            f"* AT MOST ONE headline_burst in the whole video. It is a title "
            f"card; a second one is a second title.\n"
            f"* If the story involves code, a repo, a file or a command, one "
            f"slot MUST be terminal_scene. If it involves an app, a feed, a "
            f"ranking or anything a user sees on a phone, one slot MUST be "
            f"device_scene. Both, when both are true.\n"
            f"* Do not describe a thing in text when you can show the thing."
        )
        try:
            resp = await self.llm.messages.create(
                model="claude-sonnet-4-5", max_tokens=3000, system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema",
                                          "schema": _PLAN_SCHEMA}},
            )
            data = json.loads(resp.content[0].text)
        except Exception as exc:                   # noqa: BLE001 — optional stage
            raise DirectorError(f"planning failed: {exc}") from exc

        slots: list[Slot] = []
        used_kind: dict[str, int] = {}
        used_beat: set[int] = set()
        for item in (data.get("slots") or []):
            if len(slots) >= max_slots:
                break
            try:
                b = int(item["beat"])
                kind = str(item["kind"]).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= b < len(beats)) or kind not in avail:
                logger.warning("plan dropped: beat=%s kind=%r not available",
                               item.get("beat"), kind)
                continue
            # The prompt asks for variety; this enforces it. A prompt-only rule
            # is a request, and the one time it is ignored is the video that
            # ships as four page-rolls.
            # The expensive type has its own cap, independent of max_per_kind.
            if kind == "ai_scene" and used_kind.get(kind, 0) >= self.h3_budget:
                logger.info("plan dropped: ai_scene budget of %d already spent",
                            self.h3_budget)
                continue
            if used_kind.get(kind, 0) >= max_per_kind:
                logger.info("plan dropped: %s already used %d times",
                            kind, max_per_kind)
                continue
            # Two graphics anchored to the same beat would be placed almost on
            # top of each other, and the assembler would slide the second one
            # into the next beat's narration — illustrating the wrong sentence.
            if b in used_beat:
                logger.info("plan dropped: beat %d already has a graphic", b)
                continue
            used_kind[kind] = used_kind.get(kind, 0) + 1
            used_beat.add(b)
            slot = Slot(
                index=len(slots), kind=kind, start=beats[b]["start"],
                duration=beats[b]["duration"], narration=beats[b]["narration"],
                payload=item.get("payload") or {}, why=str(item.get("why", ""))[:220],
            )
            # Length is a function of what is ON the card, not of the cadence
            # slot it happens to land in. A four-word headline and a
            # twenty-five-word quote used to get the same 2.6s.
            slot.duration = max(readable_duration(kind, _props_for(slot)),
                                self.MIN_DURATION.get(kind, 0.0))
            slots.append(slot)

        # Generated footage is GUARANTEED, not hoped for.
        #
        # Naming ai_scene in the rules raises the odds; it does not make it
        # certain, and a video with zero generated shots was the specific
        # complaint. Every other type here is a rectangle with type in it, so
        # ai_scene is the only thing on the menu that puts moving imagery on
        # screen — leaving that to chance is what produced slate after slate of
        # text cards on stories that had no software to show.
        #
        # The weakest CARD is converted, never a scene: the point is to reduce
        # the number of typographic panels, so trading a card for footage is
        # the whole move, and trading a scene for one would be a lateral step.
        # Enforce the scene floor in CODE, not just in the prompt.
        #
        # The rules ask for at least half the slots to be scenes and the
        # planner does not comply: on a story with no software to point a
        # camera at, the only scene types that fit are ai_scene, flow_scene and
        # comparison_scene, and it reaches for typographic cards instead. A
        # measured slate came back 2 scenes out of 6 with the rule stated
        # plainly in the prompt.
        #
        # Generated footage is the lever because it fits ANY subject — there is
        # always an atmospheric shot of a company, a market or a decision —
        # whereas a terminal or a phone requires the story to contain one. So
        # surplus cards become ai_scene until the floor is met or the budget
        # runs out. Cost is real (~10 min a clip), which is what the budget is
        # for; a video that is nothing but text panels is the thing being paid
        # to avoid.
        # At most a fifth of the slate may be typographic. Expressed as a
        # floor on scenes so one number governs, and computed with ceil so a
        # five-slot slate allows one card rather than rounding to two.
        import math as _math
        want = len(slots) - _math.floor(len(slots) * self.max_card_share)
        used_h3 = sum(1 for x in slots if x.kind == "ai_scene")
        have = sum(1 for x in slots if x.kind in _SCENE_KINDS)
        cards = sorted((x for x in slots if x.kind not in _SCENE_KINDS),
                       key=lambda x: -x.duration)
        try:
            from .stock import available as _stock_ok
            can_stock = _stock_ok()
        except Exception:                          # noqa: BLE001 — optional
            can_stock = False

        for victim in cards:
            if have >= want:
                break
            desc = await self._scene_prompt_for(victim.narration)
            if not desc:
                continue
            # Real footage first, generation second.
            #
            # Both put moving imagery on screen, so for the floor's purposes
            # they are interchangeable — but one returns in seconds for free
            # and the other costs ~10 minutes of GPU. Spending the expensive
            # option first would mean burning the budget on beats that a
            # stock search would have covered, then having nothing left for
            # the ones it cannot.
            if can_stock:
                kind, payload = "stock_clip", {"query": desc}
            elif used_h3 < self.h3_budget and not self.h3_placeholder:
                kind, payload = "ai_scene", {"scene": desc}
                used_h3 += 1
            else:
                break
            logger.info("Scene floor: converting the %s at %.1fs into %s "
                        "(%d/%d scenes)", victim.kind, victim.start, kind,
                        have + 1, want)
            victim.kind = kind
            victim.payload = payload
            victim.why = f"scene floor: {kind}"
            victim.duration = max(
                readable_duration(kind, _props_for(victim)),
                self.MIN_DURATION.get(kind, 0.0))
            have += 1
        if have < want:
            logger.info("Scene floor not met: %d/%d — the generation budget "
                        "of %d is the binding constraint",
                        have, want, self.h3_budget)

        if not slots:
            raise DirectorError("planner returned no usable slots")
        kinds = ", ".join(s.kind for s in slots)
        logger.info("B-roll plan: %d slots across %d kinds — %s",
                    len(slots), len(used_kind), kinds)
        for s in slots:
            logger.info("  %-16s @%5.1fs  %s", s.kind, s.start, s.why)
        return slots

    # -- rendering --------------------------------------------------------
    def target_size(self, kind: str, fullscreen: Optional[bool] = None) -> tuple:
        """Canvas for a slot: the content panel, or the whole frame.

        Takes the SLOT's decision when it has one. Sizing from the kind alone
        meant every eligible clip rendered 1920 tall, including the ones the
        full-frame budget then denied — and a 1920-tall clip in a 998 panel is
        cropped, not fitted, so it lost its title off the top edge.
        """
        full = (kind in self.fullscreen_kinds) if fullscreen is None else fullscreen
        if full:
            return self.width, self.frame_height
        return self.width, self.height

    async def render(self, slot: Slot) -> Slot:
        out = str(self.work_dir / f"broll_{slot.index:02d}_{slot.kind}.mp4")
        try:
            path = await self._dispatch(slot, out)
            # A Remotion composition is authoritative about its own frame: it
            # fills the canvas by construction and animates throughout. Both
            # backstops were built for HyperFrames output and would now do harm
            # — auto-framing would re-crop a deliberate layout, and the push
            # would shave 4% off edges the design placed on purpose.
            designed = slot.kind in _remotion_kinds()
            cw, ch = self.target_size(slot.kind)
            slot.path = _normalise_clip(
                path, slot.duration, self.fps, cw, ch,
                autoframe=not designed and slot.kind not in _SELF_FRAMED,
                push=not designed)
        except Exception as exc:                   # noqa: BLE001 — per-slot isolation
            slot.error = str(exc)[:300]
            logger.warning("b-roll %s failed: %s", slot.kind, slot.error)
        return slot

    async def render_all(self, slots: list[Slot], *,
                         concurrency: int = 3) -> list[Slot]:
        sem = asyncio.Semaphore(max(1, concurrency))

        async def one(s: Slot) -> Slot:
            async with sem:
                return await self.render(s)

        done = await asyncio.gather(*(one(s) for s in slots))
        ok = sum(1 for s in done if s.path)
        logger.info("B-roll: %d/%d rendered", ok, len(done))
        return list(done)

    async def _dispatch(self, slot: Slot, out: str) -> str:
        k, p = slot.kind, slot.payload

        if k == "highlight":
            from .highlight import build_highlight_clip, synth_phrases, _paragraphs
            sent = (p.get("sentence") or "").strip()
            paras = _paragraphs(self.source_text, title_hint=self.source_title)
            focus = next((i for i, para in enumerate(paras)
                          if sent[:40].lower() in para.lower()), -1)
            if not sent or focus < 0:
                raise DirectorError("highlight sentence not found verbatim "
                                    "in the source")
            return await build_highlight_clip(
                source_text=self.source_text, source_title=self.source_title,
                script={"script": slot.narration},
                words=synth_phrases(sent, slot.duration),
                out_path=out, duration_s=slot.duration,
                palette=self.palette, focus_paragraph=focus)

        if k == "stock_clip":
            from . import stock
            q = str(p.get("query") or "").strip()
            if not q:
                raise DirectorError("stock_clip needs a query")
            w, h = self.target_size(k, getattr(slot, "fullscreen", None))
            # Footage when it exists, an animated photograph when it
            # does not. Video coverage is absent for most specific
            # subjects, and that is precisely when a card would
            # otherwise take the slot.
            return await asyncio.to_thread(
                stock.fetch_any, q, out, duration_s=slot.duration,
                width=w, height=h, fps=self.fps)

        if k == "ai_scene":
            scene_txt = str(p.get("scene") or p.get("prompt") or "").strip()
            if self.h3_placeholder:
                # The other stage that does not belong in an iteration loop.
                # Ten minutes of GPU per clip, and while the graphics are
                # being worked on the only thing that matters about it is
                # where it sits and how long it runs.
                from .placeholder import card
                w, h = self.target_size(k, getattr(slot, "fullscreen", None))
                logger.info("ai_scene placeholder (~10 min saved): %s",
                            scene_txt[:70])
                return card(out, width=w, height=h, fps=self.fps,
                            duration_s=slot.duration,
                            label="GENERATED FOOTAGE — NOT RENDERED",
                            detail=scene_txt,
                            cost="MiniMax H3  ~10 min GPU",
                            accent="0xF06BB0")

            from . import h3_client
            scene = str(p.get("scene") or p.get("prompt") or "").strip()
            if not scene:
                raise DirectorError("ai_scene needs a scene description")
            return await asyncio.to_thread(
                h3_client.render,
                scene=scene, out_path=out, duration_s=slot.duration,
                width=self.target_size(k)[0], height=self.target_size(k)[1],
                fps=self.fps,
                gen_size=self.h3_gen_size, steps=self.h3_steps,
                seed=1000 + slot.index, first_frame=self.h3_first_frame or None)

        if k == "ai_video":
            from .aivideo import build_ai_clip
            scene = str(p.get("scene") or p.get("prompt") or "").strip()
            if not scene:
                raise DirectorError("ai_video needs a scene description")
            # A consistent grade across every generated clip in one video, so
            # two of them do not look like they came from different films.
            suffix = ("cinematic, shallow depth of field, moody volumetric "
                      "lighting, subtle film grain, no text")
            return build_ai_clip(
                prompt=scene, out_path=out, duration_s=slot.duration,
                width=self.width, height=self.height, fps=self.fps,
                style_suffix=suffix, seed=1000 + slot.index)

        if k in ("annotate", "macro"):
            from .annotate import build_annotated_clip
            return build_annotated_clip(
                url=self.source_url, out_path=out,
                phrase=str(p.get("phrase") or p.get("target") or ""),
                label=str(p.get("label", "")),
                mode=("box" if k == "annotate" else "macro"),
                duration_s=slot.duration, width=self.width,
                height=self.height, fps=self.fps,
                work_dir=str(self.work_dir), palette=self.palette)

        if k == "pageroll":
            from .pageroll import build_rolls
            rolls = build_rolls(self.source_url, str(self.work_dir / "page"),
                                count=1, duration=slot.duration,
                                width=self.width, height=self.height,
                                fps=self.fps, half_height=self.height)
            if not rolls:
                raise DirectorError("page capture produced nothing")
            os.replace(rolls[0].path, out)
            return out

        # Everything else goes to HyperFrames rather than the old broll_gen
        # generators. A deliberate reversal of the earlier plan:
        #
        #  * split_screen there is a COMPOSER that only delegates to
        #    browser_visit / image_montage / stats_card — all network-bound, and
        #    the wrong abstraction for an open-vs-closed comparison card.
        #  * stats_card and friends import `anthropic` at module scope and were
        #    written against the CommonCreed palette.
        #  * HyperFrames already takes the story's palette, composes for the
        #    real panel aspect, and every clip it makes is vision-reviewed and
        #    re-rendered when broken.
        #
        # Two design systems would mean two quality bars. This keeps one.
        return await self._design(slot, out)

    async def _design(self, slot: Slot, out: str) -> str:
        """Render a slot as a designed motion graphic, via Remotion.

        This previously asked `claude -p` to author fresh HyperFrames animation
        code for every graphic. That could not hold a quality bar, for reasons
        that were structural rather than fixable by prompting: every clip was a
        one-off so nothing was consistent between them; nothing tied the
        animation to the clip length, so graphics froze for up to 80% of their
        runtime; and nothing enforced legibility, so content filled a quarter of
        the panel at type too small to read on a phone.

        The Remotion compositions are hand-built components in which those
        properties hold by construction — the build phase is a fraction of the
        clip, sizes derive from the canvas, and text is fitted by measuring the
        real font. The planner supplies only DATA. Rendering is also about 35s
        for eight clips rather than ten minutes each, which is what makes
        iterating on a video practical at all.
        """
        from . import remotion_client

        w, h = self.target_size(slot.kind, getattr(slot, 'fullscreen', None))
        props = _props_for(slot)
        # Which mark a panel wears depends on what the panel is SAYING.
        #
        # A designed panel asserts a fact about the SUBJECT — "X open sourced
        # its ranking algorithm" is a statement about X, and stamping the
        # publisher's logo on it made the video look like a TechCrunch promo
        # for a story that is not about TechCrunch.
        #
        # The reader bed is the opposite case and is deliberately left alone:
        # it quotes the article's own sentences verbatim, so the publisher's
        # mark there is correct attribution, and swapping in the subject's
        # would put someone else's words under X's logo.
        if self.subject_icon:
            props["icon"] = self.subject_icon
        return await asyncio.to_thread(
            remotion_client.render,
            kind=slot.kind,
            props=props,
            out_path=out,
            duration_s=slot.duration,
            width=w,
            height=h,
            fps=self.fps,
            palette=self.palette,
        )


def _content_box(path: str, *, samples: int = 10) -> Optional[tuple]:
    """Union bounding box of everything that is not background, over the clip.

    Sampled across the WHOLE clip rather than from one frame: these graphics
    build up element by element, so the first frame's box is just the first
    element and cropping to it would cut off everything that arrives later.

    Returns (x0, y0, x1, y1) in pixels, or None if it cannot be determined.
    """
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return None

    dur = _probe_duration(path)
    if not dur:
        return None

    tmp = Path(path).with_name(Path(path).stem + "_box")
    tmp.mkdir(exist_ok=True)
    boxes = []
    try:
        for i in range(samples):
            t = dur * (i + 0.5) / samples
            frame = tmp / f"{i:02d}.png"
            r = subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", path,
                 "-vframes", "1", str(frame)],
                capture_output=True, text=True)
            if r.returncode != 0 or not frame.exists():
                continue
            a = np.asarray(Image.open(frame).convert("L")).astype(np.int16)
            # Background is whatever the corners agree on — these panels are a
            # flat dark field, and a fixed threshold would fail on a light one.
            bg = int(np.median([a[0, 0], a[0, -1], a[-1, 0], a[-1, -1]]))
            mask = np.abs(a - bg) > 26
            if mask.sum() < 200:
                continue
            ys, xs = np.nonzero(mask)
            boxes.append((xs.min(), ys.min(), xs.max(), ys.max()))
    finally:
        for f in tmp.glob("*.png"):
            f.unlink(missing_ok=True)
        tmp.rmdir()

    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path], capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


# Types that frame themselves and must NOT be auto-framed again.
#
# These crop to something specific: annotate and macro land on a located phrase,
# highlight sweeps a sentence in a phone mockup, pageroll frames a page region.
# Auto-framing on top of that fights the decision the generator already made —
# and on annotate it actively broke the clip, because annotate DIMS everything
# except the highlighted phrase, so the content detector saw only the bright band
# and zoomed into it, clipping the surrounding words mid-letter. The dimmed
# context is the point of that type: it shows the claim in place.
_SELF_FRAMED = frozenset({"annotate", "macro", "highlight", "pageroll",
                          "ai_video", "ai_scene"})


def _normalise_clip(path: str, want: float, fps: int,
                    width: int, height: int, *, autoframe: bool = True,
                    push: bool = True) -> str:
    """Force a clip to exactly ``want`` seconds at exactly ``width``x``height``.

    Two separate lies to correct:

    * DURATION. Generators return whatever their content needed. One asked for
      6.0s came back at 4.0s because xfade transitions consume the tail. The
      assembler places clips at computed offsets, so a short clip leaves a gap
      and everything after it drifts.

    * GEOMETRY. `phone_highlight` always renders 1080x1920 — it is a phone
      mockup and that is its native frame — while designs render at the content
      panel's 1080x998. Stacking mixed heights fails outright in ffmpeg, so
      every clip is conformed to the panel before it reaches the compositor.
      Vertical content is CROPPED to the panel from the top rather than
      squashed: a squashed phone mockup looks broken, a cropped one just shows
      less of the page.
    """
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True).stdout.split()
        vals = ",".join(probe).replace("\n", ",").split(",")
        have_w, have_h = int(vals[0]), int(vals[1])
        have_d = float(vals[2])
    except (ValueError, IndexError, subprocess.SubprocessError) as exc:
        logger.warning("cannot probe %s (%s) — leaving as-is",
                       Path(path).name, exc)
        return path

    needs_geom = (have_w, have_h) != (width, height)
    needs_time = abs(have_d - want) >= 0.08

    filters = []

    # AUTO-FRAME to the content.
    #
    # Measured on the shipped clips: content spanned only 26-29% of the panel
    # height and ink covered 2-5% of pixels — a small caption floating in a large
    # black field. In a half-panel on a phone that type is unreadable, which is
    # the whole job of these graphics. The design system is also told to fill its
    # canvas now, but this is the backstop that does not depend on it complying.
    box = _content_box(path) if autoframe else None
    if box:
        bx0, by0, bx1, by1 = box
        bw, bh = max(1, bx1 - bx0), max(1, by1 - by0)
        if bh < have_h * 0.72:
            # Pad around the content so it does not touch the panel edge, then
            # widen to the panel's aspect so nothing is stretched.
            pad = int(min(have_w, have_h) * 0.045)
            cx, cy = bx0 + bw / 2, by0 + bh / 2
            target_ar = width / height
            cw, ch = bw + 2 * pad, bh + 2 * pad
            if cw / ch < target_ar:
                cw = ch * target_ar
            else:
                ch = cw / target_ar
            cw, ch = min(cw, have_w), min(ch, have_h)
            cx0 = int(max(0, min(cx - cw / 2, have_w - cw)))
            cy0 = int(max(0, min(cy - ch / 2, have_h - ch)))
            filters.append(f"crop={int(cw)}:{int(ch)}:{cx0}:{cy0}")
            logger.info("%s: auto-framed content from %d%% to ~%d%% of panel "
                        "height", Path(path).name,
                        int(bh / have_h * 100), int(bh / ch * 100))
            needs_geom = True

    if needs_geom:
        if have_h > height * 1.3:
            # Tall source (phone mockup): scale to width, then take the top of
            # the frame — the headline and opening lines are what matter.
            filters.append(f"scale={width}:-2:flags=lanczos,"
                           f"crop={width}:{height}:0:0")
        else:
            filters.append(f"scale={width}:{height}:"
                           f"force_original_aspect_ratio=increase,"
                           f"crop={width}:{height}")
    if have_d < want:
        # Hold the last frame rather than looping: a loop restarts an animation
        # mid-beat, which reads as a glitch.
        filters.append(f"tpad=stop_mode=clone:stop_duration={want - have_d:.3f}")

    # NEVER FREEZE. A slow continuous push across the whole clip, applied after
    # the padding so the cloned tail moves too.
    #
    # Measured on the shipped clips, the animations stop long before the clip
    # does: stats_card's last motion was at 0.52s of 2.60s and headline_burst's
    # at 0.72s of 2.60s — 80% and 72% of their screen time was a still image.
    # Some of that is clone-padding a short render, some is the graphic's own
    # animation finishing early. Either way a static frame in a short reads as a
    # stall, and the fix does not need to know which cause applied.
    #
    # 4% over the clip is deliberately below conscious notice: the intent is that
    # the frame is never dead, not that the viewer sees a zoom.
    if push:
        frames = max(2, int(round(want * fps)))
        filters.append(
            f"zoompan=z='1+0.04*on/{frames}':x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps={fps}")

    vf = ",".join(filters) if filters else "null"

    fixed = str(Path(path).with_name(Path(path).stem + "_fit.mp4"))
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", path, "-vf", vf,
         "-t", f"{want:.3f}", "-r", str(fps), "-c:v", "libx264", "-crf", "18",
         "-pix_fmt", "yuv420p", "-an", fixed],
        capture_output=True, text=True)
    if r.returncode != 0:
        logger.warning("conform failed for %s: %s",
                       Path(path).name, r.stderr[-200:])
        return path
    logger.info("%s: %dx%d %.2fs -> %dx%d %.2fs", Path(path).name,
                have_w, have_h, have_d, width, height, want)
    return fixed


# ------------------------------------------------------------------ props
# Exactly which payload keys each type needs, handed to the planner verbatim.
#
# Kept beside the catalogue rather than inside it so the two read separately:
# the catalogue answers "which type fits this beat", this answers "what do I
# have to write for it". Vague payload guidance is why slots came back with a
# `label` where the component wanted a `value`, and a card rendered with an
# empty hero.
PAYLOAD_SPEC: dict[str, str] = {
    "highlight": '"sentence": one exact sentence copied from the source',
    "stats_card": '"value": the figure exactly as written (e.g. "10-15x"), '
                  '"label": a short support line, "kicker": 1-2 word eyebrow',
    "headline_burst": '"text": the claim, 4-10 words, "kicker": 1-2 word eyebrow',
    "tweet_reveal": '"author": full name, "role": their title, "body": the quote',
    "code_walkthrough": '"filename": path or language, "lines": UP TO 7 lines '
                        '(prefix "+ " or "- " for a diff), "caption": one line',
    "split_screen": '"kicker", "left_title", "left_lines": [ONE short phrase], '
                    '"right_title", "right_lines": [ONE short phrase]',
    "cinematic_chart": '"title", "bars": [{"label", "value": a number, '
                       '"display": as written}] — 2 to 4 bars',
    "mechanism": '"title", "steps": UP TO 4 short steps, "result": what it produces',
    "annotate": '"phrase": one exact phrase present on the page',
    "macro": '"phrase": one small element visible on the page',
    "ai_video": '"scene": a described scene, never a concept',
    "stock_clip": '"query": 3-6 words naming a filmable SHOT from BUSINESS or NEWS photography, e.g. "stock exchange trading floor", "glass office tower dusk", "server racks data centre". Name the SETTING, not the action. Never lifestyle: no homes, families, children, hobbies, or people smiling at camera. No abstractions.',
    "comparison_scene": '"kicker": 2-4 words. "title": 2-5 words. "items": 2-3 of {"label": UNDER 18 CHARS, "value": a NUMBER only, "prefix": e.g. "$", "suffix": e.g. "B", "lead": true for the story subject}. "note": under 45 chars',
    "terminal_scene": '"title": the repo or directory, "lines": 4-6 lines, each {"text": UNDER 26 CHARS, "kind": one of command|out|ok|warn}, "focus_line": index of the payoff line',
    "device_scene": '"title": 2-4 words, "app": the surface name e.g. "For You", "items": 3-4 {"text": UNDER 30 CHARS, "score": short number, "mark": up|down}',
    "flow_scene": '"title": 2-5 words. "input": what enters, 3-6 words. "stages": 3-5 stages, EACH UNDER 26 CHARACTERS. "result": what comes out, UNDER 22 CHARACTERS',
    "window_scene": '"title": 1-4 words, editorial. "windowTitle": the file or repo label. "lines": UP TO 6 short lines, prefix "+ " or "- " for a diff',
    "ai_scene": '"scene": a described physical place and camera move, 12-30 words, no text or logos in it',
    "pageroll": "(no payload needed)",
    "lockup": '"title": the name (1-3 words), "badge": a short pill, '
              '"typed": one sentence that types in, "kicker": 1-2 word eyebrow',
}


def _remotion_kinds() -> frozenset:
    """Slot kinds rendered by Remotion rather than from a page capture."""
    from .remotion_client import COMPOSITIONS
    return frozenset(COMPOSITIONS)


def _clean(value: Any, limit: int = 240) -> str:
    """Trim a planner string, collapsing whitespace."""
    return " ".join(str(value or "").split())[:limit]


def _props_for(slot: "Slot") -> dict:
    """Map a planned slot's payload onto its composition's props.

    Deliberately explicit rather than passing the payload straight through. The
    planner writes in the catalogue's vocabulary ("text", "label", "left_lines")
    while the components have their own, so translating here means a payload key
    changing shape breaks in one readable place instead of rendering a card with
    `undefined` where a figure should be.
    """
    k, p = slot.kind, slot.payload

    if k == "stats_card":
        return {
            "value": _cap_words(_clean(p.get("value"), 40), _WORD_CAPS["value"]),
            "support": _cap_words(_clean(p.get("label") or p.get("support"), 120),
                                  _WORD_CAPS["support"]),
            "kicker": _clean(p.get("kicker"), 28),
        }

    if k == "headline_burst":
        text = _cap_words(_clean(p.get("text") or p.get("headline"), 160),
                          _WORD_CAPS["headline"])
        words = text.split()
        return {
            "headline": text,
            "kicker": _clean(p.get("kicker"), 28),
            # Colour the back half of the line so the emphasis lands on the
            # claim rather than the subject, without the planner marking it up.
            "accentFrom": max(1, len(words) // 2) if len(words) > 2 else None,
            "support": _clean(p.get("support"), 140),
        }

    if k == "mechanism":
        return {
            "title": _clean(p.get("title") or p.get("label"), 60),
            "steps": [_cap_words(_clean(x, 80), _WORD_CAPS["step"])
                      for x in (p.get("steps") or []) if _clean(x)],
            "result": _cap_words(_clean(p.get("result") or p.get("output"), 90),
                                 _WORD_CAPS["result"]),
        }

    if k == "split_screen":
        def side(title_key: str, lines_key: str, value_key: str, default: str) -> dict:
            lines = p.get(lines_key) or []
            first = lines[0] if lines else p.get(value_key)
            return {"label": _clean(p.get(title_key) or default, 24),
                    "value": _cap_words(_clean(first, 80), _WORD_CAPS["value"])}
        return {
            "kicker": _clean(p.get("kicker") or p.get("title"), 28),
            "left": side("left_title", "left_lines", "left_value", "Before"),
            "right": side("right_title", "right_lines", "right_value", "After"),
        }

    if k == "terminal_scene":
        raw = p.get("lines") or []
        lines = []
        for item in raw[:6]:
            if isinstance(item, str):
                item = {"text": item, "kind": "out"}
            txt = _clean(item.get("text"), 26)
            if not txt:
                continue
            kind = str(item.get("kind") or "out").lower()
            if kind not in ("command", "out", "ok", "warn"):
                kind = "out"
            lines.append({"text": txt, "kind": kind})
        out = {"title": _clean(p.get("title"), 30), "lines": lines}
        fl = p.get("focus_line", p.get("focusLine"))
        if isinstance(fl, int) and 0 <= fl < len(lines):
            out["focusLine"] = fl
        return out

    if k == "stock_clip":
        return {"query": _cap_words(_clean(p.get("query") or p.get("scene"), 60), 6)}

    if k == "comparison_scene":
        items = []
        for it in (p.get("items") or [])[:3]:
            if not isinstance(it, dict):
                continue
            lab = _clean(it.get("label"), 18)
            try:
                val = float(it.get("value"))
            except (TypeError, ValueError):
                continue
            if not lab:
                continue
            items.append({"label": lab, "value": val,
                          "prefix": _clean(it.get("prefix"), 3),
                          "suffix": _clean(it.get("suffix"), 3),
                          "lead": bool(it.get("lead"))})
        return {
            "kicker": _cap_words(_clean(p.get("kicker"), 30), 4),
            "title": _cap_words(_clean(p.get("title"), 40), 5),
            "items": items,
            "note": _clean(p.get("note"), 45),
        }

    if k == "device_scene":
        items = []
        for item in (p.get("items") or [])[:4]:
            if isinstance(item, str):
                item = {"text": item}
            txt = _clean(item.get("text"), 30)
            if not txt:
                continue
            mark = str(item.get("mark") or "").lower()
            items.append({
                "text": txt,
                "score": _clean(item.get("score"), 8),
                "mark": mark if mark in ("up", "down") else None,
            })
        return {
            "title": _cap_words(_clean(p.get("title"), 40), 4),
            "app": _clean(p.get("app"), 18),
            "items": items,
        }

    if k == "flow_scene":
        return {
            "title": _cap_words(_clean(p.get("title"), 50), 5),
            "input": _cap_words(_clean(p.get("input"), 60), 6),
            # 26 chars keeps each stage on ONE line in the node box.
            "stages": [_clean(x, 26) for x in (p.get("stages") or []) if _clean(x)][:5],
            # Two lines in the banner is the hard budget; 22 chars keeps it
            # there without the fitter having to shrink to unreadable.
            "result": _cap_words(_clean(p.get("result") or p.get("output"), 22), 4),
        }

    if k == "window_scene":
        return {
            "title": _cap_words(_clean(p.get("title"), 60), 5),
            "windowTitle": _clean(p.get("windowTitle") or p.get("filename"), 44),
            # Capped by CHARACTERS, not words. A path like
            # "+ ranking/eval-harness/features.json" is two words and far too
            # wide for a monospace window at panel scale — the first build
            # clipped its lines at the right edge.
            "lines": [_clean(x, 30) for x in (p.get("lines") or []) if _clean(x)][:6],
        }

    if k == "code_walkthrough":
        return {
            "filename": _clean(p.get("filename") or p.get("language"), 40),
            "lines": [_clean(x, 52) for x in (p.get("lines") or []) if _clean(x)],
            "caption": _cap_words(_clean(p.get("caption") or p.get("label"), 90),
                                  _WORD_CAPS["caption"]),
        }

    if k == "cinematic_chart":
        bars = []
        for b in (p.get("bars") or p.get("series") or []):
            if not isinstance(b, dict):
                continue
            try:
                val = float(str(b.get("value", "")).replace(",", "").strip())
            except (TypeError, ValueError):
                continue
            bars.append({
                "label": _clean(b.get("label"), 24),
                "value": val,
                "display": _clean(b.get("display") or b.get("value"), 16),
            })
        return {"kicker": _clean(p.get("title") or p.get("kicker"), 28),
                "bars": bars}

    if k == "tweet_reveal":
        return {
            "quote": _cap_words(_clean(p.get("body") or p.get("quote"), 260),
                                _WORD_CAPS["quote"]),
            "author": _clean(p.get("author"), 40),
            "role": _clean(p.get("role") or p.get("handle"), 40),
        }

    # lockup, and the safe shape for anything new: a name, a badge, a line.
    return {
        "title": _clean(p.get("title") or p.get("value") or slot.kind, 32),
        "badge": _clean(p.get("badge") or p.get("label"), 34),
        "typed": _cap_words(
            _clean(p.get("typed") or p.get("support") or slot.narration, 240),
            _WORD_CAPS["typed"]),
        "kicker": _clean(p.get("kicker"), 28),
    }


# ------------------------------------------------------- readable duration
# On-screen reading rate, words per second.
#
# Silent reading of body text runs 3.3-5 w/s. Large display type in short
# bursts sits at the top of that, and the narration is speaking the same idea
# underneath, which aids comprehension. 4.0 is deliberately at the confident
# end: over-long clips cost cadence, and the narration keeps the viewer moving.
_READ_RATE = 4.0
# Time to notice a cut and orient before any reading starts.
_RECOGNITION_S = 0.5
# A beat of held frame after the last word is read, so the cut does not clip
# the end of a sentence.
_TAIL_S = 0.7

# Per type: (minimum, maximum) seconds. The maximum matters as much as the
# minimum — a mechanism with four steps computes past 8s, which is a sixth of
# the whole video on one graphic.
# Ceilings measured against a reference short rather than chosen.
#
# It cuts 40 times in 57 seconds and holds nothing longer than 3.84s. These
# were letting a single graphic sit for 7.5-8s, which is twice its longest
# shot and the reason this pipeline measured a 5.00s average against its
# 1.43s. Every composition here scales its own animation to the duration it
# is given — they animate on normalised time — so a shorter slot makes the
# build faster and more urgent rather than truncating it.
#
# The floors matter as much as the ceilings: a terminal still needs long
# enough to be recognised as a terminal.
_DURATION_BOUNDS: dict[str, tuple] = {
    "stats_card": (2.2, 3.2),
    "headline_burst": (2.2, 3.2),
    "lockup": (2.6, 3.6),
    "mechanism": (3.0, 4.2),
    "split_screen": (2.8, 3.8),
    "tweet_reveal": (3.0, 4.2),
    "code_walkthrough": (3.0, 4.2),
    "cinematic_chart": (2.8, 3.8),
    "annotate": (2.4, 3.4),
    "macro": (2.0, 3.0),
    "pageroll": (2.2, 3.2),
    "ai_video": (2.6, 3.6),
    # Capped at 4s deliberately. Generation time scales with frame count, and
    # at ~2 min per second of output the difference between a 4s and a 6s clip
    # is four minutes of GPU on the single most expensive item in the build.
    "ai_scene": (2.8, 4.0),
    "window_scene": (3.0, 4.2),
    "flow_scene": (3.4, 4.5),
    # A terminal needs time to type and be read; rushing it defeats it.
    "terminal_scene": (3.4, 4.5),
    "device_scene": (3.0, 4.2),
    "comparison_scene": (3.0, 4.2),
    "stock_clip": (2.0, 3.2),
}

# The most words a card may carry, per type. Enforced when building props.
#
# This is the half of the fix that duration cannot do. A 25-word quote is bad
# design at ANY length: past roughly 16 words a card stops being a graphic and
# becomes a paragraph, and the answer is to cut the sentence, not to hold it on
# screen for nine seconds.
_WORD_CAPS: dict[str, int] = {
    "headline": 9,
    "quote": 16,
    "typed": 16,
    "support": 9,
    "step": 6,
    "result": 8,
    "value": 6,
    "caption": 8,
}


def _cap_words(text: str, limit: int) -> str:
    """Trim to a word limit at a word boundary, without a trailing comma."""
    words = str(text or "").split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]).rstrip(",;:—-") + "…"


def _visible_words(kind: str, props: dict) -> int:
    """How many words the finished card actually puts on screen."""
    def n(x: Any) -> int:
        return len(str(x or "").split())

    if kind == "mechanism":
        return (n(props.get("title")) + n(props.get("result"))
                + sum(n(s) for s in props.get("steps") or []))
    if kind == "split_screen":
        out = n(props.get("kicker"))
        for side in ("left", "right"):
            d = props.get(side) or {}
            out += n(d.get("label")) + n(d.get("value"))
        return out
    if kind == "code_walkthrough":
        return (n(props.get("filename")) + n(props.get("caption"))
                + sum(n(l) for l in props.get("lines") or []))
    if kind == "cinematic_chart":
        return n(props.get("kicker")) + sum(
            n(b.get("label")) + n(b.get("display")) for b in props.get("bars") or [])
    if kind == "tweet_reveal":
        return n(props.get("quote")) + n(props.get("author")) + n(props.get("role"))
    return sum(n(props.get(k)) for k in
               ("kicker", "value", "headline", "support", "title", "badge", "typed"))


def readable_duration(kind: str, props: dict) -> float:
    """How long this card needs to be on screen to actually be read.

    Duration used to come from a fixed cadence slot, so a four-word headline and
    a twenty-five-word quote both got 2.6 seconds — of which only the final 0.73s
    was legible, because the build phase was still animating for the rest. Time
    on screen has to be a function of what is ON the screen.
    """
    lo, hi = _DURATION_BOUNDS.get(kind, (2.6, 6.0))
    words = _visible_words(kind, props)
    needed = _RECOGNITION_S + words / _READ_RATE + _TAIL_S
    return round(max(lo, min(hi, needed)), 2)
