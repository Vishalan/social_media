"""
Factory for constructing BrollBase generator instances by type name.

Usage::

    from broll_gen.factory import make_broll_generator

    # CPU-backed generators (no external GPU required)
    gen = make_broll_generator("browser_visit")
    gen = make_broll_generator("image_montage", pexels_api_key="...", bing_api_key="...")
    gen = make_broll_generator("code_walkthrough", anthropic_client=client)
    gen = make_broll_generator("stats_card", anthropic_client=client)

    # GPU-backed generator (Phase 2 fallback — requires running ComfyUI pod)
    gen = make_broll_generator("ai_video", comfyui_client=comfyui_client)
"""

import logging

from broll_gen.ai_video import AiVideoGenerator
from broll_gen.base import BrollBase
from broll_gen.browser_visit import BrowserVisitGenerator
from broll_gen.code_walkthrough import CodeWalkthroughGenerator
from broll_gen.image_montage import ImageMontageGenerator
from broll_gen.stats_card import StatsCardGenerator

logger = logging.getLogger(__name__)


def make_broll_generator(type_name: str, **kwargs) -> BrollBase:
    """
    Construct and return a BrollBase generator for the requested type.

    Args:
        type_name: One of ``"browser_visit"``, ``"image_montage"``,
                   ``"code_walkthrough"``, ``"stats_card"``, ``"ai_video"``.
        **kwargs:  Type-specific keyword arguments:

                   ``"image_montage"``:
                       - ``pexels_api_key`` (str, optional)
                       - ``bing_api_key`` (str, optional)

                   ``"code_walkthrough"``:
                       - ``anthropic_client`` (required)

                   ``"stats_card"``:
                       - ``anthropic_client`` (required)

                   ``"ai_video"``:
                       - ``comfyui_client`` (required)

    Returns:
        A concrete BrollBase instance ready for use.

    Raises:
        ValueError: If ``type_name`` is not one of the supported types.
        KeyError: If a required kwarg for the requested type is missing.
    """
    if type_name == "browser_visit":
        logger.info("B-roll generator: BrowserVisitGenerator")
        return BrowserVisitGenerator()

    if type_name == "image_montage":
        logger.info("B-roll generator: ImageMontageGenerator")
        return ImageMontageGenerator(
            pexels_api_key=kwargs.get("pexels_api_key", ""),
            bing_api_key=kwargs.get("bing_api_key", ""),
        )

    if type_name == "code_walkthrough":
        logger.info("B-roll generator: CodeWalkthroughGenerator")
        return CodeWalkthroughGenerator(
            anthropic_client=kwargs["anthropic_client"],
        )

    if type_name == "stats_card":
        logger.info("B-roll generator: StatsCardGenerator")
        return StatsCardGenerator(
            anthropic_client=kwargs["anthropic_client"],
        )

    if type_name == "ai_video":
        logger.info("B-roll generator: AiVideoGenerator (ComfyUI / Wan2.1)")
        return AiVideoGenerator(
            comfyui_client=kwargs["comfyui_client"],
        )

    raise ValueError(
        f"Unknown b-roll type {type_name!r}. "
        f"Supported: browser_visit, image_montage, code_walkthrough, stats_card, ai_video"
    )
