"""
Abstract base class and shared exception for b-roll generation backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline import VideoJob


class BrollError(RuntimeError):
    """Raised when a b-roll generator cannot produce output.

    Covers: paywall blocks, empty results, FFmpeg errors, Claude errors,
    network failures, or any other condition that prevents a usable clip.
    """
    pass


class BrollBase(ABC):
    """
    Provider-agnostic interface for b-roll video generation.

    Concrete subclasses implement a specific generation strategy
    (e.g. ComfyUI/Wan2.1, stock footage API, AI video service).

    Usage::

        client = make_broll_client(config)
        output_path = await client.generate(job, target_duration_s=4.0, output_path="output/broll/clip.mp4")
    """

    @abstractmethod
    async def generate(
        self,
        job: "VideoJob",
        target_duration_s: float,
        output_path: str,
    ) -> str:
        """
        Generate a b-roll clip for the given video job.

        Args:
            job: VideoJob containing topic, script context, and asset references.
            target_duration_s: Desired clip length in seconds.
            output_path: Local file path where the generated MP4 will be saved.

        Returns:
            output_path on success.

        Raises:
            BrollError: If generation fails, times out, or produces an
                        empty/invalid output file.
        """
        ...
