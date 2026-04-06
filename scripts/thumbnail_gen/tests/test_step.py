"""Tests for step_thumbnail — must NEVER raise."""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.thumbnail_gen import step as step_mod
from scripts.thumbnail_gen.step import (
    _script_fallback_headline,
    step_thumbnail,
)


SCRIPT = "OpenAI just released a brand new model that is faster and cheaper."


def _fake_compose(headline, background_path, cutout_path, output_path):
    from PIL import Image
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (10, 10), (1, 2, 3)).save(output_path, "PNG")
    return Path(output_path)


def _fake_cutout(src, cache_path=None):
    from PIL import Image
    p = Path("/tmp/_fake_cutout.png")
    Image.new("RGBA", (4, 4), (0, 0, 0, 0)).save(p, "PNG")
    return p


@pytest.fixture(autouse=True)
def patch_deps(monkeypatch):
    # Patch the modules step.py imports lazily.
    import scripts.thumbnail_gen.headline as h
    import scripts.thumbnail_gen.cutout as c
    import scripts.thumbnail_gen.compositor as comp
    monkeypatch.setattr(h, "generate_headline", lambda s, client=None: "FAKE HEADLINE")
    monkeypatch.setattr(c, "ensure_portrait_cutout", _fake_cutout)
    monkeypatch.setattr(comp, "compose_thumbnail", _fake_compose)
    yield


def test_happy_path(tmp_path):
    out = step_thumbnail(SCRIPT, tmp_path)
    assert out == tmp_path / "thumbnail.png"
    assert out.exists()
    assert out.stat().st_size > 0


def test_headline_failure(tmp_path, monkeypatch):
    import scripts.thumbnail_gen.headline as h
    def boom(s, client=None):
        raise RuntimeError("LLM down")
    monkeypatch.setattr(h, "generate_headline", boom)
    out = step_thumbnail(SCRIPT, tmp_path)
    assert out.exists()


def test_cutout_import_error(tmp_path, monkeypatch):
    import scripts.thumbnail_gen.cutout as c
    def boom(*a, **k):
        raise ImportError("rembg missing")
    monkeypatch.setattr(c, "ensure_portrait_cutout", boom)
    out = step_thumbnail(SCRIPT, tmp_path)
    assert out.exists()


def test_compositor_failure(tmp_path, monkeypatch):
    import scripts.thumbnail_gen.compositor as comp
    def boom(*a, **k):
        raise RuntimeError("compose broke")
    monkeypatch.setattr(comp, "compose_thumbnail", boom)
    out = step_thumbnail(SCRIPT, tmp_path)
    assert out.exists()
    assert out.stat().st_size > 0


def test_catastrophic_failure(tmp_path, monkeypatch):
    import scripts.thumbnail_gen.compositor as comp
    monkeypatch.setattr(comp, "compose_thumbnail",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(step_mod, "_text_only_fallback",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("y")))
    out = step_thumbnail(SCRIPT, tmp_path)
    assert out.exists()
    assert out.stat().st_size > 0


def test_empty_script(tmp_path, monkeypatch):
    import scripts.thumbnail_gen.headline as h
    def boom(s, client=None):
        raise RuntimeError("nothing to summarize")
    monkeypatch.setattr(h, "generate_headline", boom)
    out = step_thumbnail("", tmp_path)
    assert out.exists()


def test_script_fallback_headline():
    assert _script_fallback_headline("") == "BREAKING NEWS"
    assert _script_fallback_headline("hi") == "BREAKING NEWS"
    assert _script_fallback_headline("OpenAI releases new model today") == "OPENAI RELEASES NEW"
    assert _script_fallback_headline("Hello, world! Foo bar.") == "HELLO WORLD FOO"
