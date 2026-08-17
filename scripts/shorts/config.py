"""Configuration for the shorts pipeline.

Defaults are the values that were actually measured working on the Ubuntu
server, not aspirational ones. Anything that had to be discovered the hard way
carries the reason inline so it is not "tidied" back to a broken value.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ShortsConfig:
    """Everything the pipeline needs to run one short."""

    # --- identity -------------------------------------------------------
    run_id: str = "short"
    work_root: str = "/home/vishalan/shorts"

    # --- narration ------------------------------------------------------
    # 190-210 words is 58-63s at ~3.3 words/sec. The target is SIXTY seconds:
    # earlier runs asked for 120-140 words and produced 40s pieces.
    target_words_min: int = 190
    target_words_max: int = 210

    # v3 is cut from IMG_1774_4 (the owner's stated preference); v2 came from
    # _3. The two files have different audio despite identical duration and
    # transcript, so they are separate captures rather than re-encodes.
    voice_ref: str = "vishalan_voice_ref_v3.wav"
    # cfg_weight was NOT exposed by the service until 2026-08-17, so it sat at
    # the library default while exaggeration was tuned alone. They interact:
    # higher exaggeration speeds speech up, lower cfg_weight slows it into
    # something more deliberate.
    cfg_weight: float = 0.5
    # Stock default is 0.5. The deployed service defaults to 0.3, which is
    # FLATTER than stock on a channel that needs punchy delivery.
    exaggeration: float = 0.5
    # chatterbox/tts.py:249 hardcodes max_new_tokens=1000 == ~40s of audio.
    # Anything longer is silently truncated mid-sentence unless chunked.
    tts_max_chars_per_chunk: int = 380

    # --- audio mastering ------------------------------------------------
    lufs_target: float = -14.0      # YouTube's published figure; TikTok/IG publish none
    true_peak_db: float = -1.0
    highpass_hz: int = 70

    # --- avatar ---------------------------------------------------------
    latentsync_endpoint: str = "http://172.18.0.7:7778"
    chatterbox_endpoint: str = "http://172.18.0.8:7777"
    inference_steps: int = 20
    guidance_scale: float = 1.5
    seed: int = 1247
    # 9-14s segments give natural cut cadence and keep each render inside a
    # window the gesture library can actually satisfy.
    segment_min_s: float = 9.0
    segment_max_s: float = 14.0
    # Beat energy by position: hook wants gesture, close wants stillness.
    segment_tags: tuple[str, ...] = ("animated", "animated", "moderate",
                                     "moderate", "calm", "calm")

    gesture_source: str = "/opt/commoncreed/assets/input_media/IMG_1774_3.mp4"
    gesture_manifest: str = "/opt/commoncreed/assets/gesture_clips/manifest.json"

    # --- design ---------------------------------------------------------
    max_designs: int = 4
    design_concurrency: int = 4
    design_timeout_s: int = 1800
    # Look at each rendered graphic and re-render once if it is visibly
    # broken. HyperFrames' own lint/check passed a card whose hero overlapped
    # its support line and a terminal whose cursor sat on a letter.
    review_designs: bool = True
    design_attempts: int = 2
    intelligence_model: str = "sonnet"

    # --- visuals --------------------------------------------------------
    width: int = 1080
    height: int = 1920
    fps: int = 25
    # half_stacked is the default and "full" is deliberately NOT offered as a
    # channel default: the presenter alone filling the frame for seconds at a
    # time is dead screen time in short-form. Every span carries content in the
    # top panel — a designed graphic at an anchor, the source page-roll
    # otherwise.
    layout: str = "half_stacked"    # half_stacked | pip_circle
    # When no design covers a span, fill the content panel with source page-roll
    # rather than letting the avatar go full-frame.
    fill_gaps_with_pageroll: bool = True
    # Caption look lives in branding.CaptionStyle — the channel constant — so a
    # restyle happens in one place rather than in the assembler.
    #
    # Position is layout-dependent and set at assembly time, not here:
    #   half_stacked -> just BELOW the panel seam, so the caption reads as a
    #                   band between the content and the presenter rather than
    #                   sitting on the presenter's face.
    #   pip_circle   -> lower third, clear of the PIP.
    # Leave None to derive; set a float to override.
    caption_y_frac: Optional[float] = None

    def caption_y(self) -> float:
        """Vertical position of the caption baseline, as a fraction of frame."""
        if self.caption_y_frac is not None:
            return self.caption_y_frac
        if self.layout == "half_stacked":
            # The seam is at content_frac (0.52). Sitting the caption just
            # under it keeps it off the face and out of the bottom UI strip,
            # and puts it near the optical centre where the eye already is.
            return (self.content_height / self.height) + 0.015
        return 0.78
    whisper_model: str = "large-v3"

    # --- b-roll ---------------------------------------------------------
    # "pageroll" captures the actual source page; "stock" searches Pexels.
    # Stock reliably returns footage that is topically adjacent but
    # substantively unrelated — strangers in a coworking space for a story
    # about a repository — which reads as filler, so it is not the default.
    # "director" plans a varied slate — a different graphic type per beat,
    # each chosen for what that beat is about. "pageroll" is the older
    # single-type path; "stock" searches Pexels and is kept only for sources
    # with no capturable page.
    broll_provider: str = "director"   # director | pageroll | stock | none
    broll_enabled: bool = True
    # Match page regions to narration beats by looking at them, rather than
    # walking evenly down the page and hoping.
    smart_regions: bool = True
    # Used by the older single-type paths (pageroll, stock, smart_regions).
    # The director path uses the cadence knobs below instead.
    #
    # This was once the global cap for every path, set to 4 back when all
    # b-roll was page footage: five webpage cutaways made the video mostly
    # webpage. That reasoning was right about the PAGE and wrong as a total —
    # once the director produces a different graphic type per beat, a total cap
    # throttles variety rather than repetition. The concern is now expressed
    # exactly, as a per-kind cap.
    broll_max_clips: int = 4
    broll_clip_s: float = 2.6

    # Aim for a fresh visual roughly this often. Both reference shorts cut
    # about every 2.5s; a designed graphic every ~4.5s plus presenter and page
    # spans between them lands there. Measured on the previous build: 5 evenly
    # spaced beats across 56s put anchors 14s apart, which left three static
    # holds of 4.5s, 5.1s and 7.0s — the last is longer than either reference
    # holds ANY shot.
    broll_cadence_s: float = 4.5
    # Ceiling on designed clips per video. Each one costs a claude -p call plus
    # a render, so this bounds the per-video cost, not the aesthetics.
    broll_max_designed: int = 10
    # The real anti-repetition rule, replacing the old total cap: no single
    # graphic type more than twice per video. Page footage shown twice is
    # evidence; shown five times it becomes the subject.
    broll_max_per_kind: int = 2
    # A gap must be at least this long to be worth cutting away for. Below it,
    # the cut costs more attention than the content returns.
    min_gap_for_broll_s: float = 3.5
    # Never cut to page footage twice within this window. Was 12.0, which
    # combined with 14s-apart anchors to thin the slate to one clip per 12s no
    # matter how dense the plan was.
    min_broll_spacing_s: float = 6.0
    # No single shot may hold longer than this. Beyond it a held frame reads as
    # a stall even when the narration is still moving.
    max_static_hold_s: float = 4.5

    @property
    def work_dir(self) -> str:
        return os.path.join(self.work_root, self.run_id)

    @property
    def design_dir(self) -> str:
        return os.path.join(self.work_dir, "design")

    @property
    def broll_dir(self) -> str:
        # Bug guard: an earlier run substituted paths with sed and wrote b-roll
        # into a DIFFERENT run's directory, so the assembler found none and
        # silently produced a video with no stock footage. Deriving every path
        # from work_dir makes that class of mistake impossible.
        return os.path.join(self.work_dir, "broll")

    @property
    def content_height(self) -> int:
        """Height of the content panel in a stacked layout (even for h264)."""
        return int(self.height * 0.52) // 2 * 2

    def path(self, *parts: str) -> str:
        return os.path.join(self.work_dir, *parts)
