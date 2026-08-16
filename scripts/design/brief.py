"""Stage 1 — decide what graphics THIS story needs.

The output is a list of DesignBrief objects, each describing one motion graphic:
what it says, why it earns screen time, how it should move, and which spoken
word it should land on. Nothing here is a template — the count, content and
motion are all chosen from the source material.

Design constraints baked into the system prompt come from the editing-grammar
research in docs/spikes/2026-08-avatar-v3/:

* Graphic text reads at ~13 CPS, slower than the 15-20 CPS for subtitles,
  because a card is glanced at while the viewer still tracks the presenter.
* Cards live in the middle band; platform UI clips roughly the top 8% and
  bottom 20%, and no platform publishes a safe-area spec for organic vertical.
* The hook must land by 2.0s (TikTok measures at 2s, Meta at 3s — the tighter
  gate binds for a single cross-posted master), so nothing covers the
  presenter's face in the opening beat.
* Uniformity is the slop tell, not speed. Graphics are placed on semantic
  anchors, never on a metronome.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DesignBriefError(RuntimeError):
    """Raised when briefs cannot be produced or fail validation."""


@dataclass
class DesignBrief:
    """One motion graphic, fully specified before any code is written."""

    slug: str                 # filename-safe id, e.g. "stars-72k"
    headline: str             # the hero element — big, glanceable
    support: str = ""         # secondary label
    context: str = ""         # optional third line, smallest
    rationale: str = ""       # why this earns screen time
    motion: str = ""          # the movement idea, in plain language
    anchor_word: str = ""     # spoken word this should land on
    duration_s: float = 3.0
    kind: str = "stat"        # stat | comparison | list | timeline | lockup

    def dwell_s(self) -> float:
        """Minimum seconds the graphic must stay legible.

        13 CPS for graphic text plus 0.6s handling, floored at 1.8s (below the
        Netflix 5/6s cue floor scaled for a single glance).

        The hero carries full weight; support and context are weighted at half
        because they are scanned, not read — the viewer is still tracking the
        presenter. Counting all three at full rate produced dwell times that
        exceeded the clip's own duration, which is incoherent: a graphic cannot
        need 5.7s of reading inside a 3.0s clip.
        """
        chars = len(self.headline) + 0.5 * len(f"{self.support} {self.context}".strip())
        return max(1.8, round(chars / 13.0 + 0.6, 2))

    def effective_duration_s(self) -> float:
        """How long the clip must actually run.

        A graphic that leaves before it can be read is worse than no graphic —
        it costs attention and returns nothing. So the clip is never shorter
        than its own dwell requirement. Capped at 6s: past that a static card
        stops being a beat and starts being a stall.
        """
        return round(min(6.0, max(self.duration_s, self.dwell_s())), 2)

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["dwell_s"] = self.dwell_s()
        d["effective_duration_s"] = self.effective_duration_s()
        return d


_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "briefs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "headline": {"type": "string"},
                    "support": {"type": "string"},
                    "context": {"type": "string"},
                    "rationale": {"type": "string"},
                    "motion": {"type": "string"},
                    "anchor_word": {"type": "string"},
                    "duration_s": {"type": "number"},
                    "kind": {"type": "string"},
                },
                "required": ["slug", "headline", "rationale", "motion",
                             "anchor_word", "duration_s", "kind"],
            },
        }
    },
    "required": ["briefs"],
}


_SYSTEM = """You are the visual director for a vertical short-form AI/tech channel
fronted by the owner on camera. You decide which facts in a story deserve a motion
graphic, and what each one should do.

Hard rules:

- Between 2 and 4 graphics. Fewer is better than more. A graphic that merely
  repeats what the narration already says clearly is NOT worth screen time —
  say so by leaving it out.
- Every headline must be a figure or a name that appears in the SOURCE. Never
  invent or round a number the source does not state.
- headline is the hero: short, glanceable, ideally under 10 characters. Long
  phrases belong in support.
- anchor_word MUST be a distinctive word that actually appears in the SCRIPT,
  so the graphic can be timed to the narration. Prefer a rare word over a
  common one; avoid "the", "and", "is", numbers written as words.
- Nothing may land before 2.5s. The opening beat is the presenter's face —
  direct-to-camera is the highest-hooking visual open measured (+14% 2sVTR on
  TikTok), and covering it costs more than the graphic gains.
- motion describes ONE idea in plain language, e.g. "count up and settle hard,
  no bounce" or "type in character by character then underline". Not a
  mechanism, not a library. Vary it across the set — three identical count-ups
  read as a template, and uniformity is the tell.
- rationale is one sentence on why THIS fact earns a graphic. If you cannot
  write a convincing one, drop the graphic.
- duration_s between 2.0 and 4.0.
- kind is one of: stat, comparison, list, timeline, lockup.

Reply with JSON only."""


class DesignBriefGenerator:
    """Turns source material + narration into a set of design briefs."""

    def __init__(self, client: Any, model: str = "claude-sonnet-4-5") -> None:
        """
        Args:
            client: an Anthropic-shaped client — normally the claude_cli
                adapter from ``scripts.intelligence``.
            model: model hint passed through to the client.
        """
        self._client = client
        self._model = model

    async def generate(
        self,
        *,
        source_text: str,
        script: str,
        source_kind: str = "article",
        max_briefs: int = 4,
    ) -> list[DesignBrief]:
        """Produce design briefs for one story.

        Args:
            source_text: the article body, README, or repo summary.
            script: the finished narration — anchors must exist in it.
            source_kind: "article" | "github_repo" | "newsletter", used only to
                orient the director toward the right kind of visual.
            max_briefs: hard ceiling on how many graphics to plan.
        """
        prompt = (
            f"SOURCE KIND: {source_kind}\n\n"
            f"SOURCE MATERIAL:\n{source_text.strip()[:12000]}\n\n"
            f"NARRATION SCRIPT (anchor_word must appear here verbatim):\n"
            f"{script.strip()}\n\n"
            f"Plan at most {max_briefs} motion graphics for this story."
        )

        try:
            resp = await self._client.messages.create(
                model=self._model,
                max_tokens=2000,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            )
            data = json.loads(resp.content[0].text)
        except Exception as exc:
            raise DesignBriefError(f"brief generation failed: {exc}") from exc

        raw = data.get("briefs") or []
        if not raw:
            raise DesignBriefError("intelligence layer returned no briefs")

        briefs, script_lower = [], script.lower()
        for item in raw[:max_briefs]:
            b = DesignBrief(
                slug=_slugify(item.get("slug") or item["headline"]),
                headline=item["headline"].strip(),
                support=(item.get("support") or "").strip(),
                context=(item.get("context") or "").strip(),
                rationale=(item.get("rationale") or "").strip(),
                motion=(item.get("motion") or "").strip(),
                anchor_word=(item.get("anchor_word") or "").strip(),
                duration_s=_clamp(float(item.get("duration_s", 3.0)), 2.0, 4.0),
                kind=(item.get("kind") or "stat").strip().lower(),
            )
            # An anchor that is not in the script cannot be timed, and a graphic
            # that cannot be timed would land arbitrarily — drop it loudly
            # rather than placing it on a guess.
            if b.anchor_word.lower().strip(".,!?") not in script_lower:
                logger.warning(
                    "Dropping brief %r — anchor %r is not in the script",
                    b.slug, b.anchor_word,
                )
                continue
            briefs.append(b)

        if not briefs:
            raise DesignBriefError(
                "every brief was dropped: no anchor_word matched the script"
            )

        logger.info("Planned %d design briefs: %s",
                    len(briefs), ", ".join(b.slug for b in briefs))
        return briefs


def _slugify(s: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in s).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out[:40] or "graphic"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))
