"""
Subprocess launcher for the CommonCreed video pipeline.

Unit 4: takes a ``pipeline_runs`` row, invokes ``scripts/smoke_e2e.py`` as a
subprocess with a freshly constructed environment (NOT inherited from the
sidecar process), parses the stdout for output paths + the COST REPORT block,
persists the results via ``sidecar.db``, then calls ``caption_gen.generate_captions``
to attach platform-aware captions to the row.

Failure isolation: ``run_pipeline_for_run`` NEVER raises out. Every failure
mode (subprocess non-zero exit, timeout, parse error, caption-gen exception)
maps to a DB row update + a result dict returned to the caller. Per R15,
per-video failure isolation is non-negotiable.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import os
import re
import signal
from pathlib import Path
from typing import Any, Optional

from . import caption_gen as caption_gen_module
from . import db as db_module
from .config import settings_manager

logger = logging.getLogger(__name__)

# Hard wall clock: 15 minutes per pipeline subprocess.
DEFAULT_TIMEOUT_SECONDS = 900

# --- stdout parsers ---------------------------------------------------------

# Matches lines like:
#   ✓  Assembled in 12.3s  (45.6 MB → output/video/foo_final.mp4)
# Unicode check mark is optional — we key on the "Assembled" keyword and the
# arrow. The path runs to end-of-line minus any trailing ')'.
_ASSEMBLED_RE = re.compile(
    r"Assembled in [\d.]+s\s*\([^)]*?→\s*([^)\s][^)]*?)\)"
)

# Matches lines like:
#   ✓  thumbnail: output/thumbnails/foo/thumbnail.png
_THUMBNAIL_RE = re.compile(r"thumbnail:\s*(\S+)")

# Matches lines like:
#   ✓  Voiceover saved: output/audio/foo.mp3
# (best-effort — this is a nice-to-have, not required)
_AUDIO_RE = re.compile(r"(?:Voiceover|Audio)[^:]*:\s*(\S+\.mp3)")

# COST REPORT parsers — the smoke_e2e.py format prints:
#   Claude Sonnet  <n> in / <n> out tokens   $0.0123
#   Claude Haiku   <n> in / <n> out tokens   $0.0001
#   ElevenLabs     <n> chars                 $0.3700
#   VEED Fabric    <f>s  (...)               $1.5700
_COST_SONNET_RE = re.compile(
    r"Claude Sonnet[^$]*\$([\d.]+)"
)
_COST_HAIKU_RE = re.compile(
    r"Claude Haiku[^$]*\$([\d.]+)"
)
_COST_EL_RE = re.compile(
    r"ElevenLabs[^$]*\$([\d.]+)"
)
_COST_VEED_RE = re.compile(
    r"VEED[^\n]*\$([\d.]+)\s*$", re.MULTILINE
)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _resolve_abs(path: str, cwd: str) -> str:
    """Turn a cwd-relative path into an absolute path. Idempotent on abs paths."""
    p = Path(path)
    if p.is_absolute():
        return str(p)
    return str((Path(cwd) / p).resolve())


def _parse_paths(stdout: str, cwd: str) -> dict:
    """Extract video/thumbnail/audio paths from the subprocess stdout."""
    out: dict = {"video_path": None, "thumbnail_path": None, "audio_path": None}
    m = _ASSEMBLED_RE.search(stdout)
    if m:
        out["video_path"] = _resolve_abs(m.group(1).strip(), cwd)
    m = _THUMBNAIL_RE.search(stdout)
    if m:
        out["thumbnail_path"] = _resolve_abs(m.group(1).strip(), cwd)
    m = _AUDIO_RE.search(stdout)
    if m:
        out["audio_path"] = _resolve_abs(m.group(1).strip(), cwd)
    return out


def _parse_costs(stdout: str) -> dict:
    """Extract per-provider dollar costs from the COST REPORT block."""
    def _grab(regex: re.Pattern) -> float:
        m = regex.search(stdout)
        if not m:
            return 0.0
        try:
            return float(m.group(1))
        except (TypeError, ValueError):
            return 0.0

    return {
        "cost_sonnet": _grab(_COST_SONNET_RE),
        "cost_haiku": _grab(_COST_HAIKU_RE),
        "cost_elevenlabs": _grab(_COST_EL_RE),
        "cost_veed": _grab(_COST_VEED_RE),
    }


def _build_subprocess_env(settings: Any, run_row: dict) -> dict:
    """Construct a fresh environment dict for the subprocess.

    We deliberately do NOT inherit from os.environ — the sidecar's own env
    vars (docker socket paths, pytest leaks, whatever) must not bleed into
    the pipeline. We pass only what ``smoke_e2e.py`` actually needs, sourced
    from the typed Settings object.
    """
    env: dict = {
        # Minimal POSIX baseline so python3 can start at all.
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        # Pipeline API keys sourced from typed settings.
        "ANTHROPIC_API_KEY": getattr(settings, "ANTHROPIC_API_KEY", "") or "",
        "ELEVENLABS_API_KEY": getattr(settings, "ELEVENLABS_API_KEY", "") or "",
        "VEED_API_KEY": getattr(settings, "VEED_API_KEY", "") or "",
        "FAL_API_KEY": getattr(settings, "FAL_API_KEY", "") or "",
        "PEXELS_API_KEY": getattr(settings, "PEXELS_API_KEY", "") or "",
        # Topic contract for smoke_e2e.py.
        "SMOKE_TOPIC": str(run_row.get("topic_title") or ""),
        "SMOKE_URL": str(run_row.get("topic_url") or ""),
    }
    return env


async def _run_subprocess(
    cmd: list[str],
    cwd: str,
    env: dict,
    timeout: float,
) -> tuple[int, str, str, bool]:
    """Run a subprocess asyncio, returning (rc, stdout, stderr, timed_out).

    On timeout we kill the process (and the whole process group to catch
    ffmpeg/Playwright children) and return ``timed_out=True`` with rc=-1.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        return (
            proc.returncode if proc.returncode is not None else -1,
            (stdout_b or b"").decode("utf-8", errors="replace"),
            (stderr_b or b"").decode("utf-8", errors="replace"),
            False,
        )
    except asyncio.TimeoutError:
        # Kill the whole process group.
        try:
            if proc.pid:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except Exception:
            pass
        return -1, "", "subprocess timed out", True


async def run_pipeline_for_run(
    pipeline_run_id: int,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Execute the video pipeline subprocess for a single pipeline_runs row.

    NEVER raises. Always returns a dict with at minimum ``{"ok": bool, "id": int}``.
    Callers rely on per-video failure isolation (R15).
    """
    started_at = _now_iso()
    try:
        settings = settings_manager.settings
        if settings is None:
            try:
                settings = settings_manager.load()
            except Exception as exc:
                logger.error(
                    "pipeline_runner: settings not loaded for run %s: %s",
                    pipeline_run_id,
                    exc,
                )
                return {
                    "ok": False,
                    "id": pipeline_run_id,
                    "error": f"settings not loaded: {exc}",
                }

        db_path = settings.SIDECAR_DB_PATH
        scripts_cwd = str(Path(settings.PIPELINE_SCRIPTS_PATH).resolve())

        # --- Load the pending row ----------------------------------------
        try:
            conn = db_module.connect(db_path)
        except Exception as exc:
            logger.error("pipeline_runner: db connect failed: %s", exc)
            return {"ok": False, "id": pipeline_run_id, "error": f"db: {exc}"}

        try:
            run_row = db_module.get_pipeline_run(conn, pipeline_run_id)
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if run_row is None:
            logger.error("pipeline_runner: run %s not found", pipeline_run_id)
            return {"ok": False, "id": pipeline_run_id, "error": "row not found"}

        env = _build_subprocess_env(settings, run_row)
        cmd = ["python3", "smoke_e2e.py"]

        # --- Subprocess invocation ---------------------------------------
        try:
            rc, stdout, stderr, timed_out = await _run_subprocess(
                cmd, cwd=scripts_cwd, env=env, timeout=timeout_seconds
            )
        except Exception as exc:
            logger.exception(
                "pipeline_runner: subprocess launch failed for run %s",
                pipeline_run_id,
            )
            _persist_failure(
                db_path,
                pipeline_run_id,
                status="failed_generation",
                error_log=f"subprocess launch failed: {exc}",
                started_at=started_at,
            )
            return {
                "ok": False,
                "id": pipeline_run_id,
                "error": f"subprocess launch: {exc}",
            }

        if timed_out:
            logger.error(
                "pipeline_runner: run %s timed out after %ss",
                pipeline_run_id,
                timeout_seconds,
            )
            _persist_failure(
                db_path,
                pipeline_run_id,
                status="failed_timeout",
                error_log=f"timeout after {timeout_seconds}s\n{stderr}",
                started_at=started_at,
            )
            return {
                "ok": False,
                "id": pipeline_run_id,
                "error": "timeout",
                "timed_out": True,
            }

        if rc != 0:
            logger.error(
                "pipeline_runner: run %s exited rc=%s stderr=%s",
                pipeline_run_id,
                rc,
                stderr[:500],
            )
            _persist_failure(
                db_path,
                pipeline_run_id,
                status="failed_generation",
                error_log=f"rc={rc}\n{stderr}",
                started_at=started_at,
            )
            return {
                "ok": False,
                "id": pipeline_run_id,
                "error": f"exit {rc}",
                "stderr": stderr,
            }

        # --- Parse stdout ------------------------------------------------
        paths = _parse_paths(stdout, scripts_cwd)
        costs = _parse_costs(stdout)

        if not paths["video_path"]:
            logger.error(
                "pipeline_runner: run %s succeeded but video_path not parsed",
                pipeline_run_id,
            )
            _persist_failure(
                db_path,
                pipeline_run_id,
                status="failed_generation",
                error_log=(
                    "subprocess exit 0 but stdout did not contain an "
                    "'Assembled in ... → <path>' line\nstdout tail:\n"
                    + stdout[-800:]
                ),
                started_at=started_at,
            )
            return {
                "ok": False,
                "id": pipeline_run_id,
                "error": "output parse failed",
            }

        finished_at = _now_iso()

        # --- Persist success ---------------------------------------------
        try:
            conn = db_module.connect(db_path)
            try:
                db_module.update_pipeline_run_generation_result(
                    conn,
                    pipeline_run_id,
                    status="generated",
                    video_path=paths["video_path"],
                    thumbnail_path=paths["thumbnail_path"],
                    audio_path=paths["audio_path"],
                    cost_sonnet=costs["cost_sonnet"],
                    cost_haiku=costs["cost_haiku"],
                    cost_elevenlabs=costs["cost_elevenlabs"],
                    cost_veed=costs["cost_veed"],
                    error_log=None,
                    started_at=started_at,
                    finished_at=finished_at,
                )
            finally:
                conn.close()
        except Exception as exc:
            logger.exception(
                "pipeline_runner: failed to persist success for run %s",
                pipeline_run_id,
            )
            return {
                "ok": False,
                "id": pipeline_run_id,
                "error": f"persist: {exc}",
            }

        # --- Caption gen (best-effort) -----------------------------------
        script_text = _extract_script_text(stdout)
        headline = str(run_row.get("topic_title") or "")
        topic_url = str(run_row.get("topic_url") or "") or None
        captions: dict
        try:
            captions = caption_gen_module.generate_captions(
                script_text=script_text,
                headline=headline,
                topic_url=topic_url,
                client=None,
            )
        except Exception as exc:  # defense in depth — caption_gen shouldn't raise
            logger.exception(
                "pipeline_runner: caption_gen raised for run %s: %s",
                pipeline_run_id,
                exc,
            )
            captions = {}

        try:
            conn = db_module.connect(db_path)
            try:
                db_module.set_captions(conn, pipeline_run_id, captions)
            finally:
                conn.close()
        except Exception as exc:
            logger.exception(
                "pipeline_runner: set_captions failed for run %s: %s",
                pipeline_run_id,
                exc,
            )
            # Still count the run as generated — captions are recoverable.

        return {
            "ok": True,
            "id": pipeline_run_id,
            "video_path": paths["video_path"],
            "thumbnail_path": paths["thumbnail_path"],
            "audio_path": paths["audio_path"],
            "costs": costs,
            "captions": captions,
        }

    except Exception as exc:  # outermost safety net — never raise out
        logger.exception(
            "pipeline_runner: unexpected failure for run %s: %s",
            pipeline_run_id,
            exc,
        )
        return {
            "ok": False,
            "id": pipeline_run_id,
            "error": f"unexpected: {exc}",
        }


def _extract_script_text(stdout: str) -> str:
    """Best-effort extraction of the generated script from stdout.

    The smoke_e2e.py script does not currently echo the full script to stdout,
    so in most cases this returns an empty string and caption_gen will fall
    back to building captions from the headline alone.
    """
    # Placeholder for future enhancement; today we pass the empty string and
    # rely on caption_gen's headline-driven fallback path.
    return ""


def _persist_failure(
    db_path: str,
    run_id: int,
    status: str,
    error_log: str,
    started_at: str,
) -> None:
    """Write a failure result to the pipeline_runs row. Swallows DB errors."""
    finished_at = _now_iso()
    try:
        conn = db_module.connect(db_path)
        try:
            db_module.update_pipeline_run_generation_result(
                conn,
                run_id,
                status=status,
                video_path=None,
                thumbnail_path=None,
                audio_path=None,
                cost_sonnet=0.0,
                cost_haiku=0.0,
                cost_elevenlabs=0.0,
                cost_veed=0.0,
                error_log=error_log,
                started_at=started_at,
                finished_at=finished_at,
            )
        finally:
            conn.close()
    except Exception as exc:
        logger.error(
            "pipeline_runner: failed to persist failure for run %s: %s",
            run_id,
            exc,
        )
