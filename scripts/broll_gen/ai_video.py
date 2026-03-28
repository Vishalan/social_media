"""
B-roll type: ai_video

Thin adapter wrapping the existing ComfyUI Wan2.1 workflow.
Requires a running GPU pod — only invoked in Phase 2 when CPU types fail.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from broll_gen.base import BrollBase, BrollError
from video_gen.comfyui_client import ComfyUIClient

if TYPE_CHECKING:
    from pipeline import VideoJob

logger = logging.getLogger(__name__)


class AiVideoGenerator(BrollBase):
    """B-roll generator that delegates to the ComfyUI Wan2.1 workflow.

    This is a Phase 2 fallback — it requires a running GPU pod and should
    only be invoked after CPU-based generators (browser_visit, image_montage,
    code_walkthrough, stats_card) have been exhausted or have raised BrollError.
    """

    def __init__(self, comfyui_client: ComfyUIClient) -> None:
        """
        Args:
            comfyui_client: Initialised ComfyUIClient pointed at the GPU pod.
        """
        self._comfyui = comfyui_client

    async def generate(
        self,
        job: "VideoJob",
        target_duration_s: float,
        output_path: str,
    ) -> str:
        """Generate a b-roll clip via ComfyUI Wan2.1.

        Args:
            job: VideoJob containing topic and script context.
            target_duration_s: Desired clip length in seconds (passed as hint
                               to the workflow via the ``output_path`` param).
            output_path: Local file path where the generated MP4 will be saved.

        Returns:
            output_path on success.

        Raises:
            BrollError: If the ComfyUI workflow fails for any reason.
        """
        visual_prompt = job.script.get(
            "visual_cues", job.script.get("title", job.topic["title"])
        )

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            "ai_video: generating b-roll | prompt=%r | output=%s",
            visual_prompt,
            output_path,
        )

        try:
            await self._comfyui.run_workflow(
                workflow_json=None,
                params={"prompt": visual_prompt, "output_path": output_path},
                wait_for_completion=True,
            )
        except Exception as e:
            raise BrollError(f"ai_video: {e}") from e

        return output_path
