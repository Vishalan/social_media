"""The shorts pipeline orchestrator.

Each stage writes its artifacts into the run directory and can be re-run on its
own. State is files on disk, not objects in memory, so a crashed run resumes
from the last completed stage instead of regenerating a voiceover to fix a
caption.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Optional

from .config import ShortsConfig
from .sources import Source, load_source

logger = logging.getLogger(__name__)


class ShortsError(RuntimeError):
    """Raised when a stage fails irrecoverably."""


_SCRIPT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "hook": {"type": "string"},
        # A platform call-to-action, woven into the narration rather than
        # bolted on. Empty when the subject genuinely does not support one —
        # a forced "comment below" on a story with nothing to send costs more
        # trust than the engagement is worth.
        "cta": {"type": "string"},
        "cta_keyword": {"type": "string"},
        "script": {"type": "string"},
        "description": {"type": "string"},
        "visual_identity": {
            "type": "object",
            "properties": {
                "palette": {"type": "array", "items": {"type": "string"}},
                "typography": {"type": "string"},
                "motifs": {"type": "array", "items": {"type": "string"}},
                "rationale": {"type": "string"},
            },
            "required": ["palette", "typography", "motifs", "rationale"],
        },
        "broll_queries": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "hook", "script", "description",
                 "visual_identity", "broll_queries"],
}


def _script_system(cfg: ShortsConfig) -> str:
    return f"""You write vertical short-form scripts for an AI/tech channel fronted by
the owner on camera, AND you set the visual identity for the piece.

SCRIPT RULES
- The OPENING HOOK must land by 2.0 seconds. TikTok measures hook rate at 2s
  (2sVTR), Meta at 3s; a single cross-posted master must clear the tighter gate.
  Make the first sentence a claim with tension in it — a stake, a reversal, a
  number that should not be true. Never open by naming the topic ("Today we're
  looking at..."), never open with context.

- RE-HOOK ROUGHLY EVERY 10 SECONDS. Retention is not lost at the start, it
  leaks in the middle. Every third or fourth sentence should re-open a loop:
  a turn ("but here's the part they buried"), a question the next line answers,
  a concrete number, or a named person contradicting the last claim. Write at
  least THREE of these after the opening hook and space them out.

- Total spoken script: {cfg.target_words_min}-{cfg.target_words_max} words —
  about 60 seconds at a NORMAL speaking pace of ~2.7 words/sec. This is a hard
  ceiling, not a target to exceed: a previous script ran 207 words in 56s, which
  is 3.7 words/sec, and it sounded fast-forwarded. Fewer words said properly
  beats more words rushed. If the story does not fill the time, cut a point
  rather than speeding up.

- Leave room to BREATHE. Vary sentence length deliberately: a long sentence
  then a very short one. A three-word sentence after a long one is a beat of
  silence, and that is where a hook lands.

- Write for the ear. Short sentences. No markdown, no emoji, no stage
  directions.

RHYTHM — this is what makes narration land, and it is written IN, not added by
the voice later:
- Vary sentence length hard. A long sentence, then a three-word one. The short
  one after a long one IS the beat of silence, and that is where a hook lands.
- Use direct address. "You" and "your", not "users" and "accounts". The viewer
  is one person, not an audience.
- Ask a question the next line answers. That is what stops a scroll mid-video.
- Front-load the verb. "X just published the code" beats "The code was
  published by X".
- Never open a sentence with a subordinate clause. It buries the point past
  the moment the viewer decides to keep watching.

CALL TO ACTION
Write ONE call to action into the script, as narration, near the end — after
the payoff has landed, never before. It must fit the subject. Choose the form
the story actually supports:
- "comment <WORD> and I'll send you the link" — only if there is a real link,
  repo or file to send. Set 'cta_keyword' to that single word.
- "save this so you can check yours later" — only if the viewer would genuinely
  come back to it, e.g. a tool or a procedure.
- "follow for more" — the weakest; use only when nothing more specific fits.
- "share this with someone who <specific situation>" — name the situation.
Put the chosen line in 'cta', and include it verbatim as part of 'script'.
If the subject supports none of these honestly, set 'cta' to an empty string
and write no call to action at all.
- NEVER invent or round a figure the source does not state.
- 'script' is the full voiceover INCLUDING the hook as its first sentence.
- Use the length for substance: what it is, why it differs from what came
  before, concrete specifics, who is using it, limits or caveats, and what the
  viewer should take away. Not padding, not repetition.
- End on something concrete.

VISUAL IDENTITY
Derive the look from the SOURCE ITSELF, not from generic tech-video style. If
the story is about a specific company, product or repository, borrow its actual
visual language: brand colours, interface, typographic register, iconography,
the artifacts a reader of that source would recognise.
- palette: 3-5 hex colours from or evocative of the source's own identity.
  Do NOT default to cyan-on-black.
- typography: the register the source itself uses or implies.
- motifs: 3-5 CONCRETE visual artifacts from the source world that a graphic
  could be built from — an API response, a terminal stream, a counter, a
  latency trace, a chat bubble, a wafer die, a monospace log line. Name real
  artifacts, not adjectives.
- rationale: one sentence on why this identity belongs to THIS story.

broll_queries: 3-5 short stock-footage phrases for real-world cinematic shots.
No abstract AI cliches, no "code on screen" — we render that ourselves.

Reply with JSON only."""


class ShortsPipeline:
    """Runs one short end to end."""

    def __init__(self, cfg: ShortsConfig, *, intelligence: Any = None) -> None:
        self.cfg = cfg
        Path(cfg.work_dir).mkdir(parents=True, exist_ok=True)
        Path(cfg.design_dir).mkdir(parents=True, exist_ok=True)
        Path(cfg.broll_dir).mkdir(parents=True, exist_ok=True)
        if intelligence is None:
            from intelligence import make_intelligence_client
            intelligence = make_intelligence_client({
                "intelligence_backend": "claude_cli",
                "claude_cli_model": cfg.intelligence_model,
                "claude_cli_timeout_s": 420,
            })
        self.llm = intelligence

    # -- helpers ---------------------------------------------------------
    def _sh(self, *a: str) -> str:
        r = subprocess.run(a, capture_output=True, text=True)
        if r.returncode != 0:
            raise ShortsError(f"{' '.join(a[:4])} failed: {r.stderr[-800:]}")
        return r.stdout.strip()

    def _dur(self, p: str) -> float:
        return float(self._sh("ffprobe", "-v", "error", "-show_entries",
                              "format=duration", "-of", "csv=p=0", p))

    def _post(self, url: str, payload: dict, timeout: int = 1800) -> dict:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    def _save(self, name: str, obj: Any) -> str:
        p = self.cfg.path(name)
        Path(p).write_text(json.dumps(obj, indent=2))
        return p

    def _load(self, name: str) -> Any:
        return json.loads(Path(self.cfg.path(name)).read_text())

    def _done(self, name: str) -> bool:
        p = Path(self.cfg.path(name))
        return p.exists() and p.stat().st_size > 0

    # -- stage 1: script -------------------------------------------------
    async def write_script(self, source: Source, *, force: bool = False) -> dict:
        if self._done("script.json") and not force:
            logger.info("script.json exists — reusing")
            return self._load("script.json")

        # Persist the source so later stages and --resume runs can read it
        # without re-fetching (and without a publisher blocking the retry).
        Path(self.cfg.path("source.txt")).write_text(source.text)
        Path(self.cfg.path("source_meta.json")).write_text(json.dumps(
            {"kind": source.kind, "title": source.title, "url": source.url},
            indent=2))
        logger.info("Writing script from %s source %r", source.kind, source.title)
        resp = await self.llm.messages.create(
            model="claude-sonnet-4-5", max_tokens=3000,
            system=_script_system(self.cfg),
            messages=[{"role": "user",
                       "content": f"SOURCE KIND: {source.kind}\n\n{source.summary()}"}],
            output_config={"format": {"type": "json_schema",
                                      "schema": _SCRIPT_SCHEMA}},
        )
        data = json.loads(resp.content[0].text)
        data = await self._trim_to_length(data)
        wc = len(data["script"].split())
        # 2.7 w/s is the measured pace at the current voice settings; the old
        # 3.3 estimate is what made a 207-word script look like a 63s piece
        # when it was really 56s of rushed delivery.
        logger.info("Script: %d words (~%.1fs at 2.7 w/s) — %r",
                    wc, wc / 2.7, data["title"])
        if wc > self.cfg.target_words_max * 1.1:
            logger.warning(
                "Script is %d words, over the %d-word ceiling — narration will "
                "be rushed", wc, self.cfg.target_words_max)
        if wc < self.cfg.target_words_min * 0.85:
            logger.warning(
                "Script is %d words, well under the %d-word target — the piece "
                "will run short of 60s", wc, self.cfg.target_words_min)
        self._save("script.json", data)
        return data

    async def _trim_to_length(self, data: dict, *, attempts: int = 2) -> dict:
        """Cut an over-long script back to the word ceiling.

        Asking for a word range in the prompt is not enough — a run asked for
        150-165 and came back with 206. That matters more than it looks, because
        word count is the only lever that controls DURATION: the TTS speaks at a
        fixed rate, so a long script cannot be fixed downstream. Slowing it to a
        natural pace turned 206 words into a 74-second piece, which is no longer
        a short.

        So the ceiling is enforced by a second pass rather than requested. The
        trim is asked for as an EDIT — keep the hook, keep the re-hooks, drop a
        supporting point — because a plain "make it shorter" tends to compress
        every sentence and take the texture out with the length.
        """
        cfg = self.cfg
        for attempt in range(1, attempts + 1):
            wc = len(data["script"].split())
            if wc <= cfg.target_words_max:
                return data
            logger.info("Script is %d words, over the %d ceiling — trimming "
                        "(attempt %d/%d)", wc, cfg.target_words_max, attempt,
                        attempts)
            try:
                resp = await self.llm.messages.create(
                    model="claude-sonnet-4-5", max_tokens=2000,
                    # Structured output, like every other call here. A plain
                    # text request made the CLI exit 1 — the client is built
                    # around a schema and the free-text path is not exercised.
                    output_config={"format": {"type": "json_schema", "schema": {
                        "type": "object",
                        "properties": {"script": {"type": "string"}},
                        "required": ["script"],
                    }}},
                    system=(
                        "You tighten short-form voiceover scripts. Reply with "
                        "JSON only."),
                    messages=[{"role": "user", "content": (
                        f"This voiceover is {wc} words and must be at most "
                        f"{cfg.target_words_max} (ideally "
                        f"{cfg.target_words_min}-{cfg.target_words_max}).\n\n"
                        "Cut it by REMOVING a supporting point or a redundant "
                        "clause — not by compressing every sentence, which "
                        "would flatten the rhythm. Keep the opening hook "
                        "verbatim. Keep the mid-script turns that re-open a "
                        "loop. Keep every figure exactly as written. Keep the "
                        "short punchy sentences that create pauses.\n\n"
                        f"SCRIPT:\n{data['script']}")}],
                )
                trimmed = " ".join(
                    json.loads(resp.content[0].text)["script"].split())
            except Exception as exc:              # noqa: BLE001 — optional pass
                logger.warning("trim failed (%s) — keeping the long script",
                               str(exc)[:120])
                return data
            new_wc = len(trimmed.split())
            # Guard against a "trim" that returns something useless or longer.
            if new_wc < cfg.target_words_min * 0.7 or new_wc >= wc:
                logger.warning("trim returned %d words — rejecting it", new_wc)
                return data
            logger.info("Trimmed %d -> %d words", wc, new_wc)
            data = {**data, "script": trimmed}
        return data

    # -- stage 2: voice --------------------------------------------------
    @staticmethod
    def chunk_text(text: str, max_chars: int) -> list[str]:
        """Split at sentence boundaries under max_chars.

        Required, not optional: chatterbox/tts.py:249 hardcodes
        max_new_tokens=1000, which is ~40s of audio. A longer script sent in
        one call is silently cut mid-sentence.
        """
        text = " ".join(text.split())
        chunks, cur = [], ""
        for sent in re.split(r"(?<=[.!?])\s+", text):
            if not sent:
                continue
            if len(sent) > max_chars:
                for piece in re.split(r"(?<=,)\s+", sent):
                    while len(piece) > max_chars:
                        cut = piece.rfind(" ", 0, max_chars) or max_chars
                        chunks.append(piece[:cut].strip())
                        piece = piece[cut:].strip()
                    if piece:
                        if len(cur) + len(piece) + 1 <= max_chars:
                            cur = f"{cur} {piece}".strip()
                        else:
                            if cur:
                                chunks.append(cur)
                            cur = piece
                continue
            if len(cur) + len(sent) + 1 <= max_chars:
                cur = f"{cur} {sent}".strip()
            else:
                if cur:
                    chunks.append(cur)
                cur = sent
        if cur:
            chunks.append(cur)
        return chunks

    def generate_voice(self, script: str, *, force: bool = False) -> str:
        cfg = self.cfg
        master = cfg.path("vo_master.wav")
        if os.path.exists(master) and not force:
            logger.info("vo_master.wav exists — reusing")
            return master

        if cfg.rhythm_enabled:
            takes = self._plan_rhythm(script)
        else:
            takes = [(c, cfg.exaggeration, 0.0)
                     for c in self.chunk_text(script, cfg.tts_max_chars_per_chunk)]
        logger.info("TTS: %d chars in %d take(s)%s", len(script), len(takes),
                    " with rhythm" if cfg.rhythm_enabled else "")

        parts = []
        for i, (text_i, exaggeration, gap) in enumerate(takes):
            # A sentence can still exceed the ~40s token cap on its own, so the
            # chunker stays in the loop as a guard rather than being replaced.
            for j, piece in enumerate(
                    self.chunk_text(text_i, cfg.tts_max_chars_per_chunk)):
                name = f"{cfg.run_id}_c{i}_{j}"
                self._post(f"{cfg.chatterbox_endpoint}/tts", {
                    "text": piece, "reference_audio_path": cfg.voice_ref,
                    "exaggeration": exaggeration,
                    "cfg_weight": cfg.cfg_weight,
                    "output_filename": f"{name}.wav",
                })
                local = cfg.path(f"chunk{i}_{j}.wav")
                self._sh("docker", "cp",
                         f"commoncreed_chatterbox:/app/output/{name}.wav", local)
                d = self._dur(local)
                if d >= 39.9:
                    logger.warning("take %d.%d is %.2fs — at the ~40s cap", i, j, d)
                parts.append(local)
            if gap > 0.01:
                parts.append(self._silence(gap, cfg.path(f"gap{i}.wav")))

        listing = cfg.path("vo_concat.txt")
        Path(listing).write_text("".join(f"file '{p}'\n" for p in parts))
        raw = cfg.path("vo_raw.wav")
        self._sh("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                 "-i", listing, "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", raw)

        # Pace correction, then tone, then loudness — each stage measures what
        # the previous one produced.
        raw = self._conform_pace(raw, script)

        # Tone shaping runs BEFORE loudnorm, so the measurement sees the audio
        # that will actually ship. EQing after a normalisation pass changes the
        # loudness the pass just set.
        tone = self._voice_tone_chain()

        # Two-pass loudnorm with linear=true: one-pass applies time-varying
        # gain, which is exactly the uncontrolled compression to avoid on
        # vocoder output. Raw Chatterbox has measured above 0 dBTP on every run.
        p1 = subprocess.run(
            ["ffmpeg", "-nostats", "-i", raw, "-af",
             f"highpass=f={cfg.highpass_hz},{tone}loudnorm=I={cfg.lufs_target}:"
             f"TP={cfg.true_peak_db}:LRA=7:print_format=json", "-f", "null", "-"],
            capture_output=True, text=True)
        m = json.loads(p1.stderr[p1.stderr.rindex("{"):p1.stderr.rindex("}") + 1])
        logger.info("Loudness in: I=%s TP=%s", m["input_i"], m["input_tp"])
        self._sh("ffmpeg", "-v", "error", "-y", "-i", raw, "-af",
                 f"highpass=f={cfg.highpass_hz},{tone}loudnorm=I={cfg.lufs_target}:"
                 f"TP={cfg.true_peak_db}:LRA=7:measured_I={m['input_i']}:"
                 f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
                 f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
                 f"linear=true,alimiter=limit=0.94",
                 "-ac", "1", "-ar", "48000", master)
        self._sh("ffmpeg", "-v", "error", "-y", "-i", master,
                 "-ac", "1", "-ar", "16000", cfg.path("vo_16k.wav"))
        logger.info("Voice: %.2fs mastered to %.1f LUFS", self._dur(master), cfg.lufs_target)
        return master

    def _conform_pace(self, wav: str, text: str) -> str:
        """Time-stretch the narration to the target speaking pace.

        The delivery measured 3.70 words/sec, against 2.3-2.8 for conversational
        speech, and the owner heard it as fast-forwarded. Two levers were tried
        first and neither works:

        * FEWER WORDS does not slow anything down. The TTS speaks at whatever
          rate it speaks at, so a shorter script just yields a shorter video at
          the same rushed pace.
        * cfg_weight was assumed to control deliberateness. A sweep across its
          useful range moved the pace from 2.88 to 3.00 w/s — noise.

        atempo is the lever that actually lands a pace, and it preserves pitch.
        The stretch is computed from the MEASURED rate of this take rather than
        a constant, so it self-corrects if the voice settings change, and it is
        clamped: never faster than 1.0, never slower than the floor, because
        past roughly 0.85 consonants start to smear.
        """
        cfg = self.cfg
        words = len(text.split())
        dur = self._dur(wav)
        if not words or dur <= 0:
            return wav
        rate = words / dur
        factor = cfg.speech_rate_target / rate
        if factor >= 0.99:
            logger.info("Pace %.2f w/s already at or under target %.2f — no "
                        "stretch", rate, cfg.speech_rate_target)
            return wav
        clamped = max(cfg.speech_atempo_floor, factor)
        out = cfg.path("vo_paced.wav")
        self._sh("ffmpeg", "-v", "error", "-y", "-i", wav,
                 "-filter:a", f"atempo={clamped:.4f}", out)
        logger.info("Pace %.2f w/s -> target %.2f: atempo=%.3f%s (%.1fs -> %.1fs)",
                    rate, cfg.speech_rate_target, clamped,
                    " [clamped at floor]" if clamped > factor else "",
                    dur, self._dur(out))
        return out

    # Sentences that re-open a loop. A beat of silence BEFORE one of these is
    # what makes a turn land; without it the script reads as a flat list of
    # facts, which is what "boring" meant.
    _TURN_STARTS = (
        "but ", "and here", "here's", "now ", "so ", "except", "then ",
        "turns out", "the catch", "except ", "yet ", "still ",
    )

    def _plan_rhythm(self, script: str) -> list:
        """Split the script into sentences, each with its own energy and gap.

        Short-form delivery is not one performance at one pace — it is a hook
        that is SOLD, a body that MOVES, and a beat of silence before the turn.
        Synthesising the whole script in a single pass gives every sentence
        identical expression and identical spacing, which is the mechanical
        definition of monotone and is what the owner heard as boring.

        Returns [(text, exaggeration, gap_after_seconds), ...].
        """
        cfg = self.cfg
        sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+", script.strip()) if x.strip()]
        if not sentences:
            return []
        plan = []
        for i, sent in enumerate(sentences):
            first, last = i == 0, i == len(sentences) - 1
            nxt = sentences[i + 1].lower() if i + 1 < len(sentences) else ""
            is_turn_next = any(nxt.startswith(t) for t in self._TURN_STARTS)

            if first:
                ex, gap = cfg.exaggeration_hook, cfg.pause_after_hook_s
            elif last:
                ex, gap = cfg.exaggeration_payoff, 0.0
            elif any(sent.lower().startswith(t) for t in self._TURN_STARTS):
                ex, gap = cfg.exaggeration_turn, cfg.pause_between_s
            else:
                ex, gap = cfg.exaggeration, cfg.pause_between_s

            # The pause goes BEFORE the turn, so it is applied as the gap after
            # whatever precedes it.
            if is_turn_next:
                gap = max(gap, cfg.pause_before_turn_s)
            if i + 1 == len(sentences) - 1:
                gap = max(gap, cfg.pause_before_payoff_s)
            plan.append((sent, ex, gap))
        return plan

    def _silence(self, seconds: float, path: str) -> str:
        """A mono silence file at the TTS sample rate, for use between takes."""
        self._sh("ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                 "-i", f"anullsrc=r=24000:cl=mono", "-t", f"{seconds:.3f}",
                 "-c:a", "pcm_s16le", path)
        return path

    def _voice_tone_chain(self) -> str:
        """FFmpeg filters that give the voice body and take the nose out of it.

        Every value here was tuned against the MEASURED response of the chain on
        white noise, not by ear and not by assumption. That mattered, because
        the previous version was built on a wrong one: ffmpeg's `equalizer` is a
        PEAKING filter, always. The filter documented here as a "low shelf at
        110 Hz" was a narrow bell, so it never built any low-end foundation —
        which is exactly the "no bass, sounds nasal" the owner reported.

        The measured spectrum of the old master explains the complaint precisely:
        warmth (250-500) peaked at -18.5 dB, then a 4.6 dB SCOOP at 500-800 with
        a flat plateau above it, and bass sitting 5 dB below warmth. A scooped
        low-mid under a plateau is the textbook boxy-nasal profile, with no
        bottom to anchor it.

        Four moves, and their measured effect on band balance:

          bass= shelf     +5.8 dB   an actual shelf this time, not a bell
          bell @ 600      +1.4 dB   fills the scoop, restoring chest-to-throat
          bell @ 1200     notched   the honk itself, narrow so it does not
                                    re-open the scoop underneath it
          treble= shelf   +2.7 dB   air, so added weight does not read as dull

        The nasal notch is deliberately NARROW (Q 2.6). A wider one measured
        better on paper and took the 500-800 fill with it, which is the balance
        that makes a voice sound nasal in the first place.
        """
        cfg = self.cfg
        if not cfg.voice_eq_enabled:
            return ""
        return (
            f"bass=g={cfg.voice_sub_db}:f={cfg.voice_sub_hz}:w=0.45,"
            f"equalizer=f={cfg.voice_body_hz}:t=q:w=1.2:g={cfg.voice_body_db},"
            f"equalizer=f={cfg.voice_scoop_fill_hz}:t=q:w=1.6:"
            f"g={cfg.voice_scoop_fill_db},"
            f"equalizer=f={cfg.voice_nasal_hz}:t=q:w=2.2:g={cfg.voice_nasal_cut_db},"
            f"equalizer=f={cfg.voice_presence_hz}:t=q:w=1.4:"
            f"g={cfg.voice_presence_db},"
            f"treble=g={cfg.voice_air_db}:f={cfg.voice_air_hz}:w=0.55,"
            f"acompressor=threshold=-18dB:ratio={cfg.voice_comp_ratio}:"
            "attack=12:release=180:makeup=2,"
        )

    def _conform_pace(self, wav: str, text: str) -> str:
        """Time-stretch the narration to the target speaking pace.

        The delivery measured 3.70 words/sec, against 2.3-2.8 for conversational
        speech, and the owner heard it as fast-forwarded. Two levers were tried
        first and neither works:

        * FEWER WORDS does not slow anything down. The TTS speaks at whatever
          rate it speaks at, so a shorter script just yields a shorter video at
          the same rushed pace.
        * cfg_weight was assumed to control deliberateness. A sweep across its
          useful range moved the pace from 2.88 to 3.00 w/s — noise.

        atempo is the lever that actually lands a pace, and it preserves pitch.
        The stretch is computed from the MEASURED rate of this take rather than
        a constant, so it self-corrects if the voice settings change, and it is
        clamped: never faster than 1.0, never slower than the floor, because
        past roughly 0.85 consonants start to smear.
        """
        cfg = self.cfg
        words = len(text.split())
        dur = self._dur(wav)
        if not words or dur <= 0:
            return wav
        rate = words / dur
        factor = cfg.speech_rate_target / rate
        if factor >= 0.99:
            logger.info("Pace %.2f w/s already at or under target %.2f — no "
                        "stretch", rate, cfg.speech_rate_target)
            return wav
        clamped = max(cfg.speech_atempo_floor, factor)
        out = cfg.path("vo_paced.wav")
        self._sh("ffmpeg", "-v", "error", "-y", "-i", wav,
                 "-filter:a", f"atempo={clamped:.4f}", out)
        logger.info("Pace %.2f w/s -> target %.2f: atempo=%.3f%s (%.1fs -> %.1fs)",
                    rate, cfg.speech_rate_target, clamped,
                    " [clamped at floor]" if clamped > factor else "",
                    dur, self._dur(out))
        return out

    def transcribe_and_align(self, script: str, *, force: bool = False) -> dict:
        cfg = self.cfg
        if self._done("captions.json") and not force:
            logger.info("captions.json exists — reusing")
            return self._load("captions.json")

        self._sh("docker", "cp", cfg.path("vo_16k.wav"),
                 f"commoncreed_latentsync:/app/output/{cfg.run_id}_16k.wav")
        tr = self._post(f"{cfg.latentsync_endpoint}/transcribe", {
            "audio_path": f"/app/output/{cfg.run_id}_16k.wav",
            "model": cfg.whisper_model,
        })
        self._save("timings.json", {
            "duration": self._dur(cfg.path("vo_master.wav")),
            "words": tr["words"], "segments": tr["segments"]})

        # Captions come from the SCRIPT with ASR timings. Transcribing our own
        # narration gave "GPT-5.6 sold" and "John Krapidze" on screen.
        from captions import align_words, group_cues
        aligned = align_words(tr["words"], script)
        # Use the channel's caption style rather than group_cues' defaults —
        # the reference shorts run 2-4 words per cue and ours were running 3
        # words / 28 chars, which reads as a subtitle rather than a caption.
        from .branding import CAPTIONS
        cues = group_cues(aligned, per_cue=CAPTIONS.words_per_cue,
                          max_chars=CAPTIONS.max_chars)
        out = {"words": aligned, "cues": cues}
        self._save("captions.json", out)
        logger.info("Captions: %d cues from %d aligned words", len(cues), len(aligned))
        return out

    # -- stage 4: segment plan ------------------------------------------
    def plan_segments(self, *, force: bool = False) -> list[tuple[float, float]]:
        if self._done("segments.json") and not force:
            return [tuple(x) for x in self._load("segments.json")]
        cfg = self.cfg
        t = self._load("timings.json")
        words, dur = t["words"], t["duration"]
        out, start = [], 0.0
        for i, w in enumerate(words[:-1]):
            gap = words[i + 1]["start"] - w["end"]
            span = w["end"] - start
            ends = w["word"].rstrip().endswith((".", "!", "?"))
            if (span >= cfg.segment_min_s and (ends or gap > 0.18)) or span >= cfg.segment_max_s:
                out.append((start, w["end"]))
                start = w["end"]
        if dur - start > 1.0:
            out.append((start, dur))
        elif out:
            out[-1] = (out[-1][0], dur)
        self._save("segments.json", out)
        logger.info("Segments: %d spanning %.2fs", len(out), sum(e - s for s, e in out))
        return out
