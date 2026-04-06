"""
Narrow Docker socket client — restart-only.

Why this exists: when settings change, some containers (Postiz) need to be
restarted to pick up new env vars. We deliberately do NOT shell out to the
docker CLI and we deliberately do NOT use the full docker-py SDK surface —
we want a tiny, auditable wrapper that:

1. Speaks raw HTTP-over-Unix-socket to the Docker Engine API. No extra deps.
2. Exposes ONLY ``restart_containers``. No exec, no inspect, no logs.
3. Hard-codes an allowlist of container names that explicitly EXCLUDES the
   sidecar's own container — restarting yourself from inside a request
   handler is a footgun (mid-flight requests get killed) and we just refuse.

Tests mock the entire socket layer; nothing here ever touches a real Docker
daemon during pytest runs.
"""
from __future__ import annotations

import http.client
import logging
import socket
from typing import Iterable, Optional


logger = logging.getLogger("sidecar.docker")


# The sidecar container's own name — never restartable from within itself.
SIDECAR_CONTAINER_NAME = "commoncreed_sidecar"

DEFAULT_ALLOWLIST = (
    "postiz",
    "commoncreed_postgres",
    "commoncreed_redis",
)


class _UnixHTTPConnection(http.client.HTTPConnection):
    """http.client connection that talks to a Unix domain socket."""

    def __init__(self, socket_path: str, timeout: float = 10.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:  # type: ignore[override]
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._socket_path)
        self.sock = sock


class DockerManager:
    """Restart-only Docker client constrained by an allowlist."""

    def __init__(
        self,
        socket_path: str = "/var/run/docker.sock",
        allowlist: Optional[Iterable[str]] = None,
    ) -> None:
        self.socket_path = socket_path
        self.allowlist = tuple(allowlist) if allowlist is not None else DEFAULT_ALLOWLIST
        # Belt-and-suspenders: even if a caller passed a custom allowlist, we
        # refuse to ever include the sidecar's own container.
        if SIDECAR_CONTAINER_NAME in self.allowlist:
            self.allowlist = tuple(
                n for n in self.allowlist if n != SIDECAR_CONTAINER_NAME
            )

    def is_allowed(self, name: str) -> bool:
        return name != SIDECAR_CONTAINER_NAME and name in self.allowlist

    def _open_connection(self) -> _UnixHTTPConnection:
        """Override-friendly hook so tests can patch the socket layer."""
        return _UnixHTTPConnection(self.socket_path)

    def _restart_one(self, name: str) -> None:
        conn = self._open_connection()
        try:
            conn.request("POST", f"/v1.41/containers/{name}/restart")
            resp = conn.getresponse()
            body = resp.read()
            if resp.status >= 400:
                raise RuntimeError(
                    f"docker restart {name} returned {resp.status}: {body[:200]!r}"
                )
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def restart_containers(self, names: list[str]) -> dict:
        """Restart each requested container that passes the allowlist check.

        Returns a dict with three lists:
            ``restarted`` — names that returned a 2xx from the Docker API
            ``rejected`` — names that the allowlist blocked
            ``errors``   — list of ``{"name": ..., "error": ...}`` for failures
        """
        restarted: list[str] = []
        rejected: list[str] = []
        errors: list[dict] = []
        for name in names:
            if not self.is_allowed(name):
                logger.warning("docker_manager: rejected restart for %r", name)
                rejected.append(name)
                continue
            try:
                self._restart_one(name)
                restarted.append(name)
                logger.info("docker_manager: restarted %r", name)
            except Exception as exc:
                logger.error("docker_manager: error restarting %r: %s", name, exc)
                errors.append({"name": name, "error": str(exc)})
        return {"restarted": restarted, "rejected": rejected, "errors": errors}
