"""Word-level ASS caption generation for Vesper.

Two public functions:

  * :func:`transcribe_voice` — run faster-whisper on a voice MP3 and
    return word-level ``{word, start, end}`` dicts.
  * :func:`build_ass_captions` — produce an ASS subtitle file string
    from those dicts, styled with Vesper's palette (bone primary,
    oxidized-blood accent, graphite shadow) + typography.

Sibling of :meth:`VideoEditor._build_ass_captions` in spirit — same
bord-as-bg active-word highlight approach — but standalone so the
assembler doesn't have to instantiate a VideoEditor just to get a
caption string.

Burning is the assembler's job (FFmpeg ``-vf ass=...``). This module
only knows about text + timings + style.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920


@dataclass(frozen=True)
class CaptionStyle:
    """Per-channel caption typography + palette.

    Vesper callers build this from ``profile.palette`` + a font choice;
    tests construct it directly. Colors are hex strings (``#RRGGBB``)
    so the same values flow through the brand module + tests without
    conversion drift.
    """

    primary: str          # inactive-word fill (Vesper: bone #E8E2D4)
    accent: str           # active-word highlight ring (Vesper: #8B1A1A)
    shadow: str           # outline/shadow (Vesper: graphite #2C2826)
    font_name: str = "CormorantGaramond-Bold"
    fontsize: int = 58              # inactive (Vesper is smaller than CC)
    active_fontsize: int = 70       # active pop


# ─── Transcription ─────────────────────────────────────────────────────────


def transcribe_voice(
    audio_path: str,
    *,
    model_name: str = "base",
    device: str = "cpu",
    compute_type: str = "int8",
) -> List[dict]:
    """Return word-level timing dicts from ``audio_path``.

    Returns ``[]`` when faster-whisper isn't installed so the assembler
    falls back to a raw-video (no-caption) render rather than crashing.
    The pipeline logs a WARNING in that case — captions are plan-
    mandatory, so running without them is a degraded mode the operator
    needs to see.
    """
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        logger.warning(
            "transcribe_voice: faster-whisper not installed — captions "
            "disabled. Retention targets assume captions, so install "
            "faster-whisper==1.2.1 before shipping."
        )
        return []

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments, _ = model.transcribe(audio_path, word_timestamps=True)
    words: List[dict] = []
    for seg in segments:
        for w in (seg.words or []):
            text = w.word.strip()
            if not text:
                continue
            words.append({
                "word": text,
                "start": float(w.start),
                "end": float(w.end),
            })
    return words


# ─── ASS builder ───────────────────────────────────────────────────────────


def _hex_to_ass_color(hex_color: str) -> str:
    """`#RRGGBB` → ASS `&H00BBGGRR`.

    ASS uses BGR with a 2-hex alpha prefix. Alpha=00 means opaque.
    """
    s = hex_color.lstrip("#")
    if len(s) != 6:
        raise ValueError(f"expected #RRGGBB, got {hex_color!r}")
    r, g, b = s[0:2], s[2:4], s[4:6]
    return f"&H00{b}{g}{r}".upper()


def _ts(seconds: float) -> str:
    """ASS timestamp `H:MM:SS.cc`."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_ass_captions(
    segments: List[dict],
    style: CaptionStyle,
    *,
    output_width: int = OUTPUT_WIDTH,
    output_height: int = OUTPUT_HEIGHT,
    y_fraction: float = 0.75,
) -> str:
    """Build a complete ASS subtitle string for ``segments``.

    Each word becomes its own ``Dialogue:`` line. The active word
    renders in the ``CaptionActive`` style with a thick accent border
    (bord-as-bg, same approach as the CommonCreed VideoEditor); the
    default ``Caption`` style uses a shadow-color outline on primary-
    color text.

    Empty/whitespace-only words are dropped with a warning rather than
    emitted — pipeline drift from a whisper/LLM mismatch must not
    produce malformed ASS.
    """
    primary = _hex_to_ass_color(style.primary)
    accent = _hex_to_ass_color(style.accent)
    shadow = _hex_to_ass_color(style.shadow)

    cx = output_width // 2
    cy = int(output_height * y_fraction)

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {output_width}\n"
        f"PlayResY: {output_height}\n"
        "WrapStyle: 0\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Caption,{style.font_name},{style.fontsize},"
        f"{primary},{primary},{shadow},{shadow},"
        "-1,0,0,0,100,100,0,0,1,3,2,5,0,0,0,1\n"
        f"Style: CaptionActive,{style.font_name},{style.active_fontsize},"
        f"{primary},{primary},{accent},{accent},"
        "-1,0,0,0,100,100,0,0,1,12,0,5,0,0,0,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )

    lines: List[str] = []
    dropped = 0
    for seg in segments:
        word = (seg.get("word") or "").strip()
        if not word:
            dropped += 1
            continue
        start = float(seg["start"])
        end = float(seg["end"])
        if end <= start:
            dropped += 1
            continue
        safe_word = word.replace("{", "").replace("}", "").replace("\\", "")
        lines.append(
            f"Dialogue: 0,{_ts(start)},{_ts(end)},"
            f"CaptionActive,,0,0,0,,{{\\an5\\pos({cx},{cy})}}{safe_word}"
        )

    if dropped:
        logger.warning(
            "build_ass_captions: dropped %d malformed word segment(s); "
            "pipeline drift between whisper + story expected",
            dropped,
        )

    return header + "\n".join(lines) + ("\n" if lines else "")


def caption_style_from_palette(palette: Any, thumbnail_style: Any) -> CaptionStyle:
    """Build a :class:`CaptionStyle` from a channel profile's palette +
    thumbnail style. Fonts come from ``thumbnail_style.font_name`` to
    keep Vesper's typography consistent across the short."""
    font_name = getattr(thumbnail_style, "font_name", None) or "Inter"
    return CaptionStyle(
        primary=palette.primary,
        accent=palette.accent,
        shadow=palette.shadow,
        font_name=font_name,
    )


__all__ = [
    "CaptionStyle",
    "build_ass_captions",
    "caption_style_from_palette",
    "transcribe_voice",
]
