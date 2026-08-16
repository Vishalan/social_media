"""Stage 2 — turn a DesignBrief into a rendered MP4.

Hands the brief to the Claude Code CLI with the HyperFrames skills loaded. The
agent authors an HTML composition, runs ``hyperframes lint`` and
``hyperframes check`` (which audits runtime errors, layout, and WCAG contrast),
fixes whatever it finds, then renders locally through headless Chrome.

Requirements on the rendering host: Node >= 22, Chrome, FFmpeg, the ``claude``
CLI, the ``hyperframes`` plugin, and a non-interactive credential
(CLAUDE_CODE_OAUTH_TOKEN). Rendering never touches HeyGen's cloud, so there is
no per-clip charge.

Measured 2026-08-16 on the Ubuntu server: 53 turns, 573s for one 3s clip at
1080x1920.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional, Sequence

from .brief import DesignBrief

logger = logging.getLogger(__name__)


class RenderError(RuntimeError):
    """Raised when a design clip cannot be produced."""


# Palette for the owner's personal channel. Deliberately NOT the CommonCreed
# navy — the two channels share no brand, and reusing the palette would blur
# them at thumbnail scale.
DEFAULT_STYLE = {
    "background": "#0A0C10",
    "accent": "#22D3EE",
    "muted": "#A8B8C5",
    "register": "premium tech-editorial, not generic corporate",
    "palette": "",
    "typography": "clean geometric sans",
    "motifs": "",
    "identity_rationale": "",
    "reserved_zone": "none",
}


_PROMPT = """Build ONE HyperFrames composition and render it to MP4. Use the hyperframes
skills (hyperframes-core, hyperframes-animation, motion-graphics, hyperframes-cli).

Deliverable: a {duration:.1f} second B-ROLL clip for a vertical short.

CONTENT (use these strings exactly; do not invent or alter figures):
- Hero / headline: "{headline}"
- Support label:   "{support}"
- Context line:    "{context}"
- Graphic kind:    {kind}

WHY THIS EXISTS: {rationale}

MOTION DIRECTION: {motion}
Execute that one idea precisely. At most two moving elements at a time. If the
catalog already has a primitive for it, reuse that vocabulary rather than
inventing motion; if nothing fits, hand-author and say why.

VISUAL IDENTITY — borrow from the SOURCE, do not default to house style:
- Palette: {palette}
  (fallback if that is empty: background {background}, accent {accent}, secondary {muted})
- Typography: {typography}
- Motifs to build from: {motifs}
- Why this identity belongs to this story: {identity_rationale}

Use the motifs LITERALLY where you can. If the motif is "a terminal streaming an
API response token by token", build an actual terminal with actual streaming
tokens — not an abstract glow that gestures at one. A graphic that could belong
to any tech story is a failure; this must look like it came from this source.

Register: {register}. The hero must read at a glance on a phone; support and
context are secondary and must never compete with it.

RESERVED ZONE: {reserved_zone}
Nothing important may be placed there — the presenter is composited into it.

FORMAT:
- {width}x{height} vertical, {fps}fps, exactly {duration:.1f}s.
- Transparent background is NOT wanted; render on the solid background colour.
- Keep all content inside the middle 70% vertically. Platform UI clips roughly
  the top 8% and the bottom 20%.

PROCESS:
1. `npx hyperframes init` the project.
2. Search the catalog for an existing primitive before hand-authoring motion.
3. Author the composition.
4. `npx hyperframes lint`, then `npx hyperframes check`. Fix every finding.
5. Render exactly to this path:
   npx hyperframes render --quality high --output {output_path}
6. Verify with ffprobe that the file exists, is non-empty, and is
   {width}x{height} at about {duration:.1f}s.

This is an AUTOMATED run. Do NOT open a preview and do NOT wait for human
approval — render directly. Report the final path and the ffprobe output.
"""


class HyperFramesRenderer:
    """Renders design briefs to MP4 via the Claude Code CLI + HyperFrames."""

    def __init__(
        self,
        *,
        output_dir: str = "output/design",
        work_dir: str = "output/design/_work",
        width: int = 1080,
        height: int = 1920,
        fps: int = 25,
        style: Optional[dict] = None,
        binary: str = "claude",
        model: str = "sonnet",
        timeout_s: int = 1800,
        env: Optional[dict] = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.work_dir = Path(work_dir)
        self.width, self.height, self.fps = width, height, fps
        self.style = {**DEFAULT_STYLE, **(style or {})}
        self.model = model
        self.timeout_s = timeout_s
        self.env = env

        resolved = shutil.which(binary)
        if resolved is None:
            raise RenderError(
                f"claude CLI not found as {binary!r}. The design stage needs it "
                f"plus Node >= 22, Chrome and FFmpeg on the rendering host."
            )
        self.binary = resolved
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    async def render(self, brief: DesignBrief) -> str:
        """Render one brief. Returns the output path."""
        out = (self.output_dir / f"{brief.slug}.mp4").resolve()
        # Never shorter than the brief needs to be readable — see
        # DesignBrief.effective_duration_s().
        duration = brief.effective_duration_s()
        prompt = _PROMPT.format(
            duration=duration,
            headline=brief.headline,
            support=brief.support or "(none)",
            context=brief.context or "(none)",
            kind=brief.kind,
            rationale=brief.rationale or "(not stated)",
            motion=brief.motion or "arrive with weight and settle; no bounce",
            width=self.width, height=self.height, fps=self.fps,
            output_path=out,
            **self.style,
        )

        proj = self.work_dir / brief.slug
        proj.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.binary, "-p", prompt,
            # Tools are required here — unlike the text-only intelligence calls,
            # this agent must write files and run the CLI.
            "--allowedTools", "Read,Write,Edit,Bash,Glob,Grep,Skill",
            "--permission-mode", "acceptEdits",
            "--model", self.model,
            "--output-format", "json",
        ]

        logger.info("Designing %r (%.1fs, %s) — this takes ~10 min",
                    brief.slug, duration, brief.kind)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(proj),
                env=self.env or dict(os.environ),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self.timeout_s
            )
        except asyncio.TimeoutError:
            raise RenderError(f"design of {brief.slug!r} exceeded {self.timeout_s}s")

        if proc.returncode != 0:
            tail = (stderr or b"").decode("utf-8", "replace")[-600:]
            raise RenderError(f"claude -p exited {proc.returncode}: {tail}")

        # The agent reports success in prose; the file on disk is the contract.
        if not out.exists() or out.stat().st_size == 0:
            summary = _summarise(stdout)
            raise RenderError(
                f"design of {brief.slug!r} produced no file at {out}. Agent said: {summary}"
            )

        logger.info("Designed %s (%d KB)", out.name, out.stat().st_size // 1024)
        return str(out)

    async def render_all(
        self, briefs: Sequence[DesignBrief], *, concurrency: int = 2
    ) -> list[dict]:
        """Render briefs concurrently.

        Each clip is ~10 minutes and the work is independent, so running them
        serially wastes most of the wall clock. Concurrency is capped because
        every agent drives its own headless Chrome.

        A failed clip yields ``path: None`` rather than sinking the batch — one
        bad graphic should not cost the whole video.
        """
        sem = asyncio.Semaphore(max(1, concurrency))

        async def one(b: DesignBrief) -> dict:
            async with sem:
                try:
                    path = await self.render(b)
                    return {**b.to_dict(), "path": path, "error": None}
                except RenderError as exc:
                    logger.error("Design failed for %r: %s", b.slug, exc)
                    return {**b.to_dict(), "path": None, "error": str(exc)}

        results = await asyncio.gather(*(one(b) for b in briefs))
        ok = sum(1 for r in results if r["path"])
        logger.info("Design stage: %d/%d clips rendered", ok, len(results))
        return list(results)


def _summarise(stdout: bytes) -> str:
    try:
        d = json.loads((stdout or b"").decode("utf-8", "replace"))
        return str(d.get("result", ""))[-400:]
    except Exception:
        return (stdout or b"").decode("utf-8", "replace")[-400:]
