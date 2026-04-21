"""Vesper channel profile.

Second concrete channel. Vesper ships faceless horror stories
(picture-and-voiceover, Archivist narrator persona, night-shift /
rural-America / liminal-spaces sub-niche). The profile declares
everything downstream code needs to route calls per-channel — palette,
typography, voice reference, source config, Postiz profile strings,
CPM rates. The SFX pack registration (below) runs at import time so
``pick_sfx(..., pack="vesper")`` resolves without explicit wiring.

Scope note: v1 is shorts-only (``longs_per_week=0``) — long-form gates
to v1.1 on retention data. Multi-language is declared on the profile as
``languages_enabled=['en']`` only; the actual translation pipeline
lands in the ``story-channels-multilang`` brainstorm once English
traction is proven.
"""

from __future__ import annotations

from pathlib import Path
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


# ─── Brand palette (Vesper — near-black / bone / oxidized-blood / graphite) ──
# Source: auto-memory project_vesper_brand_palette.md. Explicitly chosen to
# be distinct from CommonCreed's navy at thumbnail scale.

PALETTE = BrandPalette(
    primary="#E8E2D4",        # bone / aged paper — caption & title text
    background="#0A0A0C",     # near-black — thumbnail matte
    accent="#8B1A1A",         # oxidized blood — keyword-punch accent
    shadow="#2C2826",         # warm graphite — shadows, plate backgrounds
)


# ─── SFX pack registration ──────────────────────────────────────────────────
# Runs at module import so any call to ``pick_sfx(..., pack="vesper")``
# after the profile is loaded finds the pack.
#
# Actual .wav files are sourced pre-launch per the launch runbook.
# Until they're populated, ``pick_sfx`` raises FileNotFoundError — this
# is the correct fail-loud behavior because rendering a Vesper video
# without the horror SFX pack would ship a tech-whoosh-on-horror-cut
# tone mismatch (the exact cross-bleed the plan guards against).

_VESPER_SFX_DIR = Path(__file__).resolve().parent.parent / "assets" / "vesper" / "sfx"

# Vesper's per-category filenames. These map the stable cut/punch/reveal/tick
# axes to horror-tuned sounds (drones, sub-bass, risers, reverb-tails, ambient
# beds, distant stingers). The names intentionally carry a ``vesper_`` prefix
# so a misconfigured pack lookup surfaces immediately during integration.
_VESPER_CATEGORY_FILES: Dict[str, Dict[str, list[str]]] = {
    "cut": {
        "light": ["vesper_cut_rev_short", "vesper_cut_dust_drop"],
        "heavy": ["vesper_cut_sub_slam", "vesper_cut_reverb_tail"],
    },
    "punch": {
        "light": ["vesper_punch_wooddrop", "vesper_punch_tape_tick"],
        "heavy": ["vesper_punch_subhit", "vesper_punch_bone_snap"],
    },
    "reveal": {
        "light": ["vesper_reveal_glass_chime", "vesper_reveal_breath_in"],
        "heavy": ["vesper_reveal_drone_enter", "vesper_reveal_shadow_pass"],
    },
    "tick": {
        "light": ["vesper_tick_watch_faint"],
        "heavy": ["vesper_tick_clock_hard"],
    },
}


def _register_sfx_pack() -> None:
    """Register Vesper's SFX pack at import time.

    Isolated helper so tests can invoke it explicitly (or patch it)
    without triggering surprising side-effects just from importing the
    profile module.
    """
    # Local import — avoids forcing ``scripts/`` onto the import path at
    # module-level, which would fail for profile-only test environments
    # that don't need the audio stack.
    try:
        from audio.sfx import SfxPack, register_pack
    except ImportError:
        try:
            from scripts.audio.sfx import SfxPack, register_pack
        except ImportError:
            # Tolerated at import time: profile-only consumers (tests,
            # docs generators) don't need the SFX pack registered. The
            # Vesper pipeline's entry-point code imports audio.sfx
            # separately and will re-register there.
            return

    register_pack(SfxPack(
        name="vesper",
        root_dir=_VESPER_SFX_DIR,
        category_files=_VESPER_CATEGORY_FILES,  # type: ignore[arg-type]
    ))


_register_sfx_pack()


# ─── Legacy-config builder ──────────────────────────────────────────────────
# Vesper's pipeline orchestrator is landing in Unit 11 as a SIBLING to
# CommonCreedPipeline, not an extension — so the "legacy config dict"
# shape doesn't need every CommonCreed field (no avatar, no HeyGen, no
# Kling, no VEED). What Vesper needs is the minimum flat-dict the
# future VesperPipeline(config) constructor will consume, plus the
# profile-identity fields downstream modules read unconditionally.
#
# For now, this builder produces a subset + profile metadata. Fields
# will be added as Units 6-11 land. Unit 11 pins the final shape.


def _build_legacy_config(env: Dict[str, str]) -> Dict[str, Any]:
    return {
        # Channel identity — read by all channel-aware modules.
        "channel_id": "vesper",
        "channel_display_name": "Vesper",
        # Anthropic for the story generator (Unit 7).
        "anthropic_api_key": env.get("ANTHROPIC_API_KEY", ""),
        # Chatterbox — Vesper uses the same self-hosted sidecar as
        # CommonCreed, with a distinct reference audio clip (Unit 8).
        "voice_provider": "chatterbox",
        "chatterbox_reference_audio": env.get(
            "VESPER_CHATTERBOX_REFERENCE_AUDIO",
            # In-container path; the sidecar mounts host assets under /app/refs.
            "/app/refs/vesper/archivist.wav",
        ),
        "chatterbox_endpoint": env.get("CHATTERBOX_ENDPOINT", ""),
        "chatterbox_device": env.get("CHATTERBOX_DEVICE", "cuda"),
        # Chatterbox prosody cues — silently dropped by current client per
        # Unit 8, but carried through for the owner-facing voice bake-off.
        "chatterbox_exaggeration": 0.35,
        "chatterbox_cfg": 0.3,
        # Telegram — single-owner bot shared with CommonCreed (Unit 11).
        "telegram_bot_token": env.get("TELEGRAM_BOT_TOKEN", ""),
        "telegram_owner_user_id": env.get("TELEGRAM_OWNER_USER_ID", ""),
        # Postiz — shared org key, per-channel profile strings.
        "postiz_api_key": env.get("POSTIZ_API_KEY", ""),
        "postiz_base_url": env.get("POSTIZ_BASE_URL", ""),
        # Reddit signal source (Unit 6) — no auth today (public JSON).
        # Kept on the config dict so future paid-tier migration is a
        # config change, not a code change.
        "reddit_user_agent": env.get(
            "VESPER_REDDIT_USER_AGENT",
            "VesperBot/0.1 (topic signal crawler)",
        ),
        # fal.ai — Flux stills (Unit 9).
        "fal_api_key": env.get("FAL_API_KEY", ""),
        # SFX pack name — threaded into VideoEditor(sfx_pack=...).
        "sfx_pack": "vesper",
    }


# ─── Profile ────────────────────────────────────────────────────────────────

PROFILE = ChannelProfile(
    channel_id="vesper",
    display_name="Vesper",
    niche="horror-stories",
    voice=VoiceProfile(
        provider="chatterbox",
        reference_audio="/app/refs/vesper/archivist.wav",
        # Low / tense / semi-whispered register for the Archivist persona.
        # These values flow into ``ChatterboxVoiceGenerator.generate`` if
        # the engine ever honors them; today they're documented per-channel
        # style notes that the owner uses during the voice bake-off.
        exaggeration=0.35,
        cfg=0.3,
    ),
    postiz=PostizProfile(
        ig_profile="vesper",
        yt_profile="vesper",
        tt_profile="vesper",  # Unit 12 wires TikTok into the Postiz client.
    ),
    cadence=Cadence(shorts_per_day=1, longs_per_week=0),  # v1: shorts only
    visual=VisualStyle(
        # Flux prompt prefix + suffix — a starting point. Unit 9 benchmarks
        # variant selection; the full reference-still set lives in
        # assets/vesper/visual_refs/ once sourced pre-launch.
        flux_prompt_prefix=(
            "cinematic horror photograph, moody low-key lighting, "
            "35mm film aesthetic, night-shift atmosphere"
        ),
        flux_prompt_suffix=(
            "shallow DOF, film grain, desaturated cool shadows, "
            "anamorphic, no text no logo no watermark"
        ),
        grade_preset="vesper_graphite",
        # Anti-slop targets (Unit 9 + Unit 10) — parallax on ≥30% of
        # still beats, I2V hero beats on ~20%.
        parallax_target_pct=30,
        i2v_hero_pct=20,
    ),
    palette=PALETTE,
    source=SourceConfig(
        # CRITICAL: Vesper uses Reddit as a TOPIC SIGNAL LAYER only.
        # Post titles + scores inform topic selection. The story itself
        # is LLM-original, seeded by the signal topic + the archetype
        # library (see Unit 7). Post BODIES are never ingested — this
        # is the research-driven pivot from the brainstorm's R4 and
        # sits in tension with the Reddit commercial-use posture.
        provider="reddit_signal",
        params={
            "subreddits": [
                "nosleep",
                "LetsNotMeet",
                "ThreeKings",
                "Ruleshorror",
                "creepyencounters",
            ],
            "min_score": 500,
            "time_filter": "day",
            "limit": 10,
            "archetype_library": "data/horror_archetypes.json",
        },
    ),
    thumbnail=ThumbnailStyle(
        font_name="CormorantGaramond-Bold",
        # Font file sourced pre-launch (Unit 13 runbook). Until then,
        # Vesper thumbnail fallbacks to Inter-Black via the same
        # font_candidates search path the Unit 4 compositor uses.
        font_path="assets/fonts/CormorantGaramond-Bold.ttf",
        max_title_words=7,        # Wider cap than the plan's default 5;
                                  # horror hooks benefit from the room.
        timestamp_motif=True,     # ``02:47`` cold-open format signature.
        face_pct=50,              # ~50% of thumbnails include a face
                                  # (witness archetype, never The Archivist
                                  # herself — see narrator visual grammar).
    ),
    platforms_enabled=["instagram_reels", "youtube_shorts", "tiktok"],
    languages_enabled=["en"],
    telegram_prefix="[Vesper]",
    # Per-channel CPM (USD per 1000 views) — horror RPM range.
    # Plan note: actual values land $1-3 under limited-ads, $4-10 top
    # quartile. Conservative midpoint chosen here so the dashboard
    # doesn't over-promise revenue before first real metrics arrive.
    cpm_rates={
        "youtube": 5.00,
        "youtube_limited_ads": 2.00,  # narrative-horror under limited-ads policy
        "tiktok": 0.20,
        "instagram": 0.35,
        "default": 0.40,
    },
    _legacy_config_builder=_build_legacy_config,
)


__all__ = ["PALETTE", "PROFILE"]
