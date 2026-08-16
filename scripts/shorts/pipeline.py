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
- The HOOK must land by 2.0 seconds. TikTok measures hook rate at 2s (2sVTR),
  Meta at 3s; a single cross-posted master must clear the tighter gate.
- Total spoken script: {cfg.target_words_min}-{cfg.target_words_max} words.
  At ~3.3 words/sec that is about 60 seconds. Do not write short.
- Write for the ear. Short sentences. No markdown, no emoji, no stage
  directions, no "link in bio".
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
        wc = len(data["script"].split())
        logger.info("Script: %d words (~%.1fs) — %r", wc, wc / 3.3, data["title"])
        if wc < self.cfg.target_words_min * 0.85:
            logger.warning(
                "Script is %d words, well under the %d-word target — the piece "
                "will run short of 60s", wc, self.cfg.target_words_min)
        self._save("script.json", data)
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

        chunks = self.chunk_text(script, cfg.tts_max_chars_per_chunk)
        logger.info("TTS: %d chars in %d chunk(s)", len(script), len(chunks))
        parts = []
        for i, c in enumerate(chunks):
            self._post(f"{cfg.chatterbox_endpoint}/tts", {
                "text": c, "reference_audio_path": cfg.voice_ref,
                "exaggeration": cfg.exaggeration,
                "cfg_weight": cfg.cfg_weight,
                "output_filename": f"{cfg.run_id}_c{i}.wav",
            })
            local = cfg.path(f"chunk{i}.wav")
            self._sh("docker", "cp",
                     f"commoncreed_chatterbox:/app/output/{cfg.run_id}_c{i}.wav", local)
            d = self._dur(local)
            if d >= 39.9:
                logger.warning("chunk%d is %.2fs — at the ~40s cap, split further", i, d)
            parts.append(local)

        listing = cfg.path("vo_concat.txt")
        Path(listing).write_text("".join(f"file '{p}'\n" for p in parts))
        raw = cfg.path("vo_raw.wav")
        self._sh("ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                 "-i", listing, "-c:a", "pcm_s16le", "-ar", "24000", "-ac", "1", raw)

        # Two-pass loudnorm with linear=true: one-pass applies time-varying
        # gain, which is exactly the uncontrolled compression to avoid on
        # vocoder output. Raw Chatterbox has measured above 0 dBTP on every run.
        p1 = subprocess.run(
            ["ffmpeg", "-nostats", "-i", raw, "-af",
             f"highpass=f={cfg.highpass_hz},loudnorm=I={cfg.lufs_target}:"
             f"TP={cfg.true_peak_db}:LRA=7:print_format=json", "-f", "null", "-"],
            capture_output=True, text=True)
        m = json.loads(p1.stderr[p1.stderr.rindex("{"):p1.stderr.rindex("}") + 1])
        logger.info("Loudness in: I=%s TP=%s", m["input_i"], m["input_tp"])
        self._sh("ffmpeg", "-v", "error", "-y", "-i", raw, "-af",
                 f"highpass=f={cfg.highpass_hz},loudnorm=I={cfg.lufs_target}:"
                 f"TP={cfg.true_peak_db}:LRA=7:measured_I={m['input_i']}:"
                 f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
                 f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
                 f"linear=true,alimiter=limit=0.94",
                 "-ac", "1", "-ar", "48000", master)
        self._sh("ffmpeg", "-v", "error", "-y", "-i", master,
                 "-ac", "1", "-ar", "16000", cfg.path("vo_16k.wav"))
        logger.info("Voice: %.2fs mastered to %.1f LUFS", self._dur(master), cfg.lufs_target)
        return master

    # -- stage 3: timings + captions ------------------------------------
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
        cues = group_cues(aligned)
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
