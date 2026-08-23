"""Background score: a local CC0 library, chosen per story and ducked under speech.

Three separable jobs, and they fail in different ways:

* SOURCING must be licence-safe. This channel is intended to earn, so anything
  requiring attribution puts an obligation on every video forever, and anything
  non-commercial is simply wrong. Archive.org's CC0 audio is a public-domain
  dedication — no credit, no restriction, no expiry. FreePD, the obvious
  alternative, closed in 2025; a hard-coded list of its URLs would have rotted
  silently.

* SELECTION must fit the story and not repeat. A ledger of recent picks makes
  rotation deterministic rather than random, because random selection over a
  small library repeats far more often than people expect.

* MIXING is where "background music" becomes a problem. A bed at a fixed low
  volume still masks consonants — the energy that makes speech intelligible
  sits in the same 1-4 kHz band most music occupies. Ducking the music from
  the voice itself is the only mix that stays out of the way when someone is
  talking and fills the room when they are not.

Broadcast targets used below: narration -14 LUFS, music bed -30 to -35 LUFS
under narration. Those are the published numbers, not taste.
"""
from __future__ import annotations

import json
import logging
import os
import random
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from .net import BROWSER_UA

logger = logging.getLogger(__name__)

LIBRARY = Path(os.environ.get("COMMONCREED_MUSIC_DIR",
                              "/opt/commoncreed/assets/music"))
LEDGER = LIBRARY / "_recent.json"

# The moods a short actually needs. Deliberately few: a larger taxonomy would
# be guessing at distinctions the mix cannot express under a voice at -32 LUFS.
# Terms are ORed. Archive.org's query parser ANDs bare words, so a list of
# four adjectives asked for items matching ALL of them and returned nothing —
# three of the four moods came back empty and the library never filled.
MOODS: dict[str, list[str]] = {
    "tense":      ["dark ambient", "drone", "suspense", "cinematic tension"],
    "driving":    ["electronic", "synthwave", "techno", "uptempo instrumental"],
    "reflective": ["ambient", "piano solo", "calm instrumental", "downtempo"],
    "bright":     ["upbeat instrumental", "chiptune", "funk instrumental", "pop instrumental"],
}
DEFAULT_MOOD = "driving"

# Items whose own metadata says they are speech. Archive.org's CC0 audio is
# mostly NOT music — it is podcasts, sermons, lectures and field recordings —
# so this filter does more work than the search query does.
# Titles that betray a commercial recording mislabelled as CC0.
#
# Archive.org's licence field is SELF-DECLARED by uploaders and is frequently
# wrong. The first search returned "MissionImpossibleTheme" and "Starboy" as
# public-domain audio, which they plainly are not. On a monetised channel a
# false positive here is a copyright claim, so anything that reads like a
# commercial release is dropped even though the metadata says it is free.
# This is a filter against upload errors, not a judgement about the works.
_COMMERCIAL_WORDS = (
    "theme", "soundtrack", "ost", "cover", "remix", "official", "feat",
    "ft.", "billboard", "top 40", "hits", "single", "album version",
    "bandas sonoras", "bandas-sonoras", "banda sonora", "trailer music",
    "movie", "film score", "tv series", "karaoke", "mashup", "bootleg",
)

_SPEECH_WORDS = (
    "podcast", "sermon", "lecture", "interview", "audiobook", "talk",
    "speech", "reading", "commentary", "news", "radio show", "episode",
    "chapter", "story", "conversation", "discussion", "meeting", "call",
)

_SEARCH = "https://archive.org/advancedsearch.php"
_META = "https://archive.org/metadata"


def _get_json(url: str, timeout: int = 45):
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _search(mood: str, rows: int = 40) -> list[str]:
    """CC0 audio item ids for a mood, best-ranked first."""
    terms = MOODS.get(mood, MOODS[DEFAULT_MOOD])
    ored = " OR ".join(f'"{t}"' for t in terms)
    # Restricted to `netlabels`, and this is the licence safeguard that
    # actually works.
    #
    # Archive.org's CC0 field is self-declared, and keyword filtering cannot
    # catch a mislabelled commercial track: the first build pulled in "Starboy"
    # tagged public domain, and no word list contains every artist and song
    # title. The risk turned out to be structural rather than lexical. That
    # upload sits in `opensource_audio`/`community` — the unmoderated public
    # bucket — while every legitimate track came from `netlabels`, a curated
    # set of labels whose artists release under Creative Commons deliberately.
    # Excluding the community bucket removes the entire class of error instead
    # of chasing individual instances of it.
    query = (f'mediatype:audio AND licenseurl:*zero* '
             f'AND collection:netlabels AND ({ored})')
    params = [("q", query), ("rows", str(rows)), ("page", "1"),
              ("output", "json"), ("sort[]", "downloads desc")]
    params += [("fl[]", f) for f in ("identifier", "title", "subject")]
    docs = _get_json(f"{_SEARCH}?{urllib.parse.urlencode(params)}")
    out = []
    for d in docs["response"]["docs"]:
        blob = " ".join(str(d.get(k, "")) for k in ("title", "subject")).lower()
        ident = str(d.get("identifier", "")).lower()
        if any(w in blob for w in _SPEECH_WORDS):
            continue
        if any(w in blob or w in ident for w in _COMMERCIAL_WORDS):
            logger.debug("skipping %s — reads as a commercial release", ident)
            continue
        out.append(d["identifier"])
    return out


def _pick_file(item_id: str) -> Optional[tuple[str, float]]:
    """A usable MP3 inside an item: (url, seconds).

    Length is the filter that matters. Under 45s there is nothing to loop
    without an audible seam every few seconds; over 12 minutes is usually a
    lecture or a DJ set that slipped through the metadata check.
    """
    try:
        meta = _get_json(f"{_META}/{item_id}")
    except Exception:                               # noqa: BLE001 — skip item
        return None
    for f in meta.get("files", []):
        if not str(f.get("name", "")).lower().endswith(".mp3"):
            continue
        try:
            length = float(f.get("length") or 0)
        except (TypeError, ValueError):
            continue
        if not (45.0 <= length <= 720.0):
            continue
        server = meta.get("server") or "archive.org"
        d = meta.get("dir", "")
        name = urllib.parse.quote(f["name"])
        return f"https://{server}{d}/{name}", length
    return None


def _is_musical(path: Path) -> bool:
    """Reject speech that survived the metadata filter.

    Discriminates on LOW-FREQUENCY energy. Speech has almost nothing below
    ~150 Hz — the male fundamental sits above it and there is no instrument
    under it — whereas virtually any produced music carries bass there. It is
    a blunt test, but it is the one that separates the two classes most
    reliably without loading an audio library on the host.
    """
    def rms_db(filt: str) -> float:
        r = subprocess.run(
            ["ffmpeg", "-v", "info", "-i", str(path), "-t", "45",
             "-af", f"{filt},astats=metadata=1:reset=0", "-f", "null", "-"],
            capture_output=True, text=True)
        vals = [float(x.split(":")[1]) for x in r.stderr.split("\n")
                if "RMS level dB" in x and ":" in x
                and x.split(":")[1].strip().replace("-", "").replace(".", "").isdigit()]
        return max(vals) if vals else -99.0

    low = rms_db("lowpass=f=150")
    full = rms_db("anull")
    if full <= -90:
        return False
    ratio = low - full            # dB of low band relative to the whole
    ok = ratio > -26.0
    if not ok:
        logger.debug("%s rejected: low band %.1f dB below full — speech-like",
                     path.name, -ratio)
    return ok


def ensure_library(per_mood: int = 4) -> dict[str, list[Path]]:
    """Download enough tracks that rotation has something to rotate.

    Downloads only what is missing, so a run with a warm library costs nothing
    and the pipeline works offline afterwards.
    """
    have: dict[str, list[Path]] = {}
    for mood in MOODS:
        d = LIBRARY / mood
        d.mkdir(parents=True, exist_ok=True)
        tracks = sorted(d.glob("*.mp3"))
        if len(tracks) >= per_mood:
            have[mood] = tracks
            continue
        logger.info("Music: %s has %d/%d tracks — fetching",
                    mood, len(tracks), per_mood)
        for item in _search(mood):
            if len(tracks) >= per_mood:
                break
            got = _pick_file(item)
            if not got:
                continue
            url, _ = got
            dst = d / f"{item[:48]}.mp3"
            if dst.exists():
                continue
            try:
                req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
                with urllib.request.urlopen(req, timeout=180) as r, open(dst, "wb") as fh:
                    fh.write(r.read())
            except Exception as exc:                # noqa: BLE001 — try next
                logger.debug("music fetch failed %s: %s", item, str(exc)[:90])
                dst.unlink(missing_ok=True)
                continue
            if dst.stat().st_size < 200_000 or not _is_musical(dst):
                dst.unlink(missing_ok=True)
                continue
            logger.info("Music: + %s/%s", mood, dst.name)
            tracks.append(dst)
        have[mood] = sorted(tracks)
    return have


def _ledger() -> list[str]:
    try:
        return json.loads(LEDGER.read_text())
    except (OSError, json.JSONDecodeError):
        return []


def _remember(name: str, keep: int = 8) -> None:
    seen = [x for x in _ledger() if x != name]
    seen.insert(0, name)
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(seen[:keep], indent=1))
    except OSError:
        pass


def pick(mood: str) -> Optional[Path]:
    """A track for this mood that was not used in the last few videos.

    Rotation is explicit rather than random. Random choice over four tracks
    repeats the previous one a quarter of the time, which viewers of a daily
    channel notice long before they could name why.
    """
    mood = mood if mood in MOODS else DEFAULT_MOOD
    tracks = sorted((LIBRARY / mood).glob("*.mp3"))
    if not tracks:
        for other in MOODS:
            tracks = sorted((LIBRARY / other).glob("*.mp3"))
            if tracks:
                logger.info("Music: no %s tracks — falling back to %s", mood, other)
                break
    if not tracks:
        return None
    recent = _ledger()
    fresh = [t for t in tracks if t.name not in recent]
    chosen = (min(fresh, key=lambda p: p.name) if fresh
              else min(tracks, key=lambda p: recent.index(p.name)))
    _remember(chosen.name)
    return chosen


def mix(voice_wav: str, out_wav: str, *, mood: str = DEFAULT_MOOD,
        bed_lufs: float = -26.0, voice_lufs: float = -14.0,
        intro_s: float = 0.0) -> str:
    """Lay a ducked bed under the narration.

    The music is normalised to `bed_lufs` and then ducked FURTHER by the voice
    through sidechaincompress, so it recovers in the gaps between sentences and
    gets out of the way the instant anyone speaks. A static bed cannot do both:
    set quiet enough never to mask a consonant it is inaudible, set loud enough
    to be felt it fights the 1-4 kHz band speech needs.

    Returns the input untouched if there is no library, because a video with no
    score is fine and a video with a broken mix is not.
    """
    track = pick(mood)
    if track is None:
        logger.info("Music: library empty — shipping without a bed")
        return voice_wav

    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", voice_wav],
        capture_output=True, text=True).stdout.strip() or 0)
    if dur <= 0:
        return voice_wav

    # Loop the bed to cover the narration, fade both ends, then duck it.
    #
    # `sidechaincompress` takes the voice as its trigger. attack is short so
    # the duck lands before the first syllable is masked; release is long so
    # the bed does not pump up between words inside a sentence.
    # RELEASE is the parameter that decides whether a bed exists at all.
    #
    # At 650ms it was longer than the gaps it was supposed to fill — measured
    # sentence gaps here run 158-332ms — so the compressor never finished
    # recovering before the next sentence pushed it down again. The bed stayed
    # ducked for the whole video, sitting 32 dB under the speech at -47 dB,
    # which is inaudible on a phone. The result reads as two separate faults:
    # "there is no music" and "there is a void after every sentence". Both are
    # this one number.
    #
    # 200ms recovers inside the shortest real gap while still being slow enough
    # not to pump between words inside a sentence. The ratio is gentler too:
    # a hard 12:1 on a bed already normalised low is what drove it into the
    # floor rather than merely out of the way.
    chain = (
        f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{dur:.3f},"
        f"loudnorm=I={bed_lufs}:TP=-2:LRA=7,"
        f"afade=t=in:st=0:d=1.2,afade=t=out:st={max(0.0, dur - 1.8):.3f}:d=1.8[bed];"
        f"[0:a]asplit=2[v1][vkey];"
        f"[bed][vkey]sidechaincompress="
        f"threshold=0.03:ratio=4:attack=20:release=200:makeup=1:knee=6[duck];"
        f"[v1][duck]amix=inputs=2:duration=first:dropout_transition=0:"
        f"weights=1 1:normalize=0,"
        f"loudnorm=I={voice_lufs}:TP=-1.5:LRA=9,alimiter=limit=0.94[out]"
    )
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", voice_wav, "-i", str(track),
         "-filter_complex", chain, "-map", "[out]",
         "-ac", "1", "-ar", "48000", out_wav],
        capture_output=True, text=True)
    if r.returncode != 0 or not Path(out_wav).exists():
        logger.warning("Music mix failed (%s) — shipping the dry voice",
                       r.stderr[-200:].replace("\n", " "))
        return voice_wav
    logger.info("Music: %s/%s ducked under the voice at %.0f LUFS",
                mood, track.name, bed_lufs)
    return out_wav
