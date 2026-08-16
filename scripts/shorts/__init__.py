"""End-to-end vertical shorts pipeline — local, no metered API spend.

    source (article URL | GitHub repo | raw text)
      -> script + visual identity      (claude -p)
      -> voiceover                     (Chatterbox, chunked)
      -> word timings                  (GPU Whisper large-v3)
      -> captions aligned to script    (not to the transcript)
      -> avatar segments               (LatentSync over real footage)
      -> designed motion graphics      (claude -p + HyperFrames)
      -> stock b-roll                  (Pexels)
      -> assembly with PIP/stacked layout
      -> finished 1080x1920 MP4

Every stage runs on the owner's own hardware or subscription. Measured cost per
60s short: about 35 minutes wall-clock and roughly $0.30 of electricity, against
$4.80-9.00 for the avatar alone on the metered VEED path.

Stage boundaries are deliberate: each writes its artifacts to the run directory
and can be re-run alone. A design that fails does not cost the voiceover.
"""
from __future__ import annotations

from .config import ShortsConfig
from .pipeline import ShortsPipeline, ShortsError
from .sources import load_source, SourceError

__all__ = [
    "ShortsConfig",
    "ShortsPipeline",
    "ShortsError",
    "load_source",
    "SourceError",
]
