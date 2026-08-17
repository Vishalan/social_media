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
        f"  {k}\n     needs: {TYPE_CATALOG[k]['needs']}\n     for:   {TYPE_CATALOG[k]['for']}"
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
  pageroll         {}

Reply with JSON only."""


class BrollDirector:
    """Plans and renders a varied b-roll slate for one short."""

    def __init__(self, *, intelligence: Any, work_dir: str,
                 width: int = 1080, height: int = 998, fps: int = 25,
                 palette: Optional[list[str]] = None,
                 source_url: str = "", source_text: str = "",
                 source_title: str = "") -> None:
        self.llm = intelligence
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.width, self.height, self.fps = width, height, fps
        self.palette = palette or []
        self.source_url = source_url
        self.source_text = source_text
        self.source_title = source_title

    # -- capability gating ------------------------------------------------
    def available_types(self) -> list[str]:
        """Types this story could support at all.

        Gating here rather than in the prompt keeps the planner from choosing
        something the dispatcher cannot render — a page-roll with no URL, or a
        highlight with no article body.
        """
        types = ["stats_card", "headline_burst", "code_walkthrough",
                 "split_screen", "cinematic_chart"]
        if len(self.source_text) > 600:
            types.insert(0, "highlight")
        if self.source_url:
            types.append("pageroll")
        # tweet_reveal is offered only when the source plausibly quotes a
        # person; the planner is told never to invent one, and this stops it
        # being tempted.
        if any(m in self.source_text for m in ('" ', '," ', 'said', 'told')):
            types.append("tweet_reveal")
        return types

    # -- planning ---------------------------------------------------------
    async def plan(self, beats: list[dict], *, max_slots: int = 5) -> list[Slot]:
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
            f"{max_slots} slots; fewer is fine if some beats are better left "
            f"on the presenter."
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
        for item in (data.get("slots") or [])[:max_slots]:
            try:
                b = int(item["beat"])
                kind = str(item["kind"]).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= b < len(beats)) or kind not in avail:
                logger.warning("plan dropped: beat=%s kind=%r not available",
                               item.get("beat"), kind)
                continue
            slots.append(Slot(
                index=len(slots), kind=kind, start=beats[b]["start"],
                duration=beats[b]["duration"], narration=beats[b]["narration"],
                payload=item.get("payload") or {}, why=str(item.get("why", ""))[:220],
            ))

        if not slots:
            raise DirectorError("planner returned no usable slots")
        kinds = ", ".join(s.kind for s in slots)
        logger.info("B-roll plan: %d slots — %s", len(slots), kinds)
        for s in slots:
            logger.info("  %-16s @%5.1fs  %s", s.kind, s.start, s.why)
        return slots

    # -- rendering --------------------------------------------------------
    async def render(self, slot: Slot) -> Slot:
        out = str(self.work_dir / f"broll_{slot.index:02d}_{slot.kind}.mp4")
        try:
            path = await self._dispatch(slot, out)
            slot.path = _normalise_clip(path, slot.duration, self.fps,
                                        self.width, self.height)
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
        """Render a slot as a designed motion graphic via HyperFrames."""
        from design import HyperFramesRenderer
        from .vision import review_design

        brief = _brief_for(slot)
        renderer = HyperFramesRenderer(
            output_dir=str(Path(out).parent),
            work_dir=str(self.work_dir / "design_work"),
            width=self.width, height=self.height, fps=self.fps,
            style=self._style(), reviewer=review_design, max_attempts=2)
        produced = await renderer.render(brief)
        if os.path.abspath(produced) != os.path.abspath(out):
            os.replace(produced, out)
        return out

    def _style(self) -> dict:
        pal = self.palette
        return {
            "palette": ", ".join(pal),
            "typography": "clean geometric sans; monospace for code and data",
            "motifs": "",
            "identity_rationale": "borrowed from the source's own product surface",
            "register": "editorial, borrowed from the source's own product surface",
            "reserved_zone": ("none — you own the whole canvas. It is roughly "
                              "1:1, NOT a tall 9:16 frame."),
            "background": pal[0] if pal else "#0A0C10",
            "accent": pal[2] if len(pal) > 2 else "#22D3EE",
            "muted": pal[-1] if pal else "#A8B8C5",
        }


def _brief_for(slot: "Slot"):
    """Turn a planned slot into a DesignBrief for HyperFrames."""
    from design import DesignBrief

    k, p = slot.kind, slot.payload
    slug = f"{slot.index:02d}-{k}"

    if k == "stats_card":
        head, sup = str(p.get("value", "")), str(p.get("label", ""))
        motion, kind = "count up fast and land hard, no bounce", "stat"
    elif k == "headline_burst":
        head, sup = str(p.get("text", "")), ""
        motion = "words arrive in sequence and settle; no wipe, no spin"
        kind = "lockup"
    elif k == "tweet_reveal":
        head, sup = str(p.get("author", "")), str(p.get("body", ""))
        motion = ("render as a social post card — avatar circle, handle, "
                  "verified tick if given — and let the quote type in")
        kind = "lockup"
    elif k == "code_walkthrough":
        head = str(p.get("filename") or p.get("language", "code"))
        sup = " / ".join(str(x) for x in (p.get("lines") or [])[:6])
        motion = ("render an editor pane with a title bar and line numbers; "
                  "the lines type in, syntax coloured for the language")
        kind = "lockup"
    elif k == "split_screen":
        head = f"{p.get('left_title', 'A')} vs {p.get('right_title', 'B')}"
        sup = (" | ".join(str(x) for x in (p.get("left_lines") or [])[:4])
               + "  ||  "
               + " | ".join(str(x) for x in (p.get("right_lines") or [])[:4]))
        motion = ("STACKED two-panel comparison, upper and lower halves — never "
                  "left/right in a narrow frame. Each panel titled with its "
                  "lines beneath; panels build in sequence, top first")
        kind = "comparison"
    elif k == "cinematic_chart":
        series = p.get("series") or []
        head = str(p.get("title", ""))
        sup = " | ".join(f"{s.get('label')}: {s.get('value')}" for s in series[:5])
        motion = "bars grow in sequence from a zero baseline, then hold"
        kind = "chart"
    else:
        head, sup = slot.narration[:40], ""
        motion, kind = "settle in", "lockup"

    return DesignBrief(
        slug=slug, headline=head[:80], support=sup[:220], context="",
        rationale=slot.why or f"{k} for this beat", motion=motion,
        anchor_word="", duration_s=slot.duration, kind=kind)


def _normalise_clip(path: str, want: float, fps: int,
                    width: int, height: int) -> str:
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
    if not (needs_geom or needs_time):
        return path

    filters = []
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
