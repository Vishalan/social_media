"""
Health router — GET /health.

Each check is wrapped in a bulletproof try/except (see
`scripts/thumbnail_gen/step.py` for the pattern) so a single broken check
can never raise out of the handler. Returns 200 when all flags are true,
503 with the same body otherwise.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .. import __version__
from .. import db as db_module
from ..config import settings_manager


router = APIRouter()


def _safe(fn: Callable[[], bool]) -> bool:
    try:
        return bool(fn())
    except Exception:
        return False


def _check_pipeline_code_visible() -> bool:
    s = settings_manager.settings
    base = Path(s.PIPELINE_SCRIPTS_PATH) if s else Path("/app/scripts")
    return (base / "smoke_e2e.py").exists()


def _check_env_readable() -> bool:
    path = settings_manager.env_path
    p = Path(path)
    if not p.exists():
        return False
    try:
        p.read_text()
        return True
    except OSError:
        return False


def _check_db_writable() -> bool:
    s = settings_manager.settings
    if not s:
        return False
    return db_module.db_writable(s.SIDECAR_DB_PATH)


def _check_docker_socket_accessible() -> bool:
    s = settings_manager.settings
    sock = s.DOCKER_SOCKET_PATH if s else "/var/run/docker.sock"
    return os.path.exists(sock) and os.access(sock, os.R_OK)


# Public check table — tests monkeypatch these names on the module.
checks = {
    "pipeline_code_visible": _check_pipeline_code_visible,
    "env_readable": _check_env_readable,
    "db_writable": _check_db_writable,
    "docker_socket_accessible": _check_docker_socket_accessible,
}


@router.get("/health")
def health() -> JSONResponse:
    results = {name: _safe(fn) for name, fn in checks.items()}
    body = {
        "ok": all(results.values()),
        **results,
        "version": __version__,
    }
    status = 200 if body["ok"] else 503
    return JSONResponse(status_code=status, content=body)
