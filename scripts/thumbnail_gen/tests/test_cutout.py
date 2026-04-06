"""Tests for portrait cutout caching."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

from scripts.thumbnail_gen.cutout import ensure_portrait_cutout


def _make_source(tmp_path: Path, name: str = "portrait.jpg") -> Path:
    p = tmp_path / name
    p.write_bytes(b"fake-jpeg-bytes")
    return p


class _ExplodingModule(types.ModuleType):
    def __getattr__(self, item):  # pragma: no cover - defensive
        raise AssertionError(f"rembg should not have been imported (accessed {item})")


def test_cache_hit_does_not_import_rembg(tmp_path, monkeypatch):
    src = _make_source(tmp_path)
    cache = tmp_path / "out.png"
    cache.write_bytes(b"cached-png")
    # Make cache newer than source
    src_stat = src.stat()
    os.utime(cache, (src_stat.st_atime, src_stat.st_mtime + 100))

    monkeypatch.setitem(sys.modules, "rembg", _ExplodingModule("rembg"))

    result = ensure_portrait_cutout(src, cache)
    assert result == cache
    assert cache.read_bytes() == b"cached-png"


def test_cache_miss_invokes_rembg(tmp_path, monkeypatch):
    src = _make_source(tmp_path)
    cache = tmp_path / "out.png"

    calls = {}

    def fake_remove(data):
        calls["data"] = data
        return b"png-output"

    mock_module = types.ModuleType("rembg")
    mock_module.remove = fake_remove
    monkeypatch.setitem(sys.modules, "rembg", mock_module)

    result = ensure_portrait_cutout(src, cache)
    assert result == cache
    assert cache.read_bytes() == b"png-output"
    assert calls["data"] == b"fake-jpeg-bytes"


def test_source_newer_than_cache_reruns_rembg(tmp_path, monkeypatch):
    src = _make_source(tmp_path)
    cache = tmp_path / "out.png"
    cache.write_bytes(b"stale")
    # Make source newer than cache
    cache_stat = cache.stat()
    os.utime(src, (cache_stat.st_atime, cache_stat.st_mtime + 100))

    mock_module = types.ModuleType("rembg")
    mock_module.remove = lambda data: b"fresh-png"
    monkeypatch.setitem(sys.modules, "rembg", mock_module)

    result = ensure_portrait_cutout(src, cache)
    assert result == cache
    assert cache.read_bytes() == b"fresh-png"


def test_default_cache_path(tmp_path, monkeypatch):
    src = _make_source(tmp_path, "owner-portrait-9x16.jpg")

    mock_module = types.ModuleType("rembg")
    mock_module.remove = lambda data: b"png-output"
    monkeypatch.setitem(sys.modules, "rembg", mock_module)

    result = ensure_portrait_cutout(src)
    expected = tmp_path / "owner-portrait-9x16-cutout.png"
    assert result == expected
    assert expected.exists()


def test_missing_source_raises_before_rembg_import(tmp_path, monkeypatch):
    src = tmp_path / "nope.jpg"
    monkeypatch.setitem(sys.modules, "rembg", _ExplodingModule("rembg"))

    with pytest.raises(FileNotFoundError):
        ensure_portrait_cutout(src)


def test_missing_rembg_raises_clear_error(tmp_path, monkeypatch):
    src = _make_source(tmp_path)
    cache = tmp_path / "out.png"

    # Force ImportError by inserting None into sys.modules
    monkeypatch.setitem(sys.modules, "rembg", None)

    with pytest.raises(ImportError, match="rembg is required for portrait cutout"):
        ensure_portrait_cutout(src, cache)
