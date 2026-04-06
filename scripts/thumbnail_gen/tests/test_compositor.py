"""Tests for thumbnail compositor."""
from pathlib import Path

import pytest
from PIL import Image

from scripts.thumbnail_gen.compositor import compose_thumbnail, CANVAS_W, CANVAS_H


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def sample_bg() -> Path:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    p = FIXTURES_DIR / "sample_bg.jpg"
    if not p.exists():
        Image.new("RGB", (200, 200), (50, 100, 150)).save(p, "JPEG")
    return p


@pytest.fixture(scope="module")
def sample_cutout() -> Path:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    p = FIXTURES_DIR / "sample_cutout.png"
    if not p.exists():
        img = Image.new("RGBA", (200, 400), (255, 0, 0, 255))
        # transparent border to simulate alpha
        px = img.load()
        for x in range(200):
            for y in range(400):
                if x < 10 or y < 10 or x > 189 or y > 389:
                    px[x, y] = (0, 0, 0, 0)
        img.save(p, "PNG")
    return p


@pytest.fixture(scope="module")
def bad_bg() -> Path:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    p = FIXTURES_DIR / "not_an_image.jpg"
    if not p.exists():
        p.write_text("this is not an image file")
    return p


def _assert_canvas(out: Path):
    assert out.exists()
    img = Image.open(out)
    assert img.size == (CANVAS_W, CANVAS_H)
    assert out.suffix == ".png"


def test_basic_compose(sample_bg, sample_cutout, tmp_path):
    out = tmp_path / "out.png"
    result = compose_thumbnail("HELLO WORLD", sample_bg, sample_cutout, out)
    assert result == out
    _assert_canvas(out)


def test_gradient_fallback_none(sample_cutout, tmp_path):
    out = tmp_path / "out.png"
    compose_thumbnail("AI BREAKS THE INTERNET", None, sample_cutout, out)
    _assert_canvas(out)


def test_gradient_fallback_bad_bg(bad_bg, sample_cutout, tmp_path):
    out = tmp_path / "out.png"
    compose_thumbnail("HELLO WORLD", bad_bg, sample_cutout, out)
    _assert_canvas(out)


def test_center_pixel_not_pure_bg(sample_cutout, tmp_path):
    out = tmp_path / "out.png"
    compose_thumbnail("HELLO WORLD AGAIN", None, sample_cutout, out)
    img = Image.open(out).convert("RGB")
    px = img.getpixel((540, 960))
    # Should not be the pure top gradient color
    from scripts.thumbnail_gen.compositor import BRAND_NAVY
    assert px != BRAND_NAVY


def test_long_headline(sample_cutout, tmp_path):
    out = tmp_path / "out.png"
    compose_thumbnail(
        "ARTIFICIAL INTELLIGENCE TRANSFORMS EVERYTHING NOW",
        None,
        sample_cutout,
        out,
    )
    _assert_canvas(out)


def test_one_long_word(sample_cutout, tmp_path):
    out = tmp_path / "out.png"
    compose_thumbnail("INTERNATIONALIZATION", None, sample_cutout, out)
    _assert_canvas(out)
