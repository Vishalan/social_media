"""Still-image generation + timeline planning for story-channel visuals.

Vesper's visual stack (Unit 9 / Unit 10 scaffolding):
  * :class:`FalFluxClient` — stateless fal.ai HTTP client for Flux text-to-image
  * :class:`Beat` / :class:`Timeline` — shot-timeline representation
  * :mod:`.timeline_lint` — anti-slop rules (duration variance + move
    diversity + parallax / I2V ratio targets) enforced pre-render

The rendering side (Ken Burns on stills, DepthFlow parallax, overlay
pack, MoviePy assembly) reuses existing helpers under
``scripts/broll_gen/image_montage.py`` + ``scripts/video_edit/video_editor.py``.
"""

from __future__ import annotations

from ._types import Beat, BeatMode, Timeline

__all__ = ["Beat", "BeatMode", "Timeline"]
