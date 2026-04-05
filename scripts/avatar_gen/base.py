"""
Abstract base class and shared exception for avatar generation backends.
"""

from abc import ABC, abstractmethod
from typing import Optional


class AvatarQualityError(RuntimeError):
    """Raised when an avatar generation backend produces unusable output."""
    pass


class AvatarClient(ABC):
    """
    Provider-agnostic interface for avatar video generation.

    Concrete subclasses: HeyGenAvatarClient, KlingAvatarClient, VeedFabricClient.

    Usage::

        client = make_avatar_client(config)
        output_path = await client.generate(audio_url, "output/avatar/clip.mp4")
    """

    @property
    @abstractmethod
    def needs_portrait_crop(self) -> bool:
        """
        Whether the pipeline should FFmpeg-crop the output to 9:16 portrait.

        True for providers that output landscape (e.g. HeyGen 1920×1080).
        False for providers that output native 9:16 (e.g. Kling, VEED Fabric).
        """
        ...

    @property
    @abstractmethod
    def max_duration_s(self) -> Optional[float]:
        """
        Maximum seconds of avatar video this provider can generate in one API call.

        None means no hard cap. When set (e.g. LTX-2.3 = 20.0), the pipeline
        will stitch multiple clips together for longer content.
        """
        ...

    @abstractmethod
    async def generate(self, audio_url: str, output_path: str) -> str:
        """
        Generate an avatar video lip-synced to the supplied audio.

        Args:
            audio_url: Publicly accessible URL of the ElevenLabs audio file.
            output_path: Local file path where the generated MP4 will be saved.

        Returns:
            output_path on success.

        Raises:
            AvatarQualityError: If generation fails, times out, or produces
                                an empty/invalid output file.
        """
        ...
