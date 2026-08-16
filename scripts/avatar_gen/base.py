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

    # ------------------------------------------------------------------
    # Local-inference extension (added 2026-08-16)
    #
    # ``generate()`` above takes a PUBLIC URL because every backend at the time
    # was a hosted API. A locally-hosted model cannot be expressed through that
    # contract: it needs a file on disk, and for lip-sync-over-real-footage it
    # also needs a driving video. Rather than widen the abstract method (which
    # would break the three hosted clients and their tests), local backends
    # opt in by overriding the two members below.
    # ------------------------------------------------------------------
    @property
    def accepts_local_audio(self) -> bool:
        """
        Whether this backend can consume a local audio file directly.

        False for hosted APIs, which require the pipeline to upload the audio
        somewhere public first. True for local models — and when True the
        pipeline should SKIP the upload entirely, which avoids both the
        round-trip and publishing the owner's voice to a third party.
        """
        return False

    @property
    def needs_driving_video(self) -> bool:
        """
        Whether this backend lip-syncs over existing footage.

        True for LatentSync-class models, which regenerate only the mouth
        region of a supplied clip. Such backends do not synthesise head motion
        or gestures — those come from the driving video — so the caller must
        supply one.
        """
        return False

    async def generate_local(
        self,
        audio_path: str,
        output_path: str,
        *,
        driving_video: Optional[str] = None,
    ) -> str:
        """
        Generate an avatar video from a LOCAL audio file.

        Args:
            audio_path: Path to the audio file on disk.
            output_path: Local file path where the generated MP4 will be saved.
            driving_video: Path or library name of the footage to lip-sync over.
                           Required when ``needs_driving_video`` is True.

        Returns:
            output_path on success.

        Raises:
            NotImplementedError: If this backend is hosted-only.
            AvatarQualityError: If generation fails or produces invalid output.
        """
        raise NotImplementedError(
            f"{type(self).__name__} is a hosted backend and has no local path. "
            f"Check `accepts_local_audio` before calling generate_local()."
        )
