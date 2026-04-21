"""Curated Vesper story candidates + a lexical tension-curve scorer.

Three problems this solves for the offline/server demos:

1. **Story quality is uneven.** Without an LLM to generate + score
   stories per-run, we need a small curated pool and a way to pick
   the best one.
2. **Visuals unaligned with narration.** The old demo used a fixed
   set of beat prompts independent of the chosen story. Now each
   story is split into N narration phases; each beat's Flux prompt
   is derived from the phase it accompanies.
3. **Horror palette crashing in at t=0.** The plan's Vesper palette
   ("oxidized blood, bone") is appropriate for climax beats but
   disorienting on the hook. The tag→palette gradient below maps
   hook/setup → neutral/documentary; rising/reveal → cold unease;
   climax/tail → full Vesper palette.

The scorer is intentionally simple (lexical, no LLM). It rewards
stories where tension markers cluster in the back half — the
Archivist register's shape. LLM-based scoring is the upgrade path
when ANTHROPIC_API_KEY is wired.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import List, Optional, Sequence


# ─── Candidate stories ────────────────────────────────────────────────────
#
# Each is ~180 words, Archivist-register (first-person transcribed
# account, modern US/UK, workplace-grounded). The "tension" field is
# the scorer's lexical output — sorted by this at load time so the
# top-scored candidate is index 0 by convention.


# Per-story "visual bible": locked look, location, and canonical
# character descriptions. Every beat's Flux prompt inherits these so
# the 12 renders read as one film rather than 12 disconnected images.
# Without this, Flux invents a different waitress, a different diner,
# and different lighting on every beat.
_STORY_VISUAL_BIBLE: dict = {
    "2-47-diner": {
        "look": (
            "shot on CineStill 800T 35mm film, warm tungsten practical "
            "highlights against deep teal shadows, high-ISO grain, "
            "orange halation around light sources, handheld, shallow "
            "depth of field, no text, no captions, no watermark"
        ),
        "location": (
            "an empty roadside diner in the Texas panhandle at 2:47 am, "
            "rainy asphalt parking lot, sodium streetlamps, red neon "
            "diner sign reflecting in wet pavement, flat plains horizon"
        ),
        "characters": {
            "narrator": (
                "a mid-50s male long-haul truck driver, unshaven, "
                "canvas jacket, kept off-camera or in silhouette"
            ),
            "waitress": (
                "a tired mid-40s waitress in a white apron, shoulder-"
                "length dark hair, head down, face mostly obscured "
                "by her own shadow"
            ),
            "silent_man": (
                "a motionless male figure seated at the counter, back "
                "to camera, plain dark jacket, head slightly bowed, "
                "never clearly visible, partially silhouetted"
            ),
        },
    },
    "room-four-night-shift": {
        "look": (
            "shot on grainy 35mm film, cold flickering fluorescent "
            "overhead lighting, pale green-cyan wall tint, muted palette, "
            "handheld, shallow depth of field, no text no watermark"
        ),
        "location": (
            "a small rural hospital at 3:20 am, narrow linoleum "
            "hallway, fluorescent tube ceiling lights, empty nurses' "
            "station at the far end, doorways propped open"
        ),
        "characters": {
            "narrator": (
                "a late-30s male night-shift nurse, scrubs, tired eyes, "
                "kept at the edge of frame"
            ),
            "room_four": (
                "an unoccupied hospital room, empty bed with bare "
                "mattress, untouched call-button on the nightstand, "
                "no patient visible ever"
            ),
        },
    },
    "factory-ceiling": {
        "look": (
            "shot on 35mm film, industrial halogen work lights "
            "against deep shadow, metallic blue-gray palette, "
            "handheld from ground level looking up, wide-angle lens, "
            "no text no watermark"
        ),
        "location": (
            "the production floor of an aluminum-can plant at 4 am, "
            "thirty-foot ceilings, exposed steel catwalks, pipes and "
            "conduit, hydraulic lines, machinery idle"
        ),
        "characters": {
            "narrator": (
                "a male maintenance worker in coveralls and hi-vis "
                "vest, kept in middle distance, looking up"
            ),
            "figure": (
                "a crouched humanoid figure on a catwalk high above, "
                "arms folded around its knees, motionless, never "
                "clearly visible, silhouetted against overhead lights"
            ),
        },
    },
}


_STORIES: List[dict] = [
    {
        "id": "2-47-diner",
        "title": "The 2:47 diner",
        "text": (
            "I drove truck for fourteen years on the same stretch of "
            "interstate. You learn the rhythm of it. The same billboards, "
            "the same rest stops, the same faces behind the counter at "
            "the all-night diner outside Amarillo. One Tuesday in "
            "November I pulled in at two-forty-seven in the morning for "
            "coffee and a bathroom. The lot was empty. Just my rig and "
            "one blue sedan. I remember thinking the sedan was odd "
            "because its headlights were still on. Inside, the waitress "
            "set my cup down without looking up. She said quietly, "
            "don't turn around. I asked her what. She said the man at "
            "the counter behind you came in an hour ago and he hasn't "
            "moved. He hasn't blinked. She said, I think he's waiting "
            "for someone and I don't know who. I paid for my coffee "
            "and I left. The blue sedan was gone. My rig was exactly "
            "where I parked it. I never stopped at that diner again."
        ),
    },
    {
        "id": "room-four-night-shift",
        "title": "Room four, night shift",
        "text": (
            "I took night shift at a small rural hospital for six "
            "months between jobs. It pays more. You mostly watch "
            "monitors and answer call buttons. Room four was empty "
            "that whole stretch. No patient, no bedding on the mattress, "
            "the door always propped open so the fluorescents from "
            "the hallway washed inside. One night at three-twenty the "
            "call light above room four came on. Yellow, steady. I "
            "walked down. The bed was still empty. The button was on "
            "the nightstand where it always sat. Untouched. I reset "
            "the light and I went back to the station. At three-"
            "twenty-six it came on again. Steady. This time I watched "
            "it from the hallway before I entered. Nobody there. Just "
            "the humming fluorescent and a faint smell like old "
            "pennies. I reset it once more. The third time it came "
            "on I was already walking. I did not look inside. I "
            "finished the shift at the nurses' station with my back "
            "to that door."
        ),
    },
    {
        "id": "factory-ceiling",
        "title": "The factory ceiling",
        "text": (
            "I worked maintenance at an aluminum-can plant in Ohio. "
            "Twelve-hour overnights. The production floor has ceilings "
            "maybe thirty feet up, grids of catwalks and conduit. You "
            "learn to ignore the shapes up there — pipes, lights, "
            "support steel. You only look up if something's broken. "
            "One Saturday around four in the morning I was resetting "
            "a hydraulic line under stack seven and I happened to look "
            "straight up. There was a figure crouched on the catwalk "
            "directly above me. Arms folded around its knees. Not "
            "moving. I thought at first it was one of the line-ops "
            "taking a break where they shouldn't, so I waved. It "
            "didn't wave back. I radioed Tyler on shift. He came over "
            "and looked up with me. He said that catwalk doesn't "
            "connect to anything. There's no ladder, no door, nothing. "
            "We watched it together for a full minute. Then we "
            "finished the shift on the far side of the building. "
            "Neither of us reported it. I quit the following Friday."
        ),
    },
]


# ─── Tension-curve scorer ─────────────────────────────────────────────────


# Words/phrases that mark escalation in Archivist-register prose.
# Intentionally includes mundane markers ("I noticed") as well as overt
# ones ("didn't move") since Vesper's voice is deliberately flat.
_TENSION_MARKERS = (
    "didn't move", "did not move", "hasn't moved", "hasn't blinked",
    "waiting for", "still on", "without looking up", "quietly",
    "don't turn", "i noticed", "suddenly", "then i saw",
    "directly above", "directly behind", "not moving", "untouched",
    "empty", "alone", "i was already walking", "i did not look",
    "third time", "second time", "hadn't",
    "wrong", "off", "my back to", "i left", "i quit", "i never",
)
_HOOK_MARKERS = (
    "years", "the same", "every", "rhythm", "shift", "routine",
    "usual", "night shift", "twelve-hour", "worked", "drove",
)

_BACK_HALF_THRESHOLD = 0.55  # tension markers should cluster past 55% of the story


@dataclass(frozen=True)
class StoryScore:
    story_id: str
    total: float
    hook_strength: float
    tension_density: float
    back_half_ratio: float
    word_count: int
    detail: str = ""


def score_story(story: dict) -> StoryScore:
    text = story["text"].lower()
    words = text.split()
    n_words = len(words)
    if n_words == 0:
        return StoryScore(story["id"], 0.0, 0.0, 0.0, 0.0, 0)

    # Hook strength: count hook markers in first 20% of the story.
    hook_end_idx = max(1, int(n_words * 0.2))
    hook_text = " ".join(words[:hook_end_idx])
    hook_hits = sum(1 for m in _HOOK_MARKERS if m in hook_text)
    # Log-scaled so we don't over-reward long openings.
    hook_strength = math.log1p(hook_hits) * 2.0

    # Tension density + back-half ratio.
    tension_positions: List[int] = []
    for m in _TENSION_MARKERS:
        start = 0
        while True:
            pos = text.find(m, start)
            if pos < 0:
                break
            # Convert char position → approximate word index.
            word_idx = len(text[:pos].split())
            tension_positions.append(word_idx)
            start = pos + len(m)
    tension_count = len(tension_positions)
    tension_density = tension_count / max(n_words / 100, 1)  # per 100 words

    if tension_positions:
        back_half_hits = sum(
            1 for p in tension_positions
            if p / n_words >= _BACK_HALF_THRESHOLD
        )
        back_half_ratio = back_half_hits / tension_count
    else:
        back_half_ratio = 0.0

    # Shape penalty — very short stories (< 120 words) aren't shorts-
    # compatible; over-long (> 230) will trip beat-count math.
    length_penalty = 0.0
    if n_words < 120:
        length_penalty = (120 - n_words) * 0.05
    elif n_words > 230:
        length_penalty = (n_words - 230) * 0.03

    total = (
        hook_strength
        + tension_density
        + back_half_ratio * 3.0
        - length_penalty
    )
    return StoryScore(
        story_id=story["id"],
        total=round(total, 3),
        hook_strength=round(hook_strength, 3),
        tension_density=round(tension_density, 3),
        back_half_ratio=round(back_half_ratio, 3),
        word_count=n_words,
        detail=(
            f"hits={tension_count} back_half={back_half_ratio:.2f} "
            f"density={tension_density:.2f}"
        ),
    )


def pick_best_story() -> dict:
    """Return the highest-scoring story from the curated pool."""
    scored = [(score_story(s), s) for s in _STORIES]
    scored.sort(key=lambda p: p[0].total, reverse=True)
    return scored[0][1]


def list_all_scored() -> List[tuple]:
    """Return [(StoryScore, dict), ...] sorted best-first, for the
    demo to log its selection rationale."""
    scored = [(score_story(s), s) for s in _STORIES]
    scored.sort(key=lambda p: p[0].total, reverse=True)
    return scored


# ─── Phase splitting + per-beat Flux prompts ──────────────────────────────


# Tag → (palette phrase, lighting phrase, mood phrase).
# Hook + setup deliberately neutral — no "blood", no "oxidized", no
# "near-black" until rising/reveal. Keeps the viewer's interest without
# front-loading horror.
_TAG_PROMPT_TEMPLATES = {
    "hook": {
        "palette": "desaturated winter tones, sodium streetlight orange, cold slate blue",
        "mood":    "documentary photograph, mundane, ordinary, no tension",
        "light":   "overhead sodium lamps, soft diffused fog",
    },
    "setup": {
        "palette": "warm amber interior lamps, cream and wood tones",
        "mood":    "naturalistic 35mm film, workaday, familiar",
        "light":   "soft indoor tungsten, no shadows",
    },
    "rising": {
        "palette": "cool neutral, muted blue-gray, slight desaturation",
        "mood":    "slight unease, off-composition, something just outside frame",
        "light":   "cold fluorescent, shadow in foreground",
    },
    "reveal": {
        "palette": "cold steel blue, bone cream accents, one oxidized edge",
        "mood":    "a single unsettling detail becomes visible, naturalistic not graphic",
        "light":   "low key, single off-camera source, directional shadow",
    },
    "climax": {
        "palette": "near-black background, oxidized blood and bone palette, graphite shadows",
        "mood":    "still tension, high contrast, viewer holds their breath",
        "light":   "minimal light source, rim-lit silhouettes",
    },
    "tail": {
        "palette": "cold blue predawn, desaturated gray, faint bone",
        "mood":    "empty aftermath, release, distance",
        "light":   "overcast predawn, flat cool light",
    },
}

_FLUX_SHARED_SUFFIX = (
    "cinematic horror photograph, 35mm film grain, 9:16 vertical, "
    "high detail, no text no watermark, no captions"
)


def split_story_into_phases(
    story_text: str, n_phases: int,
) -> List[str]:
    """Split the story text into ``n_phases`` roughly-equal word-count
    chunks. Preserves sentence boundaries where possible so each phase
    reads as a coherent moment."""
    sentences = re.split(r"(?<=[.!?])\s+", story_text.strip())
    if not sentences or n_phases <= 0:
        return [story_text]
    total_words = sum(len(s.split()) for s in sentences)
    target_words = total_words / n_phases

    phases: List[str] = []
    current: List[str] = []
    current_words = 0
    for sent in sentences:
        sw = len(sent.split())
        if current and (current_words + sw) > target_words * 1.4:
            # Close the current phase if adding this sentence would
            # overshoot by >40%.
            phases.append(" ".join(current))
            current = [sent]
            current_words = sw
        else:
            current.append(sent)
            current_words += sw
        if len(phases) >= n_phases - 1 and current:
            # Don't start a new phase if we already have n_phases - 1
            # closed — let the remaining sentences accumulate.
            continue
    if current:
        phases.append(" ".join(current))

    # Pad or trim to exactly n_phases.
    while len(phases) < n_phases:
        phases.append(phases[-1] if phases else story_text)
    return phases[:n_phases]


def _phase_scene_summary(phase_text: str) -> str:
    """Extract a short scene descriptor from a phase chunk. Takes the
    first clause or first 15 words — whichever is shorter."""
    first_sentence = re.split(r"[.!?]", phase_text.strip(), 1)[0]
    words = first_sentence.split()
    return " ".join(words[:15]).strip()


def _character_matches_for_phase(
    phase_text: str, characters: dict,
) -> List[str]:
    """Return the subset of canonical character descriptions whose
    keyword appears in the phase text. Keeps a character card visible
    in only the beats where that character is mentioned, so Flux has
    no excuse to invent a different one."""
    matches: List[str] = []
    lower = phase_text.lower()
    # Simple keyword mapping. Can't hurt to overrun; Flux handles
    # 200-300 token prompts fine.
    keyword_map = {
        "narrator": ("drove", "i pulled", "i paid", "i left", "i asked",
                     "i took", "i worked", "i walked", "i reset",
                     "i radioed"),
        "waitress": ("waitress",),
        "silent_man": ("man at the counter", "silhouette", "hadn't moved",
                       "hadn't blinked", "didn't move", "behind you"),
        "room_four": ("room four", "call light", "bed", "mattress",
                      "nightstand", "doorway"),
        "figure": ("figure", "catwalk", "crouched", "above me",
                   "arms folded"),
    }
    for name, desc in characters.items():
        triggers = keyword_map.get(name, ())
        for trig in triggers:
            if trig in lower:
                matches.append(desc)
                break
    return matches


def build_flux_prompts(
    story_text: str,
    beats: Sequence,
    *,
    story_id: Optional[str] = None,
) -> List[str]:
    """Per-beat Flux prompts with locked story-level look + location +
    character descriptions so the 12 renders read as one film.

    Each prompt structure:

        <scene from phase>,
        <characters present in this phase>,
        <tag-based mood/palette modifier>,
        LOCATION (locked for story),
        LOOK (locked for story)

    The bible for ``story_id`` is looked up in ``_STORY_VISUAL_BIBLE``.
    Unknown story ids fall back to a generic horror look (matches the
    old behavior — callers upgrading to bible-aware stories pass the
    id explicitly).
    """
    n = len(beats)
    phases = split_story_into_phases(story_text, n)
    bible = _STORY_VISUAL_BIBLE.get(story_id) if story_id else None
    prompts: List[str] = []
    for idx, beat in enumerate(beats):
        phase = phases[min(idx, len(phases) - 1)]
        scene = _phase_scene_summary(phase)
        tag = (getattr(beat, "tag", "") or "hook").lower()
        tmpl = _TAG_PROMPT_TEMPLATES.get(tag, _TAG_PROMPT_TEMPLATES["setup"])

        parts: List[str] = [scene]
        if bible:
            chars = _character_matches_for_phase(
                phase, bible.get("characters", {}),
            )
            parts.extend(chars)
        # Tag modulator (mood) stays subtle — the locked look + location
        # do the heavy lifting for consistency.
        parts.append(tmpl["mood"])
        if bible:
            parts.append(bible["location"])
            parts.append(bible["look"])
        else:
            # Fallback for stories without a bible — the old
            # palette-gradient behavior.
            parts.append(tmpl["palette"])
            parts.append(tmpl["light"])
            parts.append(_FLUX_SHARED_SUFFIX)
        prompts.append(", ".join(p for p in parts if p))
    return prompts


__all__ = [
    "StoryScore",
    "build_flux_prompts",
    "list_all_scored",
    "pick_best_story",
    "score_story",
    "split_story_into_phases",
]
