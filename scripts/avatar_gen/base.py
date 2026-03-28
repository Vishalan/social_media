"""
Abstract base class and shared exception for avatar generation backends.
"""

from abc import ABC, abstractmethod


class AvatarQualityError(RuntimeError):
    """Raised when an avatar generation backend produces unusable output."""
    pass


class AvatarClient(ABC):
    """
    Provider-agnostic interface for avatar video generation.

    Concrete subclasses: HeyGenAvatarClient, KlingAvatarClient.

    Usage::

        client = make_avatar_client(config)
        output_path = await client.generate(audio_url, "output/avatar/clip.mp4")
    """

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
