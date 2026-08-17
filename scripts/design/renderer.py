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
from typing import Any, Optional, Sequence

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
- Hero / headline: "{headline}"{support_line}{context_line}
- Graphic kind:    {kind}

Render ONLY the lines given above. If a support or context line is absent from
this list it does not exist — do not invent one, and never render a placeholder
like "(none)" or "N/A" as visible copy.

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

SCALE — this is the most common way these graphics fail:
{scale_guidance}

MOTION MUST LAST THE WHOLE CLIP. The build may not finish before {build_min:.1f}s
of the {duration:.1f}s, and after it lands something must still be moving — a
counter settling, a cursor blinking, a slow scale, a line drawing in. Measured
failures on shipped clips: a 2.6s stats card whose last motion was at 0.52s and a
2.6s headline whose last motion was at 0.72s, so 80% and 72% of their screen time
was a STILL IMAGE. A frozen frame in a short reads as a stall, not as emphasis.

RESERVED ZONE: {reserved_zone}
Nothing important may be placed there — the presenter is composited into it.

FORMAT:
- {width}x{height} vertical, {fps}fps, exactly {duration:.1f}s.
- Transparent background is NOT wanted; render on the solid background colour.
{safe_area}

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
        reviewer: Optional[Any] = None,
        max_attempts: int = 2,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.work_dir = Path(work_dir)
        self.width, self.height, self.fps = width, height, fps
        self.style = {**DEFAULT_STYLE, **(style or {})}
        self.model = model
        self.timeout_s = timeout_s
        self.env = env
        # A vision pass that looks at the rendered frames. HyperFrames' own
        # `check` audits runtime errors, layout boxes and contrast, and still
        # passed a card whose hero numeral overlapped its own support line and
        # a terminal whose block cursor sat on the first letter of the word.
        # Those are only visible by looking.
        self.reviewer = reviewer
        self.max_attempts = max(1, max_attempts)

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
        """Render one brief, reviewing the result and retrying once if broken."""
        notes = ""
        last_path = ""
        for attempt in range(1, self.max_attempts + 1):
            last_path = await self._render_once(brief, extra_notes=notes)
            if self.reviewer is None:
                return last_path
            verdict = await asyncio.to_thread(
                self.reviewer, video=last_path, brief=brief.to_dict(),
                work_dir=str(self.work_dir))
            if verdict.get("ok", True):
                return last_path
            problems = verdict.get("problems") or [verdict.get("worst", "")]
            if attempt >= self.max_attempts:
                logger.warning(
                    "Design %r still flawed after %d attempts, shipping it: %s",
                    brief.slug, attempt, verdict.get("worst", ""))
                return last_path
            # Feed the specific defect back rather than asking for a vague
            # improvement — "make it better" reliably produces a different
            # arrangement with the same collision.
            notes = ("A previous attempt was REJECTED on visual review. Fix "
                     "exactly these and change nothing else that already "
                     "works:\n" + "\n".join(f"- {p}" for p in problems))
            logger.info("Re-rendering %r (attempt %d): %s",
                        brief.slug, attempt + 1, verdict.get("worst", ""))
        return last_path

    async def _render_once(self, brief: DesignBrief, *,
                           extra_notes: str = "") -> str:
        out = (self.output_dir / f"{brief.slug}.mp4").resolve()
        # Never shorter than the brief needs to be readable — see
        # DesignBrief.effective_duration_s().
        duration = brief.effective_duration_s()
        # A PANEL render (roughly square) is composited into the top half of the
        # frame, so platform UI never reaches it and it should be filled edge to
        # edge. A FULL-FRAME render does get clipped top and bottom. Applying the
        # full-frame safe area to a panel was squeezing content into 70% of an
        # already half-height canvas: shipped clips had content spanning 26-29%
        # of the panel with ink on 2-5% of pixels, which is unreadable at phone
        # size and is the reason they did not hold attention.
        is_panel = self.height < self.width * 1.3
        if is_panel:
            safe_area = (
                "- You own the WHOLE canvas. It is composited into the top half "
                "of the frame, so no platform UI overlaps it and there is no "
                "safe-area inset to respect.\n"
                "- FILL IT: content must span at least 85% of the canvas height "
                "and 85% of its width. Margins no larger than 6% a side. Empty "
                "background should be the minority of the frame.")
            hero_px = int(self.height * 0.30)
            solo_px = int(self.height * 0.42)
            support_px = int(self.height * 0.062)
            floor_px = int(self.height * 0.040)
            scale_guidance = (
                f"This {self.width}x{self.height} panel is viewed at about 6cm "
                f"tall on a phone. Type that looks generous in a desktop preview "
                f"is illegible there.\n"
                f"- Hero text: at least {hero_px}px. A hero that is a single "
                f"figure or one word (a number, a multiple, a price) should be "
                f"{solo_px}px or larger and dominate the frame.\n"
                f"- Support and context: at least {support_px}px.\n"
                f"- NOTHING below {floor_px}px, including labels inside diagrams, "
                f"code lines, chart ticks and step captions. If a diagram's rows "
                f"do not fit at {floor_px}px, use fewer rows — four legible steps "
                f"beat seven unreadable ones.")
        else:
            safe_area = (
                "- Keep all content inside the middle 70% vertically. Platform "
                "UI clips roughly the top 8% and the bottom 20%.")
            scale_guidance = (
                f"Hero text at least {int(self.height * 0.09)}px; nothing below "
                f"{int(self.height * 0.022)}px.")

        prompt = _PROMPT.format(
            duration=duration,
            safe_area=safe_area,
            scale_guidance=scale_guidance,
            build_min=max(0.6, duration * 0.7),
            headline=brief.headline,
            support_line=(f'\n- Support label:   "{brief.support}"'
                          if brief.support else ""),
            context_line=(f'\n- Context line:    "{brief.context}"'
                          if brief.context else ""),
            kind=brief.kind,
            rationale=brief.rationale or "(not stated)",
            motion=brief.motion or "arrive with weight and settle; no bounce",
            width=self.width, height=self.height, fps=self.fps,
            output_path=out,
            **self.style,
        )
        if extra_notes:
            prompt += "\n\nCORRECTIONS REQUIRED\n" + extra_notes

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
            # Same as the intelligence adapter: the CLI reports auth and
            # config failures on stdout, so stderr alone is often empty.
            err = (stderr or b"").decode("utf-8", "replace").strip()
            out = (stdout or b"").decode("utf-8", "replace").strip()
            detail = " | ".join(x for x in (err[-500:], out[-500:]) if x) or "(no output)"
            raise RenderError(f"claude -p exited {proc.returncode}: {detail}")

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
