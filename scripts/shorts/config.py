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
    # 150-165 words for a 60s short, i.e. about 2.7 words/sec.
    #
    # 190-210 was set from an assumed 3.3 w/s, but the delivered narration
    # measured 3.70 w/s (207 words in 56.0s) and sounds fast-forwarded. Normal
    # conversational speech is 2.3-2.8 w/s and energetic narration around 3.0,
    # so the script was well past the top of the range. Fewer words at a normal
    # pace also leaves room for the pauses that make a hook land.
    target_words_min: int = 150
    target_words_max: int = 165

    # v3 is cut from IMG_1774_4 (the owner's stated preference); v2 came from
    # _3. The two files have different audio despite identical duration and
    # transcript, so they are separate captures rather than re-encodes.
    voice_ref: str = "vishalan_voice_ref_v3.wav"
    # cfg_weight was NOT exposed by the service until 2026-08-17, so it sat at
    # the library default while exaggeration was tuned alone. They interact:
    # higher exaggeration speeds speech up, lower cfg_weight slows it into
    # something more deliberate.
    # 0.35, down from 0.5. Lower cfg_weight makes Chatterbox less clipped and
    # more deliberate, which is the other half of fixing the rushed delivery —
    # word count sets how much has to be said, this sets how it is said.
    cfg_weight: float = 0.35
    # 0.4. Stock is 0.5 and the deployed service defaults to 0.3. Exaggeration
    # and speed interact: higher values speed the delivery up, so 0.5 was
    # compounding the rushed feel. 0.4 keeps expression without the hurry.
    exaggeration: float = 0.4
    # chatterbox/tts.py:249 hardcodes max_new_tokens=1000 == ~40s of audio.
    # Anything longer is silently truncated mid-sentence unless chunked.
    tts_max_chars_per_chunk: int = 380

    # --- audio mastering ------------------------------------------------
    lufs_target: float = -14.0      # YouTube's published figure; TikTok/IG publish none
    true_peak_db: float = -1.0
    highpass_hz: int = 70

    # Voice tone. Chatterbox output is thin and slightly boxy on this reference,
    # so the chain adds weight without muddying it:
    #   low shelf   +3.5 dB @ 110 Hz  — chest and body
    #   bell        -2.5 dB @ 320 Hz  — the "box" that makes weight sound muddy
    #   presence    +2.0 dB @ 4.5 kHz — consonant clarity, so added low end does
    #                                   not cost intelligibility
    # Gentle compression after EQ evens the delivery without pumping.
    voice_eq_enabled: bool = True
    voice_low_shelf_db: float = 3.5
    voice_low_shelf_hz: int = 110
    voice_mud_cut_db: float = -2.5
    voice_mud_hz: int = 320
    voice_presence_db: float = 2.0
    voice_presence_hz: int = 4500

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
    # The separate design stage is OFF. It ran DesignBriefGenerator through
    # HyperFrames — a second design system with a second quality bar, which was
    # the original argument for routing everything through one. Now that the
    # director renders Remotion compositions, it IS that one path: same
    # components, same timing rules, chosen per beat instead of per anchor word.
    # Set above 0 only to run the legacy HyperFrames path alongside.
    max_designs: int = 0
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
    # 3.2s, down from 4.5. The old figure was a COST compromise, not an
    # aesthetic one: each designed graphic took ~10 minutes through HyperFrames,
    # so a denser slate meant an unusable render time. A Remotion composition
    # takes ~3 SECONDS, which removes the constraint entirely — and density was
    # always the honest fix for the reader-page bed filling half the video with
    # small body text.
    broll_cadence_s: float = 3.2
    # Generated cinematic footage is OFF, on measured quality rather than on
    # principle. LTX-Video 2B installs and runs on this 3090 — 80-98s for a 3s
    # clip at 1080x998, which would be affordable — but the output is unusable:
    # two attempts, one terse prompt and one long LTX-style description at 40
    # steps, both produced a near-black frame with a soft blue smear, no
    # recognisable subject and almost no motion. The near-square panel geometry
    # is likely well outside what a 2B model handles.
    #
    # Left wired and gated rather than deleted: the renderer, the subprocess
    # isolation and the capability check are all correct and worth keeping for a
    # stronger local model. Set True to re-enable, and LOOK at the clip before
    # trusting it — a garbled b-roll shot is worse than a page panel.
    ai_video_enabled: bool = False
    # Ceiling on designed clips per video. Each one costs a claude -p call plus
    # a render, so this bounds the per-video cost, not the aesthetics.
    # 14 designed clips is roughly 45s of rendering, against about 2.5 hours
    # through the old path. The cap now bounds the PLAN, not the clock.
    broll_max_designed: int = 14
    # The real anti-repetition rule, replacing the old total cap: no single
    # graphic type more than twice per video. Page footage shown twice is
    # evidence; shown five times it becomes the subject.
    # 3 rather than 2: with 14 slots to fill from 8 composition types plus the
    # page-derived ones, a cap of 2 forces weak-fit choices near the end of the
    # plan. The rule is still "no type becomes the video's identity".
    broll_max_per_kind: int = 3
    # A gap must be at least this long to be worth cutting away for. Below it,
    # the cut costs more attention than the content returns.
    min_gap_for_broll_s: float = 3.5
    # Never cut to page footage twice within this window. Was 12.0, which
    # combined with 14s-apart anchors to thin the slate to one clip per 12s no
    # matter how dense the plan was.
    min_broll_spacing_s: float = 6.0
    # No single shot may hold longer than this. Beyond it a held frame reads as
    # a stall even when the narration is still moving.
    #
    # 3.5 rather than 4.5: at 4.5 the panel still measured four holds over the
    # limit, because a subdivided span only reads as a cut if the two views
    # differ enough, and two dense-text views sometimes do not. Splitting more
    # finely gives each view a better chance of landing on visibly different
    # material, and 3.5s is still above the ~2.5s cadence of both references.
    max_static_hold_s: float = 3.5

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
