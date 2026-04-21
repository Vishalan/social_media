"""Thumbnail adapter — wraps :mod:`scripts.thumbnail_gen.compositor`
with a :class:`ThumbnailConfig` built from Vesper's channel profile.

The pipeline's `_ThumbnailBuilder` Protocol needs only
``render(*, job, output_path)``. This adapter owns the config
construction (palette, font, pip_enabled=False), the title extraction
from ``job.topic_title``, and the path hand-off.

Background + cutout assets are optional — when ``background_path`` is
``None`` the compositor draws a vertical gradient from the Vesper
palette instead. For the faceless Vesper channel, ``cutout_path`` is
required by the compositor signature but ignored at render time
because ``pip_enabled=False``; we pass a placeholder path.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ._types import VesperJob

logger = logging.getLogger(__name__)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """`#RRGGBB` → `(r, g, b)`. Used to marshal Vesper's `BrandPalette`
    hex values into the tuple shape the compositor expects."""
    s = hex_color.lstrip("#")
    if len(s) != 6:
        raise ValueError(f"expected #RRGGBB, got {hex_color!r}")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


@dataclass
class VesperThumbnailAdapter:
    """Builds a Vesper thumbnail from a :class:`VesperJob`.

    Constructor takes the channel profile (or just the palette +
    thumbnail-style fields — loose so tests don't need the full
    profile dataclass). ``render()`` is the Protocol hook.
    """

    palette: Any               # BrandPalette — kept loose for testing
    thumbnail_style: Any       # ThumbnailStyle — kept loose for testing
    compose_fn: Optional[Any] = None   # injectable for tests
    placeholder_cutout: str = "assets/vesper/refs/_placeholder_cutout.png"

    def render(self, *, job: VesperJob, output_path: str) -> str:
        """Render ``job.topic_title`` into a 1080x1920 thumbnail.

        Returns the output path.
        """
        from thumbnail_gen.compositor import (  # type: ignore
            ThumbnailConfig,
            compose_thumbnail,
        )

        cfg = ThumbnailConfig(
            bg=_hex_to_rgb(self.palette.background),
            bg_deep=_hex_to_rgb(self.palette.shadow),
            accent=_hex_to_rgb(self.palette.accent),
            primary=_hex_to_rgb(self.palette.primary),
            font_candidates=(Path(self.thumbnail_style.font_path),),
            pip_enabled=False,  # Vesper is faceless
            aspect="9:16",
        )

        compose = self.compose_fn or compose_thumbnail
        result = compose(
            headline=job.topic_title,
            background_path=None,     # gradient fallback is the Vesper default
            cutout_path=Path(self.placeholder_cutout),
            output_path=Path(output_path),
            brand_logo_path=None,
            config=cfg,
        )
        logger.info(
            "VesperThumbnailAdapter: wrote %s (headline=%r)",
            result, job.topic_title[:40],
        )
        return str(result)


__all__ = ["VesperThumbnailAdapter"]
