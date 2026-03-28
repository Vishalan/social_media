"""Tests for make_broll_generator factory."""

import pytest
from unittest.mock import MagicMock

from broll_gen.factory import make_broll_generator


def test_browser_visit_returns_correct_type():
    from broll_gen.browser_visit import BrowserVisitGenerator

    gen = make_broll_generator("browser_visit")
    assert isinstance(gen, BrowserVisitGenerator)


def test_image_montage_returns_correct_type():
    from broll_gen.image_montage import ImageMontageGenerator

    gen = make_broll_generator("image_montage")
    assert isinstance(gen, ImageMontageGenerator)


def test_code_walkthrough_returns_correct_type():
    from broll_gen.code_walkthrough import CodeWalkthroughGenerator

    gen = make_broll_generator("code_walkthrough", anthropic_client=MagicMock())
    assert isinstance(gen, CodeWalkthroughGenerator)


def test_stats_card_returns_correct_type():
    from broll_gen.stats_card import StatsCardGenerator

    gen = make_broll_generator("stats_card", anthropic_client=MagicMock())
    assert isinstance(gen, StatsCardGenerator)


def test_ai_video_returns_correct_type():
    from broll_gen.ai_video import AiVideoGenerator

    gen = make_broll_generator("ai_video", comfyui_client=MagicMock())
    assert isinstance(gen, AiVideoGenerator)


def test_unknown_type_raises_value_error():
    with pytest.raises(ValueError, match="Unknown b-roll type"):
        make_broll_generator("dalle")
