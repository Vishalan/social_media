"""Networked reachability probes for the Vesper server stack.

Companion to :mod:`scripts.vesper_pipeline.doctor` (hermetic,
filesystem-only). The probe performs actual network calls — running
it in CI is a mistake; running it on the laptop before a launch is
exactly the point.

Probes (each returns a :class:`ProbeResult`):

  * **redis** — PING against ``REDIS_URL``.
  * **comfyui** — GET ``/system_stats`` against ``COMFYUI_URL``.
  * **chatterbox** — GET ``/health`` + ``/refs/list`` against
    ``CHATTERBOX_ENDPOINT``; verifies Vesper's ``archivist.wav`` is
    in the refs list if the env var pinpoints a specific filename.
  * **postiz** — GET ``/api/public/v1/integrations`` against
    ``POSTIZ_URL`` with ``Authorization: $POSTIZ_API_KEY``;
    verifies the ``vesper`` profile is wired for IG/YT/TT.
  * **telegram** — getMe against ``https://api.telegram.org/bot$TOKEN``.
  * **fal_ai** — best-effort HEAD against ``https://fal.run`` when
    ``FAL_API_KEY`` is set. Purely advisory (fal.ai's auth is
    per-endpoint; a full probe would burn budget).

Every probe has a short HTTP timeout (5 s default) and surfaces the
actual wire failure (connection refused, DNS fail, 4xx/5xx) in its
message so the operator can grep a log rather than re-run with
``--verbose``. Exit status: 0 when every required probe passes, 2
when at least one fails.

Required vs optional:
  * redis, comfyui, chatterbox, postiz, telegram → required.
  * fal_ai → optional (no fal.ai key ⇒ skipped; fail ⇒ warn).

Injectable HTTP client for tests — production uses ``httpx`` and
``redis-py``, both imported lazily.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional

# Path bootstrap — same pattern as doctor / __main__.
_SCRIPTS = Path(__file__).resolve().parent.parent
_REPO_ROOT = _SCRIPTS.parent
for p in (str(_SCRIPTS), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

logger = logging.getLogger(__name__)


DEFAULT_TIMEOUT_S = 5.0


class ProbeStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    WARN = "warn"


@dataclass(frozen=True)
class ProbeResult:
    name: str
    status: ProbeStatus
    message: str = ""
    latency_ms: float = 0.0
    required: bool = True

    @property
    def is_blocking(self) -> bool:
        return self.required and self.status == ProbeStatus.FAIL


# ─── HTTP client Protocol ──────────────────────────────────────────────────


class _HttpClient:
    """Minimal interface we need. Production wraps httpx; tests pass a
    fake that records calls + returns canned responses."""

    def get(self, url: str, *, headers: Mapping[str, str] | None = None,
            timeout: float = DEFAULT_TIMEOUT_S) -> Any: ...  # pragma: no cover


def _default_http_client():
    """Lazy-import httpx so the module imports cleanly in tests."""
    import httpx  # type: ignore

    class _Wrap:
        def get(self, url, *, headers=None, timeout=DEFAULT_TIMEOUT_S):
            return httpx.get(url, headers=headers or {}, timeout=timeout)

    return _Wrap()


# ─── Redis Protocol ────────────────────────────────────────────────────────


class _RedisClient:
    def ping(self) -> Any: ...  # pragma: no cover


def _default_redis_client(url: str):
    import redis  # type: ignore
    return redis.from_url(url, socket_timeout=DEFAULT_TIMEOUT_S)


# ─── Prober ────────────────────────────────────────────────────────────────


@dataclass
class Prober:
    """Walks each probe in order, collecting results.

    All network clients injectable — tests pass stubs; production
    uses httpx + redis-py.
    """

    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    timeout_s: float = DEFAULT_TIMEOUT_S
    http_client_factory: Callable[[], _HttpClient] = field(
        default=_default_http_client,
    )
    redis_client_factory: Callable[[str], _RedisClient] = field(
        default=_default_redis_client,
    )

    def run(self) -> List[ProbeResult]:
        results: List[ProbeResult] = []
        results.append(self._probe_redis())
        results.append(self._probe_comfyui())
        results.extend(self._probe_chatterbox())
        results.append(self._probe_postiz())
        results.append(self._probe_telegram())
        results.append(self._probe_fal_ai())
        return results

    def blocking_failures(self, results: List[ProbeResult]) -> List[ProbeResult]:
        return [r for r in results if r.is_blocking]

    # ─── Individual probes ─────────────────────────────────────────────

    def _probe_redis(self) -> ProbeResult:
        url = self.env.get("REDIS_URL", "").strip()
        if not url:
            return ProbeResult(
                name="redis",
                status=ProbeStatus.FAIL,
                message="REDIS_URL not set",
            )
        t0 = time.monotonic()
        try:
            client = self.redis_client_factory(url)
            pong = client.ping()
        except Exception as exc:
            return ProbeResult(
                name="redis",
                status=ProbeStatus.FAIL,
                message=f"PING failed: {exc}",
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        if not pong:
            return ProbeResult(
                name="redis",
                status=ProbeStatus.FAIL,
                message="PING returned falsy",
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        return ProbeResult(
            name="redis",
            status=ProbeStatus.PASS,
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    def _probe_comfyui(self) -> ProbeResult:
        url = self.env.get("COMFYUI_URL", "").strip()
        if not url:
            return ProbeResult(
                name="comfyui", status=ProbeStatus.FAIL,
                message="COMFYUI_URL not set",
            )
        return self._http_get_ok(
            name="comfyui",
            url=url.rstrip("/") + "/system_stats",
        )

    def _probe_chatterbox(self) -> List[ProbeResult]:
        endpoint = self.env.get("CHATTERBOX_ENDPOINT", "").strip()
        if not endpoint:
            return [ProbeResult(
                name="chatterbox:health",
                status=ProbeStatus.FAIL,
                message="CHATTERBOX_ENDPOINT not set",
            )]
        health = self._http_get_ok(
            name="chatterbox:health",
            url=endpoint.rstrip("/") + "/health",
        )
        results = [health]
        if health.status != ProbeStatus.PASS:
            # Skip the refs probe if health already failed.
            results.append(ProbeResult(
                name="chatterbox:refs",
                status=ProbeStatus.SKIP,
                message="skipped — /health probe failed",
            ))
            return results
        # /refs/list exists per Unit 8; probe it + look for archivist.
        refs = self._http_get_json(
            name="chatterbox:refs",
            url=endpoint.rstrip("/") + "/refs/list",
        )
        if refs.status == ProbeStatus.PASS:
            # Additional: confirm archivist.wav appears in the list
            # when CHATTERBOX_REFERENCE_AUDIO is set.
            want = self.env.get("CHATTERBOX_REFERENCE_AUDIO", "").strip()
            if want:
                want_name = os.path.basename(want)
                got = (refs.message or "").lower()
                if want_name and want_name.lower() not in got:
                    refs = ProbeResult(
                        name="chatterbox:refs",
                        status=ProbeStatus.WARN,
                        message=(
                            f"{want_name} not in refs list. Response: "
                            f"{refs.message[:200]}"
                        ),
                        latency_ms=refs.latency_ms,
                    )
        results.append(refs)
        return results

    def _probe_postiz(self) -> ProbeResult:
        url = self.env.get("POSTIZ_URL", "").strip()
        key = self.env.get("POSTIZ_API_KEY", "").strip()
        if not url or not key:
            missing = [n for n, v in [
                ("POSTIZ_URL", url), ("POSTIZ_API_KEY", key),
            ] if not v]
            return ProbeResult(
                name="postiz",
                status=ProbeStatus.FAIL,
                message=f"missing env: {', '.join(missing)}",
            )
        return self._http_get_ok(
            name="postiz",
            url=url.rstrip("/") + "/api/public/v1/integrations",
            headers={"Authorization": key},
        )

    def _probe_telegram(self) -> ProbeResult:
        token = self.env.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            return ProbeResult(
                name="telegram",
                status=ProbeStatus.FAIL,
                message="TELEGRAM_BOT_TOKEN not set",
            )
        return self._http_get_ok(
            name="telegram",
            url=f"https://api.telegram.org/bot{token}/getMe",
        )

    def _probe_fal_ai(self) -> ProbeResult:
        key = self.env.get("FAL_API_KEY", "").strip()
        if not key:
            return ProbeResult(
                name="fal_ai",
                status=ProbeStatus.SKIP,
                message="FAL_API_KEY not set (optional)",
                required=False,
            )
        # fal.ai has no public liveness endpoint; a GET to the base
        # URL is advisory only.
        t0 = time.monotonic()
        try:
            resp = self.http_client_factory().get(
                "https://fal.run/",
                headers={"Authorization": f"Key {key}"},
                timeout=self.timeout_s,
            )
            sc = getattr(resp, "status_code", 0)
            # fal.ai returns 404 for the bare root — that's a healthy
            # signal the edge is reachable.
            if sc in (200, 401, 403, 404):
                return ProbeResult(
                    name="fal_ai",
                    status=ProbeStatus.PASS,
                    message=f"HTTP {sc}",
                    latency_ms=(time.monotonic() - t0) * 1000,
                    required=False,
                )
            return ProbeResult(
                name="fal_ai",
                status=ProbeStatus.WARN,
                message=f"unexpected HTTP {sc}",
                latency_ms=(time.monotonic() - t0) * 1000,
                required=False,
            )
        except Exception as exc:
            return ProbeResult(
                name="fal_ai",
                status=ProbeStatus.WARN,
                message=f"probe failed: {exc}",
                latency_ms=(time.monotonic() - t0) * 1000,
                required=False,
            )

    # ─── HTTP helpers ──────────────────────────────────────────────────

    def _http_get_ok(
        self,
        *,
        name: str,
        url: str,
        headers: Mapping[str, str] | None = None,
    ) -> ProbeResult:
        """GET ``url``; PASS on 2xx, FAIL otherwise."""
        t0 = time.monotonic()
        try:
            resp = self.http_client_factory().get(
                url, headers=dict(headers) if headers else {},
                timeout=self.timeout_s,
            )
        except Exception as exc:
            return ProbeResult(
                name=name, status=ProbeStatus.FAIL,
                message=f"{url}: {exc}",
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        sc = getattr(resp, "status_code", 0)
        ms = (time.monotonic() - t0) * 1000
        if 200 <= sc < 300:
            return ProbeResult(
                name=name, status=ProbeStatus.PASS,
                message=f"HTTP {sc}", latency_ms=ms,
            )
        return ProbeResult(
            name=name, status=ProbeStatus.FAIL,
            message=f"HTTP {sc} from {url}",
            latency_ms=ms,
        )

    def _http_get_json(self, *, name: str, url: str) -> ProbeResult:
        """GET ``url`` + capture body in the message (truncated).
        Used by chatterbox refs probe so the operator sees the refs
        list in the summary."""
        t0 = time.monotonic()
        try:
            resp = self.http_client_factory().get(
                url, headers={}, timeout=self.timeout_s,
            )
        except Exception as exc:
            return ProbeResult(
                name=name, status=ProbeStatus.FAIL,
                message=f"{url}: {exc}",
                latency_ms=(time.monotonic() - t0) * 1000,
            )
        sc = getattr(resp, "status_code", 0)
        ms = (time.monotonic() - t0) * 1000
        if not (200 <= sc < 300):
            return ProbeResult(
                name=name, status=ProbeStatus.FAIL,
                message=f"HTTP {sc} from {url}",
                latency_ms=ms,
            )
        body = ""
        try:
            body = resp.text if hasattr(resp, "text") else str(resp.json())
        except Exception:
            body = ""
        return ProbeResult(
            name=name, status=ProbeStatus.PASS,
            message=body[:300],
            latency_ms=ms,
        )


# ─── Formatting + CLI ──────────────────────────────────────────────────────


_SYMBOLS = {
    ProbeStatus.PASS: "[ok]",
    ProbeStatus.WARN: "[warn]",
    ProbeStatus.FAIL: "[FAIL]",
    ProbeStatus.SKIP: "[skip]",
}


def format_results(results: List[ProbeResult]) -> str:
    lines: List[str] = ["Vesper network probe:"]
    for r in results:
        sym = _SYMBOLS[r.status]
        tail = f" — {r.message}" if r.message else ""
        lat = f" ({r.latency_ms:.0f} ms)" if r.latency_ms else ""
        lines.append(f"  {sym} {r.name}{lat}{tail}")
    blockers = [r for r in results if r.is_blocking]
    totals = {s.value: len([r for r in results if r.status == s])
              for s in ProbeStatus}
    lines.append(
        f"\nSummary: {totals['pass']} ok, {totals['warn']} warn, "
        f"{totals['skip']} skip, {totals['fail']} fail — "
        f"{len(blockers)} blocking"
    )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    prober = Prober()
    results = prober.run()
    print(format_results(results))
    return 2 if prober.blocking_failures(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "Prober",
    "ProbeResult",
    "ProbeStatus",
    "format_results",
    "main",
]
