"""Tests for :mod:`scripts.video_gen.gpu_mutex`.

Uses the in-memory :class:`FakeMutexBackend` so tests are deterministic
and don't need a Redis. A separate integration-test lane (out of scope
here) exercises the real ``RedisMutexBackend`` against a local redis.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from video_gen.gpu_mutex import (  # type: ignore
    DEFAULT_MUTEX_KEY,
    FakeMutexBackend,
    GpuMutexAcquireTimeout,
    GpuPlaneMutex,
)


class _FakeClock:
    """Monotonic injectable clock for sleep-free tests."""

    def __init__(self, start: float = 1000.0):
        self.t = start
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def _mutex(backend: FakeMutexBackend | None = None, **kwargs) -> tuple[GpuPlaneMutex, _FakeClock]:
    clock = _FakeClock()
    backend = backend if backend is not None else FakeMutexBackend()
    backend._clock = clock.now  # type: ignore[attr-defined]
    mutex = GpuPlaneMutex(
        backend,
        clock=clock.now,
        sleep=clock.sleep,
        **kwargs,
    )
    return mutex, clock


class GpuMutexAcquireReleaseTests(unittest.TestCase):
    def test_acquire_on_free_slot_returns_immediately(self):
        mutex, clock = _mutex()
        lock = mutex.acquire(caller="vesper.flux", timeout_s=10)
        self.assertEqual(lock.caller, "vesper.flux")
        self.assertEqual(lock.key, DEFAULT_MUTEX_KEY)
        self.assertTrue(lock.token)
        self.assertEqual(clock.sleeps, [])

    def test_release_by_holder_frees_the_slot(self):
        mutex, _ = _mutex()
        first = mutex.acquire(caller="a")
        self.assertTrue(mutex.release(first))
        # A second caller can now acquire.
        second = mutex.acquire(caller="b")
        self.assertEqual(second.caller, "b")

    def test_release_after_expiry_is_a_noop(self):
        """If the TTL expired and someone else holds the slot, a late
        release() must NOT evict the current holder."""
        backend = FakeMutexBackend()
        mutex, clock = _mutex(backend=backend, ttl_s=100)
        slow = mutex.acquire(caller="slow")
        # Jump past TTL; a new caller grabs the freed slot.
        clock.t += 150
        fast = mutex.acquire(caller="fast")
        self.assertNotEqual(slow.token, fast.token)
        # Slow caller's late release must not remove fast's lock.
        self.assertFalse(mutex.release(slow))
        # Fast is still the holder.
        self.assertTrue(mutex.release(fast))


class GpuMutexContentionTests(unittest.TestCase):
    def test_second_acquire_blocks_until_release(self):
        mutex, clock = _mutex(poll_interval_s=1.0)
        held = mutex.acquire(caller="a")

        # Start a second acquire; it must spin until the slot is free.
        # Simulate this by manually iterating: since FakeMutexBackend is
        # synchronous, we release mid-polls and check that acquire returns.
        # Poll interval=1s, timeout=5s → 5 polls max.
        #
        # Plant a release after 2 polls by wrapping backend.
        original_try = mutex._backend.try_acquire  # type: ignore[attr-defined]
        call_count = {"n": 0}

        def counted_try(key, token, ttl_s):
            call_count["n"] += 1
            if call_count["n"] == 3:
                mutex.release(held)
            return original_try(key, token, ttl_s)

        mutex._backend.try_acquire = counted_try  # type: ignore[assignment]
        second = mutex.acquire(caller="b", timeout_s=10)
        self.assertEqual(second.caller, "b")
        # Polled at least twice before the release planted on call 3.
        self.assertGreaterEqual(len(clock.sleeps), 2)

    def test_acquire_timeout_raises(self):
        mutex, clock = _mutex(poll_interval_s=1.0)
        _ = mutex.acquire(caller="hog")  # never released
        with self.assertRaises(GpuMutexAcquireTimeout) as cm:
            mutex.acquire(caller="starved", timeout_s=3.0)
        self.assertIn("starved", str(cm.exception))
        self.assertIn("Degrade stage", str(cm.exception))


class GpuMutexContextManagerTests(unittest.TestCase):
    def test_lock_context_acquires_and_releases(self):
        mutex, _ = _mutex()
        with mutex.lock(caller="vesper.flux") as lock:
            self.assertTrue(lock.token)
            # During the block, the slot is held.
            with self.assertRaises(GpuMutexAcquireTimeout):
                mutex.acquire(caller="other", timeout_s=0.5)
        # After the block, the slot is free again.
        next_lock = mutex.acquire(caller="after", timeout_s=1.0)
        self.assertEqual(next_lock.caller, "after")

    def test_lock_releases_even_on_exception(self):
        mutex, _ = _mutex()
        with self.assertRaises(RuntimeError):
            with mutex.lock(caller="vesper.i2v"):
                raise RuntimeError("I2V blew up")
        # Slot must be free even though the caller raised.
        after = mutex.acquire(caller="next", timeout_s=1.0)
        self.assertEqual(after.caller, "next")


class GpuMutexTokenIsolationTests(unittest.TestCase):
    def test_tokens_are_unique_per_acquire(self):
        mutex, _ = _mutex()
        a = mutex.acquire(caller="x")
        mutex.release(a)
        b = mutex.acquire(caller="x")
        self.assertNotEqual(a.token, b.token, "tokens must not collide across acquires")

    def test_release_with_foreign_token_rejected(self):
        mutex, _ = _mutex()
        held = mutex.acquire(caller="real")
        # Forge a lock handle with the wrong token.
        from video_gen.gpu_mutex import AcquiredLock
        forged = AcquiredLock(
            key=held.key,
            token="attacker-token",
            caller="attacker",
            job_id="fake",
            acquired_at=0.0,
        )
        self.assertFalse(mutex.release(forged))
        # Real holder can still release.
        self.assertTrue(mutex.release(held))


if __name__ == "__main__":
    unittest.main(verbosity=2)
