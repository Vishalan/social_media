"""Designed motion-graphic b-roll, authored per story.

Two stages, both driven by the intelligence layer so nothing is templated:

1. ``brief`` — read the source (article, GitHub repo, newsletter) and decide
   what visuals THIS story needs: which facts deserve a graphic, what each one
   should say, how it should move, and where it belongs in the narration.
2. ``render`` — hand each brief to the Claude Code CLI with the HyperFrames
   skills loaded; it authors an HTML composition, runs the lint/check gates,
   and renders an MP4.

Why not a fixed template set: the pipeline previously drew stat cards with PIL
at fixed sizes and positions. Every video looked identical, which is exactly
the uniformity the editing-grammar research identifies as the slop tell. Here
the number of graphics, their content, and their motion all follow the story.

Cost: rendering is local (Node + Chrome + FFmpeg) and the intelligence runs on
the owner's Claude subscription via ``claude -p``. No metered API spend. The
real cost is wall-clock — roughly 9-10 minutes per clip, and clips are
independent so they parallelise.
"""
from __future__ import annotations

from .brief import DesignBrief, DesignBriefGenerator, DesignBriefError
from .renderer import HyperFramesRenderer, RenderError

__all__ = [
    "DesignBrief",
    "DesignBriefGenerator",
    "DesignBriefError",
    "HyperFramesRenderer",
    "RenderError",
]
