"""
Wan2.2-S2V-14B avatar client — generates lip-synced talking head video
from a reference image + audio via ComfyUI.

Uses the same ComfyUI workflow pattern as EchoMimicClient: load a JSON
workflow template, substitute params, call comfyui_client.run_workflow().

Requires:
- ComfyUI running at the configured URL (default http://localhost:8188)
- ComfyUI-WanVideoWrapper custom node installed
- Wan2.2-S2V-14B model weights in ComfyUI models directory
"""
import asyncio
import logging
from pathlib import Path
from typing import Optional

from .base import AvatarClient, AvatarQualityError

logger = logging.getLogger(__name__)


class Wan22S2VClient(AvatarClient):
    WORKFLOW_PATH = Path(__file__).parents[1] / "comfyui_workflows" / "wan22_s2v_avatar.json"

    def __init__(
        self,
        comfyui_client,
        reference_image_path: str,
        output_dir: str = "output/avatar",
    ):
        self.client = comfyui_client
        self.reference_image_path = reference_image_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def needs_portrait_crop(self) -> bool:
        return False  # native 9:16 at 768x768

    @property
    def max_duration_s(self) -> Optional[float]:
        return 60.0  # Wan2.2 handles up to 60s natively

    async def generate(self, audio_url: str, output_path: str) -> str:
        """
        Generate an avatar video lip-synced to the supplied audio.

        Args:
            audio_url: Path or URL to the audio file.
            output_path: Local file path where the generated MP4 will be saved.

        Returns:
            output_path on success.

        Raises:
            AvatarQualityError: If generation fails or no face detected.
        """
        import json
        import random

        if not self.WORKFLOW_PATH.exists():
            raise AvatarQualityError(
                f"Wan2.2-S2V workflow not found at {self.WORKFLOW_PATH}. "
                "Create it in ComfyUI UI and export as JSON."
            )

        workflow = json.loads(self.WORKFLOW_PATH.read_text())
        params = {
            "reference_image": self.reference_image_path,
            "audio_path": audio_url,
            "output_path": output_path,
            "seed": random.randint(0, 2**31),
        }
        await self.client.run_workflow(workflow, params, wait_for_completion=True)
        self._check_face_presence(output_path)
        return output_path

    def _check_face_presence(self, video_path: str) -> None:
        """
        Basic face presence check: sample frames, verify at least one face detected.
        Raises AvatarQualityError if check fails.
        """
        import cv2

        cap = cv2.VideoCapture(video_path)
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        found = False
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sample_interval = max(1, frame_count // 10)
        for i in range(0, frame_count, sample_interval):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if not ret:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
            if len(faces) > 0:
                found = True
                break
        cap.release()
        if not found:
            raise AvatarQualityError(f"No face detected in Wan2.2 avatar output: {video_path}")
