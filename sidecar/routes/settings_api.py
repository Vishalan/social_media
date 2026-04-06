"""
Settings write API.

Atomic .env update strategy:
1. Parse the current .env into a dict (preserving order best-effort).
2. Validate each submitted (key, value) — non-empty, length-bounded.
3. Compute which keys are *changing* (different from the current parsed value).
4. For changed keys, decide which containers need restart by consulting a
   static map. The sidecar's own container is NEVER in that map — even if a
   "Sidecar" key changes, we just re-read at next access; restarting yourself
   from inside a request handler kills the response.
5. Write the new contents to ``<env>.new`` then ``os.replace()`` it over the
   real path. ``os.replace`` is atomic on POSIX.
6. Re-load settings_manager so subsequent reads see the new values.
7. Insert one row per changed key into the ``settings`` audit table.
8. Return ``{updated, restarted}`` as JSON.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .. import db as db_module
from ..auth import require_auth
from ..config import settings_manager
from ..docker_manager import DockerManager, SIDECAR_CONTAINER_NAME


logger = logging.getLogger("sidecar.settings_api")
router = APIRouter()

# Static map: which keys, when changed, force a container restart.
# Sidecar-internal keys are deliberately absent — re-read at point of use.
KEY_TO_CONTAINERS: dict[str, tuple[str, ...]] = {
    "POSTIZ_BASE_URL": ("postiz",),
    "POSTIZ_API_KEY":  ("postiz",),
}

# Subprocess-only keys: no restart, picked up by next pipeline run.
SUBPROCESS_KEYS = frozenset({
    "ELEVENLABS_API_KEY", "VEED_API_KEY", "FAL_API_KEY", "PEXELS_API_KEY",
})


# Module-level singleton so tests can monkeypatch the underlying mgr.
docker_manager = DockerManager()


MAX_VALUE_LEN = 4096


def _validate(key: str, value: str) -> None:
    if not isinstance(value, str) or len(value.strip()) == 0:
        raise HTTPException(status_code=400, detail=f"invalid empty value for {key}")
    if len(value) > MAX_VALUE_LEN:
        raise HTTPException(status_code=400, detail=f"value too long for {key}")
    if "\n" in value or "\r" in value:
        raise HTTPException(status_code=400, detail=f"value for {key} contains newline")


def _read_env(path: Path) -> dict:
    data: dict = {}
    if not path.exists():
        return data
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def _write_env_atomic(path: Path, data: dict) -> Path:
    tmp = path.with_suffix(path.suffix + ".new")
    body = "\n".join(f"{k}={v}" for k, v in data.items()) + "\n"
    tmp.write_text(body)
    os.replace(tmp, path)
    return tmp


def _affected_containers(changed_keys: Iterable[str]) -> list[str]:
    targets: list[str] = []
    for k in changed_keys:
        for c in KEY_TO_CONTAINERS.get(k, ()):
            if c == SIDECAR_CONTAINER_NAME:
                # Defensive: never restart self even if the map says to.
                continue
            if c not in targets:
                targets.append(c)
    return targets


@router.post("/settings/update")
async def settings_update(request: Request, _: bool = Depends(require_auth)):
    form = await request.form()
    submitted = {k: str(v) for k, v in form.items() if k != "csrf_token"}

    if not submitted:
        raise HTTPException(status_code=400, detail="no fields submitted")

    for k, v in submitted.items():
        _validate(k, v)

    s = settings_manager.settings
    if s is None:
        raise HTTPException(status_code=503, detail="settings not loaded")

    env_path = Path(settings_manager.env_path)
    current = _read_env(env_path)

    # Drop "***" placeholders so the user can leave masked fields untouched.
    changed: dict[str, str] = {}
    for k, v in submitted.items():
        if v == "***":
            continue
        if current.get(k) != v:
            changed[k] = v

    if not changed:
        return JSONResponse({"updated": [], "restarted": []})

    new_env = dict(current)
    new_env.update(changed)
    _write_env_atomic(env_path, new_env)

    # Reload sidecar in-process settings so subsequent requests see the change.
    try:
        settings_manager.reload()
    except Exception as exc:
        logger.error("settings reload after write failed: %s", exc)

    # Audit log
    try:
        conn = db_module.connect(s.SIDECAR_DB_PATH)
        try:
            with conn:
                for k in changed.keys():
                    conn.execute(
                        "INSERT OR REPLACE INTO settings (key, value, updated_at) "
                        "VALUES (?, ?, datetime('now'))",
                        (k, "***"),  # never store the secret in audit
                    )
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("settings audit write failed: %s", exc)

    targets = _affected_containers(changed.keys())
    restart_result = {"restarted": [], "rejected": [], "errors": []}
    if targets:
        try:
            restart_result = docker_manager.restart_containers(targets)
        except Exception as exc:
            logger.error("docker restart failed: %s", exc)
            restart_result = {
                "restarted": [], "rejected": [], "errors": [{"name": "*", "error": str(exc)}],
            }

    return JSONResponse({
        "updated": sorted(changed.keys()),
        "restarted": restart_result.get("restarted", []),
        "rejected": restart_result.get("rejected", []),
        "errors": restart_result.get("errors", []),
    })
