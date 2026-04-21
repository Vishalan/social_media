"""Per-channel profile registry — thin, module-per-channel.

Each channel is a Python module under this package that exports ``PROFILE``,
a :class:`ChannelProfile` dataclass instance. ``load_channel_config(channel_id)``
returns the profile for the requested channel.

Design intent (per docs/plans/2026-04-21-001-feat-vesper-horror-channel-plan.md):
this is a *thin* scaffold, not a multi-tenant framework. The goal for v1 is
(a) zero ``"CommonCreed"`` or ``"Vesper"`` string literals in shared pipeline
code and (b) a single ``channel_id`` CLI parameter that picks the profile.
The structured schema (full multi-channel factory) is extracted once
channel #2 lands and the right abstraction is visible.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict

from ._types import (
    BrandPalette,
    Cadence,
    ChannelProfile,
    PostizProfile,
    SourceConfig,
    ThumbnailStyle,
    VisualStyle,
    VoiceProfile,
)


class ChannelNotFound(Exception):
    """Raised when ``load_channel_config`` is called with an unknown channel_id."""


def load_channel_config(channel_id: str) -> ChannelProfile:
    """Return the :class:`ChannelProfile` for ``channel_id``.

    Looks up ``channels.<channel_id>`` and returns its ``PROFILE`` attribute.
    Raises :class:`ChannelNotFound` if the module doesn't exist or doesn't
    export a profile.
    """
    try:
        module = importlib.import_module(f"channels.{channel_id}")
    except ModuleNotFoundError as exc:
        raise ChannelNotFound(
            f"No channel module found for {channel_id!r}. "
            f"Expected channels/{channel_id}.py exporting PROFILE."
        ) from exc

    profile = getattr(module, "PROFILE", None)
    if profile is None:
        raise ChannelNotFound(
            f"channels/{channel_id}.py does not export a PROFILE attribute."
        )
    if not isinstance(profile, ChannelProfile):
        raise ChannelNotFound(
            f"channels/{channel_id}.py::PROFILE is not a ChannelProfile "
            f"(got {type(profile).__name__})."
        )
    return profile


def build_legacy_config(profile: ChannelProfile, env: Dict[str, str]) -> Dict[str, Any]:
    """Build the dict-shaped config the legacy pipeline expects.

    The existing :class:`CommonCreedPipeline` takes a flat ``config`` dict
    keyed by provider-specific strings (``anthropic_api_key``, ``voice_id``,
    etc.). This helper flattens the profile + environment into that shape
    without changing the pipeline's constructor signature.

    Secrets are read from ``env`` (typically ``os.environ``) — they never
    live in the profile module because profiles are version-controlled.
    """
    return profile.to_legacy_config(env)


__all__ = [
    "BrandPalette",
    "Cadence",
    "ChannelNotFound",
    "ChannelProfile",
    "PostizProfile",
    "SourceConfig",
    "ThumbnailStyle",
    "VisualStyle",
    "VoiceProfile",
    "build_legacy_config",
    "load_channel_config",
]
