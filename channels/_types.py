"""Channel-profile dataclasses.

These describe the per-channel surfaces of the pipeline: identity, voice
configuration, visual style, content source, posting cadence, Postiz
routing, brand palette, thumbnail style, and the legacy config-dict
shape the existing :class:`CommonCreedPipeline` consumes.

The dataclasses are *value containers*. They do not read environment
variables themselves — :meth:`ChannelProfile.to_legacy_config` takes
the ``env`` dict as an argument so tests and alternate entry points can
inject their own environment without monkey-patching ``os.environ``.

Design notes:
  * Fields are intentionally permissive (``Optional`` + defaults) because
    v1 has two concrete profiles — CommonCreed (full avatar pipeline) and
    Vesper (faceless, story-driven). Some fields apply to one channel and
    not the other. Per plan scope-guardian review, we resist adding
    fields-per-concept speculation; only land what both profiles will use
    or what a profile must declare today.
  * Secrets never live in the profile module. They flow in via
    ``to_legacy_config(env)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


# ─── Sub-profiles ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VoiceProfile:
    """How this channel generates voice-over."""

    provider: str  # "elevenlabs" | "chatterbox"
    # Chatterbox-specific: path to reference audio clip inside the sidecar.
    reference_audio: Optional[str] = None
    # ElevenLabs-specific: voice ID (``ELEVENLABS_VOICE_ID`` env var value).
    voice_id: Optional[str] = None
    # Chatterbox generation tuning (documented per-channel; 0.5/0.5 is the
    # engine default). Vesper uses low/tense 0.35/0.3 for whispered register.
    exaggeration: float = 0.5
    cfg: float = 0.5


@dataclass(frozen=True)
class BrandPalette:
    """Four-color brand palette used by captions, thumbnails, interstitials.

    Colors are ``#RRGGBB`` hex strings; ``scripts.branding.to_ass_color``
    converts them to ASS subtitle tokens at render time.
    """

    primary: str         # dominant text / emphasis color
    background: str      # dominant background / matte
    accent: str          # keyword-punch / active-caption color
    shadow: str          # drop-shadow / graphite tone


@dataclass(frozen=True)
class VisualStyle:
    """Channel-specific visual prompt + motion mix knobs.

    Fields beyond ``flux_prompt_prefix`` / ``suffix`` are Vesper-shaped
    (parallax % + I2V hero %). CommonCreed ignores them today because its
    visual pipeline is avatar + b-roll, not stills + I2V. They remain here
    so the dataclass is a single reference for "what varies visually"
    across channels.
    """

    flux_prompt_prefix: str = ""
    flux_prompt_suffix: str = ""
    grade_preset: str = ""
    parallax_target_pct: int = 0
    i2v_hero_pct: int = 0


@dataclass(frozen=True)
class SourceConfig:
    """How this channel picks topics.

    ``provider`` is the driver type: ``"rss_news"`` for CommonCreed (RSS
    feeds via :class:`NewsSourcer`), ``"reddit_signal"`` for Vesper (Reddit
    post titles as topic signal — never content). ``params`` is a
    provider-specific dict (subreddit list, time filter, min score for
    Vesper; feed URLs for CommonCreed).
    """

    provider: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Cadence:
    """Posting cadence."""

    shorts_per_day: int = 1
    longs_per_week: int = 0


@dataclass(frozen=True)
class PostizProfile:
    """Per-platform Postiz ``profile`` strings.

    Postiz's ``publish_post`` accepts ``ig_profile`` / ``yt_profile`` /
    (future) ``tt_profile`` kwargs that scope integrations to a specific
    connected account within the shared org. Empty string = platform
    disabled for this channel.
    """

    ig_profile: str = ""
    yt_profile: str = ""
    tt_profile: str = ""


@dataclass(frozen=True)
class ThumbnailStyle:
    """Channel thumbnail spec. Unit 4 (thumbnail compositor refactor)
    reads these fields to drive palette / aspect / typography per channel.
    Pre-Unit-4 this dataclass is informational only.
    """

    font_name: str = ""
    font_path: str = ""
    max_title_words: int = 7
    timestamp_motif: bool = False
    face_pct: int = 50


# ─── Top-level profile ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChannelProfile:
    """The complete per-channel profile.

    ``to_legacy_config_builder`` is a callable so each profile module can
    supply its own flattening logic (CommonCreed's legacy config has ~25
    env-derived fields; Vesper's will differ). The callable receives the
    current environment dict and returns the legacy-shaped config dict.
    """

    channel_id: str
    display_name: str
    niche: str
    voice: VoiceProfile
    postiz: PostizProfile
    cadence: Cadence = field(default_factory=Cadence)
    visual: VisualStyle = field(default_factory=VisualStyle)
    palette: Optional[BrandPalette] = None
    source: Optional[SourceConfig] = None
    thumbnail: Optional[ThumbnailStyle] = None
    platforms_enabled: List[str] = field(default_factory=list)
    languages_enabled: List[str] = field(default_factory=lambda: ["en"])
    telegram_prefix: str = ""
    # Per-channel CPM map populated by Unit 2b. Pre-Unit-2b this stays empty;
    # ``AnalyticsTracker.revenue_estimate`` falls back to its module-level
    # default when the profile doesn't set this.
    cpm_rates: Dict[str, Any] = field(default_factory=dict)
    # Profile-supplied flattener. Accepts the current environment dict and
    # returns the legacy ``config`` shape consumed by the existing pipeline.
    _legacy_config_builder: Optional[Callable[[Dict[str, str]], Dict[str, Any]]] = None

    def to_legacy_config(self, env: Dict[str, str]) -> Dict[str, Any]:
        """Return the flat dict the legacy pipeline's ``__init__`` expects."""
        if self._legacy_config_builder is None:
            raise NotImplementedError(
                f"Channel {self.channel_id!r} has no _legacy_config_builder. "
                "Profiles that drive the legacy pipeline must supply one."
            )
        return self._legacy_config_builder(env)


__all__ = [
    "BrandPalette",
    "Cadence",
    "ChannelProfile",
    "PostizProfile",
    "SourceConfig",
    "ThumbnailStyle",
    "VisualStyle",
    "VoiceProfile",
]
