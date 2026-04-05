"""
AvatarLayout enum — shared between the pipeline and VideoEditor.

Kept in avatar_gen/ so both commoncreed_pipeline.py and video_edit/video_editor.py
can import it without circular dependencies.
"""

from enum import Enum


class AvatarLayout(str, Enum):
    """
    Explicit layout mode for avatar video assembly.

    HALF_SCREEN — avatar bottom half, b-roll top half (default).
    FULL_SCREEN — avatar fills the entire 9:16 frame.
    STITCHED    — pipeline stitched multiple clips; treated as HALF_SCREEN at assembly.
    SKIPPED     — no avatar; b-roll fills the full frame.
    BROLL_BODY  — avatar at hook and CTA only; b-roll fills full 9:16 frame during body.
                  Avatar is expected to be a short ~6s clip containing [hook audio][cta audio].
    """
    HALF_SCREEN = "half_screen"
    FULL_SCREEN = "full_screen"
    STITCHED    = "stitched"
    SKIPPED     = "skipped"
    BROLL_BODY  = "broll_body"
