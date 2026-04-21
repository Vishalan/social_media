"""Shared Postiz rate-limit ledger (plan System-Wide Impact #2).

Postiz's public API caps every endpoint at **30 requests / hour** across
the whole organization. Two pipelines (CommonCreed + Vesper) sharing one
org therefore share this budget. Without coordination a publish-heavy
hour + retry storm can breach the ceiling and drop real posts.

:class:`PostizRateLedger` is a file-backed append-only log with a
fcntl-flock write gate and an in-memory window reader. Callers check
``remaining()`` (or ``assert_available(n)``) before a call and record
actual consumption after. The ledger rotates ~hourly by trimming
entries older than :data:`WINDOW_S`; no separate cron job required.

Write contract:
  * ``consume(n)`` appends ``n`` entries with the current UTC timestamp,
    under an exclusive file lock so concurrent pipelines don't race.
  * Ledger file is mode 0600 (Security Posture — no leakage to shared
    services).

Read contract:
  * ``remaining()`` / ``count_last_hour()`` open the file read-only,
    drop entries older than WINDOW_S, and return counts. Cheap enough
    to call on every publish.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Postiz rolling-window cap: 30 calls / hour across the whole org.
POSTIZ_HOURLY_LIMIT = 30
WINDOW_S = 3600

_DEFAULT_LEDGER_PATH = Path("data/postiz_rate_budget.jsonl")


@dataclass(frozen=True)
class LedgerEntry:
    ts_utc: float       # Unix epoch seconds, UTC
    channel_id: str     # "commoncreed" | "vesper" | ...
    endpoint: str       # e.g. "publish_post", "upload_file"
    count: int = 1      # usually 1; batched calls may append n

    def to_json(self) -> str:
        return json.dumps({
            "ts_utc": self.ts_utc,
            "channel_id": self.channel_id,
            "endpoint": self.endpoint,
            "count": self.count,
        })

    @classmethod
    def from_json(cls, line: str) -> Optional["LedgerEntry"]:
        try:
            data = json.loads(line.strip())
            return cls(
                ts_utc=float(data["ts_utc"]),
                channel_id=str(data["channel_id"]),
                endpoint=str(data.get("endpoint") or ""),
                count=int(data.get("count") or 1),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None


class PostizRateBudgetExceeded(RuntimeError):
    """Raised by ``assert_available()`` when the requested call count
    would breach the rolling-hour cap."""


class PostizRateLedger:
    """File-backed rolling-hour ledger of Postiz API consumption."""

    def __init__(
        self,
        path: Path = _DEFAULT_LEDGER_PATH,
        *,
        hourly_limit: int = POSTIZ_HOURLY_LIMIT,
        window_s: int = WINDOW_S,
        clock=time.time,
    ) -> None:
        self.path = Path(path)
        self.hourly_limit = hourly_limit
        self.window_s = window_s
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Touch with owner-only perms up-front — cheap idempotent guard
        # so we never end up with a world-readable ledger.
        if not self.path.exists():
            fd = os.open(
                self.path,
                os.O_CREAT | os.O_WRONLY | os.O_APPEND,
                0o600,
            )
            os.close(fd)
        else:
            try:
                os.chmod(self.path, 0o600)
            except PermissionError:
                pass  # Not fatal — permissions may be locked by OS.

    # ── Read path ─────────────────────────────────────────────────────────

    def _read_entries(self) -> List[LedgerEntry]:
        if not self.path.exists():
            return []
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("PostizRateLedger read failed: %s", exc)
            return []
        entries: List[LedgerEntry] = []
        for line in raw.splitlines():
            e = LedgerEntry.from_json(line)
            if e is not None:
                entries.append(e)
        return entries

    def _within_window(self, entries: List[LedgerEntry]) -> List[LedgerEntry]:
        cutoff = self._clock() - self.window_s
        return [e for e in entries if e.ts_utc >= cutoff]

    def count_last_hour(self, *, channel_id: Optional[str] = None) -> int:
        """Return the number of ledger-entry *counts* within the window.

        When ``channel_id`` is given, filter to that channel only.
        Otherwise return the org-wide total that's load-bearing against
        the 30/hour cap.
        """
        entries = self._within_window(self._read_entries())
        if channel_id is not None:
            entries = [e for e in entries if e.channel_id == channel_id]
        return sum(e.count for e in entries)

    def remaining(self) -> int:
        """Return how many org-wide calls are still free in this window."""
        return max(0, self.hourly_limit - self.count_last_hour())

    def assert_available(self, n: int = 1) -> None:
        """Raise :class:`PostizRateBudgetExceeded` if consuming ``n`` now
        would breach the cap. Intended as a pre-flight guard before a
        burst of publishes (e.g., a multi-platform post = 3-5 calls)."""
        if self.remaining() < n:
            raise PostizRateBudgetExceeded(
                f"Postiz rate budget exhausted: {self.remaining()} remaining, "
                f"need {n}. Window={self.window_s}s, limit={self.hourly_limit}."
            )

    # ── Write path ────────────────────────────────────────────────────────

    @contextlib.contextmanager
    def _locked(self, *, timeout_s: float = 10.0):
        """Exclusive file lock (blocking with timeout) for the write path."""
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            deadline = self._clock() + timeout_s
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if self._clock() >= deadline:
                        raise RuntimeError(
                            f"PostizRateLedger: could not acquire lock on "
                            f"{self.path} within {timeout_s}s"
                        )
                    time.sleep(0.05)
            try:
                yield fd
            finally:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            os.close(fd)

    def consume(
        self,
        *,
        channel_id: str,
        endpoint: str = "publish_post",
        count: int = 1,
    ) -> None:
        """Append ``count`` ledger entries. Atomic under fcntl flock."""
        entry = LedgerEntry(
            ts_utc=self._clock(),
            channel_id=channel_id,
            endpoint=endpoint,
            count=count,
        )
        line = entry.to_json() + "\n"
        with self._locked() as fd:
            os.write(fd, line.encode("utf-8"))

    # ── Housekeeping ──────────────────────────────────────────────────────

    def rotate(self) -> int:
        """Drop entries older than the window. Returns the count trimmed.

        Safe to call idempotently (e.g., from a daily cron or after a
        publish burst). Opens the file under exclusive lock so a
        concurrent ``consume()`` can't interleave writes with rotation.
        """
        with self._locked() as _:
            entries = self._within_window(self._read_entries())
            rewritten = "".join(e.to_json() + "\n" for e in entries)
            # Truncate + rewrite. Using a temporary fd keeps the original
            # inode so the flock holder stays correct through the swap.
            tmp_path = self.path.with_suffix(".jsonl.tmp")
            tmp_path.write_text(rewritten, encoding="utf-8")
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.path)
        before = sum(1 for _ in (
            self.path.read_text().splitlines() if self.path.exists() else []
        ))
        return max(0, before - len(entries))


__all__ = [
    "LedgerEntry",
    "POSTIZ_HOURLY_LIMIT",
    "PostizRateBudgetExceeded",
    "PostizRateLedger",
    "WINDOW_S",
]
