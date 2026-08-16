"""Stage contracts for the shorts pipeline.

Each stage is defined as a Protocol so an implementation can be replaced
without touching the orchestrator. The point is that this pipeline will be
rebuilt in pieces — LatentSync will be superseded, Chatterbox will be
superseded, the design renderer will change when something better than
HyperFrames appears — and swapping one should not mean rewriting the others.

Rules that keep the seams clean:

* Stages exchange FILE PATHS and plain dicts, never live objects. Anything on
  disk survives a crash and can be inspected by hand.
* A stage reads its inputs from the run directory and writes its outputs
  there. No stage reaches into another stage's internals.
* Failure is per-stage. A design that fails must not cost the avatar render.
* No stage imports another stage. Shared behaviour goes in a module both can
  import.

To swap an implementation: write a class satisfying the protocol, and pass it
to ShortsPipeline instead of the default. Nothing else changes.
"""
from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable


@runtime_checkable
class SourceLoader(Protocol):
    """Turns a reference into facts a script can be written from."""

    def load(self, spec: str, *, kind: str | None = None) -> Any:
        """Return an object with .kind, .title, .text and .url."""
        ...


@runtime_checkable
class ScriptWriter(Protocol):
    """Turns source facts into narration plus a visual identity."""

    async def write(self, source: Any) -> dict:
        """Return {title, hook, script, description, visual_identity, broll_queries}."""
        ...


@runtime_checkable
class VoiceSynth(Protocol):
    """Turns narration text into a mastered audio file.

    Implementations MUST handle length limits internally. Chatterbox caps a
    single generation at ~40s (max_new_tokens=1000, hardcoded upstream) and
    silently truncates mid-sentence past that; a VoiceSynth that does not chunk
    is broken for a 60-second script even though it appears to succeed.
    """

    def synthesize(self, text: str, out_path: str) -> str:
        """Return the path to the mastered WAV."""
        ...


@runtime_checkable
class Transcriber(Protocol):
    """Produces word-level timings for narration.

    Used for TIMING only. The words themselves must come from the script:
    transcribing our own synthetic narration put "GPT-5.6 sold" and
    "John Krapidze" on screen.
    """

    def transcribe(self, audio_path: str, *, model: str = "") -> dict:
        """Return {words: [{word, start, end}], segments: [...]}."""
        ...


@runtime_checkable
class AvatarRenderer(Protocol):
    """Turns audio segments into presenter video."""

    def render(self, segments: Sequence[tuple[float, float]],
               audio_path: str, out_path: str) -> str:
        """Return the path to the joined avatar track.

        Implementations that generate per-segment MUST trim each segment back
        to its audio's exact frame count before joining. LatentSync returns ~2
        frames more than it is given; across six segments that compounded to
        0.48s of drift, with the mouth running ahead of the words.
        """
        ...


@runtime_checkable
class BrollProvider(Protocol):
    """Supplies non-presenter footage.

    Two implementations exist and they are not equivalent. PageRoll captures
    the actual source page; StockFootage searches a stock library by keyword.
    Stock reliably returns footage that is topically adjacent but substantively
    unrelated — strangers in a coworking space for a story about a repository —
    which reads as filler. PageRoll is the default for that reason.
    """

    def provide(self, *, queries: Sequence[str], url: str,
                count: int, duration: float, out_dir: str) -> list[dict]:
        """Return [{path, duration, kind, ...}]."""
        ...


@runtime_checkable
class DesignRenderer(Protocol):
    """Turns design briefs into motion-graphic clips."""

    async def render_all(self, briefs: Sequence[Any], *,
                         concurrency: int = 2) -> list[dict]:
        """Return [{slug, path|None, error|None, ...}] — never raises for one
        bad clip."""
        ...


@runtime_checkable
class Compositor(Protocol):
    """Places content and presenter into a laid-out frame."""

    def composite(self, *, content: str, avatar: str, output: str,
                  layout: str) -> str:
        ...


@runtime_checkable
class ThumbnailMaker(Protocol):
    """Produces the cover frame for a finished short."""

    def make(self, *, script: dict, avatar_path: str, out_path: str) -> str:
        ...
