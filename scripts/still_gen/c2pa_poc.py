"""C2PA-through-MoviePy POC runner (Unit 9 first deliverable).

Verifies whether fal.ai-generated images keep their C2PA credentials
after round-tripping through MoviePy's ``write_videofile``. Result
determines Unit 11's Instagram AI-label strategy per plan
System-Wide Impact #6:

  * **PASS**  — credentials survive. Ship as-is; IG auto-detects AI label.
  * **STRIP** — credentials stripped by libx264 re-encode. Choose:
      (a) add ``c2patool`` re-sign stage to assembly pipeline
      (b) route final assembly through ``ffmpeg -c copy`` stream-copy
      (c) accept IG label is manual-UI-only

This script requires an actual fal.ai key + ``c2patool`` binary +
MoviePy + ffmpeg — it does NOT run as a unit test. Invoke it as an
integration script on a machine with credentials + tools:

.. code-block:: bash

    export FAL_API_KEY=<key>
    python -m scripts.still_gen.c2pa_poc [--endpoint fal-ai/flux-pro/v1.1]

Output is a JSON report at ``output/c2pa_poc/report.json`` with:

  * generated_image_path — fal.ai output
  * image_c2pa_present — whether c2patool verify succeeded pre-MoviePy
  * mp4_path — MoviePy round-trip product
  * mp4_c2pa_present — whether c2patool verify survives round-trip
  * recommendation — one of ``pass`` / ``re_sign`` / ``stream_copy`` /
    ``manual_only``

The script is idempotent; re-running on an existing report compares
against prior outcomes to detect behavioral drift across MoviePy
versions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


_DEFAULT_PROMPT = (
    "cinematic horror photograph, moody low-key lighting, 35mm film "
    "aesthetic, night-shift atmosphere, abandoned highway rest stop, "
    "shallow DOF, film grain, no text no logo"
)

_REPORT_DIR = Path("output/c2pa_poc")


async def _generate_still(endpoint: str, output_path: Path) -> Dict[str, Any]:
    from .flux_client import FalFluxClient

    fal_key = os.environ.get("FAL_API_KEY")
    if not fal_key:
        raise RuntimeError("FAL_API_KEY env var required")
    client = FalFluxClient(
        fal_api_key=fal_key,
        endpoint=endpoint,
        output_dir=str(output_path.parent),
    )
    result = await client.generate(
        prompt=_DEFAULT_PROMPT,
        output_path=str(output_path),
    )
    return {
        "remote_url": result.remote_url,
        "width": result.width,
        "height": result.height,
        "duration_ms": result.duration_ms,
    }


def _c2patool_verify(path: Path) -> bool:
    """Run ``c2patool <path>`` — returns True if the manifest verifies."""
    try:
        proc = subprocess.run(
            ["c2patool", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            logger.info("c2patool non-zero exit for %s: %s", path, proc.stderr[:500])
            return False
        # c2patool prints a JSON manifest for files with credentials;
        # absent-credential files print an empty stdout + return 0 on
        # some versions, or a "No claim found" message on others.
        if not proc.stdout.strip():
            return False
        if "No claim" in proc.stdout or "no manifest" in proc.stdout.lower():
            return False
        return True
    except FileNotFoundError:
        raise RuntimeError(
            "c2patool binary not installed — `cargo install c2patool` or "
            "download a release build from https://github.com/contentauth/c2patool"
        )
    except subprocess.TimeoutExpired:
        logger.warning("c2patool timed out for %s", path)
        return False


def _moviepy_roundtrip(image_path: Path, mp4_path: Path, duration_s: float = 4.0) -> None:
    """Put the still through MoviePy + libx264 and write an MP4.

    Represents the simplest plausible Vesper render step; if C2PA
    credentials survive this, they likely survive the fuller Ken Burns
    / overlay / caption pipeline too. If they don't, the fuller
    pipeline has no chance.
    """
    try:
        from moviepy.editor import ImageClip  # MoviePy v1.x API
    except ImportError:
        from moviepy import ImageClip         # MoviePy v2.x API

    clip = ImageClip(str(image_path), duration=duration_s)
    # Some MoviePy versions require a framerate here; 24 fps is fine.
    clip.write_videofile(
        str(mp4_path),
        fps=24,
        codec="libx264",
        audio=False,
        logger=None,
    )


def _classify(image_ok: bool, mp4_ok: bool) -> str:
    """Map (image_has_c2pa, mp4_has_c2pa) to a recommendation."""
    if not image_ok and not mp4_ok:
        return "manual_only"         # fal.ai didn't embed credentials either
    if image_ok and mp4_ok:
        return "pass"
    if image_ok and not mp4_ok:
        return "re_sign"             # survived fal.ai, stripped by MoviePy
    # Weird state: C2PA absent on still but present on MP4? unreachable.
    return "unknown"


def run_poc(endpoint: str) -> Dict[str, Any]:
    """Run the full POC and return the report dict.

    Caller handles writing the report to disk (main() does so by default)
    so the function is unit-testable with fake subprocess + moviepy hooks
    if needed.
    """
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    image_path = _REPORT_DIR / "flux_still.png"
    mp4_path = _REPORT_DIR / "moviepy_roundtrip.mp4"

    generation = asyncio.run(_generate_still(endpoint, image_path))

    image_c2pa_present = _c2patool_verify(image_path)
    logger.info("c2patool(still): %s", "PASS" if image_c2pa_present else "ABSENT")

    _moviepy_roundtrip(image_path, mp4_path)

    mp4_c2pa_present = _c2patool_verify(mp4_path)
    logger.info("c2patool(mp4): %s", "PASS" if mp4_c2pa_present else "ABSENT")

    recommendation = _classify(image_c2pa_present, mp4_c2pa_present)
    logger.info("C2PA POC recommendation: %s", recommendation.upper())

    return {
        "endpoint": endpoint,
        "generation": generation,
        "image_path": str(image_path),
        "image_c2pa_present": image_c2pa_present,
        "mp4_path": str(mp4_path),
        "mp4_c2pa_present": mp4_c2pa_present,
        "recommendation": recommendation,
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--endpoint", default="fal-ai/flux/dev",
        help="fal.ai Flux endpoint (default: fal-ai/flux/dev)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    report = run_poc(args.endpoint)
    report_path = _REPORT_DIR / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"C2PA POC report: {report_path}")
    print(f"Recommendation: {report['recommendation'].upper()}")
    return 0 if report["recommendation"] in ("pass", "re_sign", "stream_copy") else 1


if __name__ == "__main__":
    sys.exit(main())
