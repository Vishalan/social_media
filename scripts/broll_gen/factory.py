"""
Factory for constructing BrollBase generator instances by type name.

Usage::

    from broll_gen.factory import make_broll_generator

    # CPU-backed generators (no external GPU required)
    gen = make_broll_generator("browser_visit")
    gen = make_broll_generator("image_montage", pexels_api_key="...", bing_api_key="...")
    gen = make_broll_generator("code_walkthrough", anthropic_client=client)
    gen = make_broll_generator("stats_card", anthropic_client=client)
    gen = make_broll_generator("stock_video", pexels_api_key="...")

    # GPU-backed generator (Phase 2 fallback — requires running ComfyUI pod)
    gen = make_broll_generator("ai_video", comfyui_client=comfyui_client)
"""

import logging

from broll_gen.ai_video import AiVideoGenerator
from broll_gen.base import BrollBase
from broll_gen.browser_visit import BrowserVisitGenerator
from broll_gen.cinematic_chart import CinematicChartGenerator
from broll_gen.code_walkthrough import CodeWalkthroughGenerator
from broll_gen.headline_burst import HeadlineBurstGenerator
from broll_gen.image_montage import ImageMontageGenerator
from broll_gen.phone_highlight import PhoneHighlightGenerator
from broll_gen.split_screen import SplitScreenGenerator
from broll_gen.stats_card import StatsCardGenerator
from broll_gen.stock_video import StockVideoGenerator
from broll_gen.tweet_reveal import TweetRevealGenerator

logger = logging.getLogger(__name__)


def make_broll_generator(type_name: str, **kwargs) -> BrollBase:
    """
    Construct and return a BrollBase generator for the requested type.

    Args:
        type_name: One of ``"browser_visit"``, ``"image_montage"``,
                   ``"code_walkthrough"``, ``"stats_card"``, ``"ai_video"``,
                   ``"stock_video"``.
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

                   ``"stock_video"``:
                       - ``pexels_api_key`` (str, optional)

    Returns:
        A concrete BrollBase instance ready for use.

    Raises:
        ValueError: If ``type_name`` is not one of the supported types.
        KeyError: If a required kwarg for the requested type is missing.
    """
    if type_name == "browser_visit":
        logger.info("B-roll generator: BrowserVisitGenerator")
        return BrowserVisitGenerator(
            anthropic_client=kwargs.get("anthropic_client"),
            width_override=kwargs.get("width_override"),
        )

    if type_name == "image_montage":
        logger.info("B-roll generator: ImageMontageGenerator")
        return ImageMontageGenerator(
            pexels_api_key=kwargs.get("pexels_api_key", ""),
            bing_api_key=kwargs.get("bing_api_key", ""),
            width_override=kwargs.get("width_override"),
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
            width_override=kwargs.get("width_override"),
        )

    if type_name == "headline_burst":
        logger.info("B-roll generator: HeadlineBurstGenerator")
        return HeadlineBurstGenerator(
            anthropic_client=kwargs["anthropic_client"],
            width_override=kwargs.get("width_override"),
        )

    if type_name == "ai_video":
        logger.info("B-roll generator: AiVideoGenerator (ComfyUI / Wan2.1)")
        return AiVideoGenerator(
            comfyui_client=kwargs["comfyui_client"],
        )

    if type_name == "stock_video":
        logger.info("B-roll generator: StockVideoGenerator (Pexels video)")
        return StockVideoGenerator(pexels_api_key=kwargs.get("pexels_api_key", ""))

    # ── Unit 0.5 placeholder branches ─────────────────────────────────────
    # Each new type owns a distinct ``elif`` block so the Wave-2 worker
    # replacing it (A1 / B1 / B2 / C2) cannot overlap another worker's edit.
    # Real implementations land in their respective Wave-2 units.
    if type_name == "phone_highlight":
        logger.info("B-roll generator: PhoneHighlightGenerator")
        return PhoneHighlightGenerator(
            anthropic_client=kwargs.get("anthropic_client"),
        )

    if type_name == "tweet_reveal":
        logger.info("B-roll generator: TweetRevealGenerator")
        return TweetRevealGenerator()

    if type_name == "split_screen":
        logger.info("B-roll generator: SplitScreenGenerator")
        return SplitScreenGenerator()

    if type_name == "cinematic_chart":
        logger.info("B-roll generator: CinematicChartGenerator (Remotion sidecar)")
        return CinematicChartGenerator(
            base_url=kwargs.get("remotion_base_url"),
        )

    raise ValueError(
        f"Unknown b-roll type {type_name!r}. "
        f"Supported: browser_visit, image_montage, code_walkthrough, stats_card, "
        f"headline_burst, ai_video, stock_video, phone_highlight, tweet_reveal, "
        f"split_screen, cinematic_chart"
    )
