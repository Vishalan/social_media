"""
Factory for constructing the configured AvatarClient backend.

Usage::

    from scripts.avatar_gen import make_avatar_client

    config = {
        "avatar_provider": "kling",           # or "heygen"
        "fal_api_key": os.environ["FAL_API_KEY"],
        "kling_avatar_image_url": os.environ["KLING_AVATAR_IMAGE_URL"],
    }
    client = make_avatar_client(config)
    output_path = await client.generate(audio_url, "output/avatar/clip.mp4")
"""

import logging

from .base import AvatarClient
from .heygen_client import HeyGenAvatarClient
from .kling_client import KlingAvatarClient
from .veed_client import VeedFabricClient

logger = logging.getLogger(__name__)

_DEFAULT_PROVIDER = "veed"


def make_avatar_client(config: dict) -> AvatarClient:
    """
    Construct and return the configured AvatarClient backend.

    Args:
        config: Dictionary of configuration values.  Reads
                ``config["avatar_provider"]`` (defaults to ``"veed"``).

                For ``"veed"`` (default):
                    - ``fal_api_key``
                    - ``veed_avatar_image_url``
                    - ``veed_resolution`` (optional, "480p" or "720p", default "480p")
                    - ``output_dir`` (optional, default ``"output/avatar"``)

                For ``"kling"``:
                    - ``fal_api_key``
                    - ``kling_avatar_image_url``
                    - ``output_dir`` (optional, default ``"output/avatar"``)

                For ``"heygen"``:
                    - ``heygen_api_key``
                    - ``heygen_avatar_id``
                    - ``output_dir`` (optional, default ``"output/avatar"``)

                For ``"ltx"`` (not yet implemented — raises NotImplementedError):
                    - ``fal_api_key``
                    - ``ltx_avatar_image_url``
                    - ``output_dir`` (optional)

    Returns:
        AvatarClient instance ready for use.

    Raises:
        ValueError: If ``avatar_provider`` is unrecognised.
        NotImplementedError: If ``avatar_provider`` is ``"ltx"`` (planned, not built yet).
    """
    provider: str = config.get("avatar_provider", _DEFAULT_PROVIDER).lower()
    output_dir: str = config.get("output_dir", "output/avatar")

    if provider == "veed":
        logger.info("Avatar provider: VEED Fabric 1.0 (fal.ai, 480p)")
        return VeedFabricClient(
            fal_api_key=config["fal_api_key"],
            avatar_image_url=config["veed_avatar_image_url"],
            resolution=config.get("veed_resolution", "480p"),
            output_dir=output_dir,
        )

    if provider == "kling":
        logger.info("Avatar provider: Kling AI Avatar v2 Pro (fal.ai)")
        return KlingAvatarClient(
            fal_api_key=config["fal_api_key"],
            avatar_image_url=config["kling_avatar_image_url"],
            output_dir=output_dir,
        )

    if provider == "heygen":
        logger.info("Avatar provider: HeyGen Avatar IV")
        return HeyGenAvatarClient(
            api_key=config["heygen_api_key"],
            avatar_id=config["heygen_avatar_id"],
            output_dir=output_dir,
        )

    if provider == "ltx":
        raise NotImplementedError(
            "LTX-2.3 avatar provider is planned but not yet implemented. "
            "Use 'veed' or 'kling' instead."
        )

    raise ValueError(
        f"Unknown avatar_provider {provider!r}. "
        f"Supported values: 'veed', 'kling', 'heygen'."
    )
