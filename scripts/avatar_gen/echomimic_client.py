import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class AvatarQualityError(RuntimeError):
    pass


class EchoMimicClient:
    WORKFLOW_PATH = Path(__file__).parents[2] / "comfyui_workflows" / "echomimic_v3_avatar.json"

    def __init__(self, comfyui_client, output_dir: str = "output/avatar"):
        self.client = comfyui_client
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate(
        self,
        reference_video_path: str,
        audio_path: str,
        output_path: str,
        seed: int | None = None,
    ) -> str:
        """
        Generate an upper-body avatar clip synchronized to audio.
        Returns output_path on success.
        Raises AvatarQualityError if face presence check fails.
        """
        import json
        import random

        workflow = json.loads(self.WORKFLOW_PATH.read_text())
        params = {
            "reference_video": reference_video_path,
            "audio_path": audio_path,
            "output_path": output_path,
            "seed": seed if seed is not None else random.randint(0, 2**31),
        }
        await self.client.run_workflow(workflow, params, wait_for_completion=True)
        self._check_face_presence(output_path)
        return output_path

    def _check_face_presence(self, video_path: str) -> None:
        """
        Basic face presence check: sample frames, verify at least one face detected.
        Raises AvatarQualityError if check fails.
        Uses OpenCV Haar cascade (no GPU required for detection step).
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
            raise AvatarQualityError(f"No face detected in avatar output: {video_path}")
