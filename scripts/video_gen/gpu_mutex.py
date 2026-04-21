"""Server-side GPU plane mutex (plan Key Decision #6 option b).

The Ubuntu server at 192.168.29.237 has one RTX 3090 (24 GB VRAM). Four
consumers contend for it: chatterbox TTS, Depth Anything V2 + DepthFlow
parallax, local Flux stills, and Wan2.2-class I2V. None can reliably
co-reside under peak VRAM; all must serialize through this mutex.

The laptop-side ``fcntl.flock`` pattern used by the MoviePy sidecar is
irrelevant here — those locks don't coordinate with the server. The
mutex must live on the server. Redis is already present on the server
(``commoncreed_redis``, used by Postiz's BullMQ queue) so we borrow it
for a single-slot semaphore.

Design:
  * Key: ``gpu:plane:mutex`` (one slot).
  * Acquire via ``SET key token NX EX ttl`` — atomic.
  * Release via a Lua script that only ``DEL``s if the stored value
    matches the caller's token. Prevents a post-TTL reacquire race
    where a slow caller's ``release()`` evicts a fresh holder.
  * Blocking ``acquire(timeout_s)`` polls with 0.5 s sleep.
  * TTL default 15 min — longer than the worst-case Wan2.2 I2V clip
    (~5 min) with buffer, but short enough that a crashed caller
    self-heals without manual ops.

Callers (orchestrator):
  Use :meth:`GpuPlaneMutex.lock` as a context manager::

      with mutex.lock(caller="vesper.flux", job_id=job_uuid):
          client.submit_workflow(...)

Priority between stages (chatterbox > parallax > Flux > I2V) is the
orchestrator's responsibility — this module enforces serialization,
not ordering.
"""

from __future__ import annotations

import logging
import secrets
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional, Protocol

logger = logging.getLogger(__name__)


DEFAULT_MUTEX_KEY = "gpu:plane:mutex"
DEFAULT_TTL_S = 15 * 60           # 15 min — longer than worst-case I2V clip
DEFAULT_ACQUIRE_TIMEOUT_S = 10 * 60  # 10 min per Key Decision #6
DEFAULT_POLL_INTERVAL_S = 0.5


# Lua script: DEL key only if GET key == token.
# Run under EVAL to avoid a GET-then-DEL race across callers.
_RELEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""


class GpuMutexAcquireTimeout(TimeoutError):
    """Raised when :meth:`GpuPlaneMutex.acquire` exceeds its timeout.

    Callers (per Key Decision #6) should degrade their stage rather
    than retry immediately:
      * parallax → static Ken Burns
      * Flux    → fal.ai fallback via flux_router
      * I2V     → still_parallax fallback
    """


class MutexBackend(Protocol):
    """Minimal interface for a key-value store supporting atomic
    compare-and-set with TTL.

    Production: :class:`RedisMutexBackend` wrapping ``redis.Redis``.
    Tests: :class:`FakeMutexBackend` below.
    """

    def try_acquire(self, key: str, token: str, ttl_s: int) -> bool:
        """SET key token NX EX ttl — return True if this caller got the slot."""

    def release(self, key: str, token: str) -> bool:
        """Delete ``key`` iff its current value equals ``token``. Returns
        True if the key was actually deleted by this call."""


class RedisMutexBackend:
    """Production backend: atomic SETNX+EXPIRE via redis-py.

    The ``redis`` package is imported lazily so this module can be
    imported (and its tests run) without ``redis-py`` installed.
    """

    def __init__(self, redis_client) -> None:  # type: ignore[no-untyped-def]
        self._r = redis_client
        # Register the Lua release script once; EVALSHA is faster and
        # avoids re-sending the source every release.
        self._release_script = self._r.register_script(_RELEASE_LUA)

    def try_acquire(self, key: str, token: str, ttl_s: int) -> bool:
        # redis-py returns True on success, None when NX-blocked.
        got = self._r.set(key, token, nx=True, ex=ttl_s)
        return bool(got)

    def release(self, key: str, token: str) -> bool:
        return bool(self._release_script(keys=[key], args=[token]))


class FakeMutexBackend:
    """In-memory backend for unit tests. Not thread-safe — tests
    exercise sequential acquire/release ordering, not real contention."""

    def __init__(self) -> None:
        # key -> (token, expires_at_monotonic)
        self._store: dict[str, tuple[str, float]] = {}
        self._clock = time.monotonic

    def _expired(self, expires_at: float) -> bool:
        return self._clock() >= expires_at

    def try_acquire(self, key: str, token: str, ttl_s: int) -> bool:
        existing = self._store.get(key)
        if existing is not None and not self._expired(existing[1]):
            return False
        self._store[key] = (token, self._clock() + ttl_s)
        return True

    def release(self, key: str, token: str) -> bool:
        existing = self._store.get(key)
        if existing is None:
            return False
        held_token, _ = existing
        if held_token != token:
            return False
        del self._store[key]
        return True


@dataclass(frozen=True)
class AcquiredLock:
    """Handle returned by :meth:`GpuPlaneMutex.acquire`.

    Held only long enough for the caller's GPU-bound work to finish.
    ``token`` is the secret value stored under the mutex key — only
    the holder can :meth:`GpuPlaneMutex.release` it (via the Lua
    check-and-del script)."""

    key: str
    token: str
    caller: str
    job_id: str
    acquired_at: float


class GpuPlaneMutex:
    """Single-slot semaphore for the server 3090.

    Stateless other than the backend — safe to instantiate per-call or
    share across a pipeline. Real coordination lives in Redis."""

    def __init__(
        self,
        backend: MutexBackend,
        *,
        key: str = DEFAULT_MUTEX_KEY,
        ttl_s: int = DEFAULT_TTL_S,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        clock=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        self._backend = backend
        self._key = key
        self._ttl_s = ttl_s
        self._poll = poll_interval_s
        self._clock = clock
        self._sleep = sleep

    def acquire(
        self,
        *,
        caller: str,
        job_id: Optional[str] = None,
        timeout_s: float = DEFAULT_ACQUIRE_TIMEOUT_S,
    ) -> AcquiredLock:
        """Block until the GPU plane is free or ``timeout_s`` elapses.

        :param caller: Short stage label for logs (e.g. ``"vesper.flux"``).
        :param job_id: Optional job UUID — defaults to a fresh uuid4.
        :param timeout_s: Max wall-clock seconds to wait.
        :raises GpuMutexAcquireTimeout: when the slot remains held past
            the timeout. Callers should degrade their stage rather than
            retry in a hot loop.
        """
        if job_id is None:
            job_id = str(uuid.uuid4())
        token = f"{caller}:{job_id}:{secrets.token_hex(4)}"
        deadline = self._clock() + timeout_s
        wait_start = self._clock()

        while True:
            if self._backend.try_acquire(self._key, token, self._ttl_s):
                waited = self._clock() - wait_start
                logger.info(
                    "gpu_mutex acquired key=%s caller=%s job=%s waited=%.2fs",
                    self._key, caller, job_id, waited,
                )
                return AcquiredLock(
                    key=self._key,
                    token=token,
                    caller=caller,
                    job_id=job_id,
                    acquired_at=self._clock(),
                )

            if self._clock() >= deadline:
                waited = self._clock() - wait_start
                logger.warning(
                    "gpu_mutex TIMEOUT key=%s caller=%s job=%s waited=%.2fs",
                    self._key, caller, job_id, waited,
                )
                raise GpuMutexAcquireTimeout(
                    f"GPU plane busy for {waited:.0f}s (caller={caller} "
                    f"job={job_id}); timeout={timeout_s:.0f}s. Degrade stage."
                )

            self._sleep(self._poll)

    def release(self, lock: AcquiredLock) -> bool:
        """Release a lock held by this caller. Returns True if the key
        was actually removed by this call; False means the TTL had
        already expired and someone else holds the slot now."""
        deleted = self._backend.release(lock.key, lock.token)
        if deleted:
            held_for = self._clock() - lock.acquired_at
            logger.info(
                "gpu_mutex released key=%s caller=%s job=%s held=%.2fs",
                lock.key, lock.caller, lock.job_id, held_for,
            )
        else:
            logger.warning(
                "gpu_mutex release NOOP (token mismatch — TTL expired?) "
                "key=%s caller=%s job=%s",
                lock.key, lock.caller, lock.job_id,
            )
        return deleted

    @contextmanager
    def lock(
        self,
        *,
        caller: str,
        job_id: Optional[str] = None,
        timeout_s: float = DEFAULT_ACQUIRE_TIMEOUT_S,
    ) -> Iterator[AcquiredLock]:
        """Context-manager wrapper around :meth:`acquire`/:meth:`release`.

        Usage::

            with mutex.lock(caller="vesper.flux", job_id=j):
                client.submit_workflow(...)
        """
        acquired = self.acquire(caller=caller, job_id=job_id, timeout_s=timeout_s)
        try:
            yield acquired
        finally:
            self.release(acquired)


__all__ = [
    "AcquiredLock",
    "DEFAULT_ACQUIRE_TIMEOUT_S",
    "DEFAULT_MUTEX_KEY",
    "DEFAULT_TTL_S",
    "FakeMutexBackend",
    "GpuMutexAcquireTimeout",
    "GpuPlaneMutex",
    "MutexBackend",
    "RedisMutexBackend",
]
