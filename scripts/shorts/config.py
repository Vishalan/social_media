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

    voice_ref: str = "vishalan_voice_ref_v2.wav"
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
    intelligence_model: str = "sonnet"

    # --- visuals --------------------------------------------------------
    width: int = 1080
    height: int = 1920
    fps: int = 25
    layout: str = "pip_circle"      # pip_circle | half_stacked | full
    caption_font: str = "/opt/commoncreed/assets/fonts/Inter-Bold.ttf"
    caption_size: int = 54
    # 0.80H keeps captions clear of the PIP (which sits 0.60-0.79H) and above
    # the bottom UI strip.
    caption_y_frac: float = 0.80
    whisper_model: str = "large-v3"

    # --- b-roll ---------------------------------------------------------
    broll_enabled: bool = True
    broll_max_clips: int = 4
    broll_clip_s: float = 2.2

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

    def path(self, *parts: str) -> str:
        return os.path.join(self.work_dir, *parts)
