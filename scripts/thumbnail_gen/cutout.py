"""Cached portrait cutout via rembg."""
from __future__ import annotations

from pathlib import Path


def ensure_portrait_cutout(source_path: Path, cache_path: Path | None = None) -> Path:
    """Return a path to a transparent-background cutout of the source portrait.

    Caches the result on disk; only re-runs rembg when the source is newer than
    the cache (or the cache is missing).
    """
    source_path = Path(source_path)
    if not source_path.exists():
        raise FileNotFoundError(f"Source portrait not found: {source_path}")

    if cache_path is None:
        cache_path = source_path.parent / f"{source_path.stem}-cutout.png"
    else:
        cache_path = Path(cache_path)

    if cache_path.exists() and cache_path.stat().st_mtime >= source_path.stat().st_mtime:
        return cache_path

    try:
        import rembg
    except ImportError as e:
        raise ImportError(
            "rembg is required for portrait cutout. "
            "Install with: pip install rembg onnxruntime"
        ) from e

    input_bytes = source_path.read_bytes()
    output_bytes = rembg.remove(input_bytes)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(output_bytes)
    return cache_path
