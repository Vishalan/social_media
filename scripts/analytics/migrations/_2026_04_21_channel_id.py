"""Schema migration: add ``channel_id`` scoping to AnalyticsTracker tables.

Adds ``channel_id TEXT NOT NULL DEFAULT 'commoncreed'`` to ``posts``,
``revenue``, ``news_items``. Rebuilds ``news_items`` with
``UNIQUE(channel_id, url)`` (replacing ``UNIQUE(url)``). Preserves an
explicit ``idx_news_items_url`` so ``WHERE url = ?`` queries still hit
an index. Records completion in a ``schema_migrations`` sentinel table.

Safety guarantees:
  * Pre-migration backup copy of the DB file (assert size > 0 before
    mutating).
  * Advisory file lock on ``/tmp/analytics-migration.lock`` — refuses
    to run if another migration is in flight.
  * All schema mutations inside one ``BEGIN IMMEDIATE`` transaction;
    ``ROLLBACK`` on any exception.
  * ``PRAGMA foreign_keys=OFF`` during rebuild + ``foreign_key_check``
    after.
  * ``PRAGMA integrity_check`` before commit.
  * ``PRAGMA journal_mode=WAL`` set post-commit (persistent; lets
    readers coexist with future writers without ``database is locked``
    errors).
  * Idempotent: re-running after success is a no-op; re-running after
    partial failure resumes (per-column ``table_info`` check + unique-
    index shape check for ``news_items``).

See docs/plans/2026-04-21-001-feat-vesper-horror-channel-plan.md Unit 2.
"""

from __future__ import annotations

import fcntl
import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)

MIGRATION_ID = "2026-04-21_channel_id"
_LOCK_PATH = "/tmp/analytics-migration.lock"


class MigrationError(RuntimeError):
    """Raised when the migration fails safely and the DB was rolled back."""


def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id TEXT PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL
        )
        """
    )


def _has_applied(conn: sqlite3.Connection, migration_id: str) -> bool:
    _ensure_schema_migrations(conn)
    row = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE id = ? LIMIT 1",
        (migration_id,),
    ).fetchone()
    return row is not None


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _news_items_has_channel_unique(conn: sqlite3.Connection) -> bool:
    """Return True if news_items' unique constraint already covers (channel_id, url)."""
    for idx in conn.execute("PRAGMA index_list('news_items')").fetchall():
        # idx columns: seq, name, unique, origin, partial
        if idx[2] == 1:  # unique
            info = conn.execute(f"PRAGMA index_info('{idx[1]}')").fetchall()
            cols = [c[2] for c in info]
            if "channel_id" in cols and "url" in cols:
                return True
    return False


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _backup(db_path: str) -> str:
    """Copy the DB file to a timestamped backup. Assert size > 0."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = f"{db_path}.bak-{ts}"
    shutil.copy2(db_path, backup_path)
    os.sync()
    size = Path(backup_path).stat().st_size
    if size == 0:
        raise MigrationError(f"backup at {backup_path} is zero bytes — refusing to migrate")
    logger.info("[migration] backup written: %s (%d bytes)", backup_path, size)
    return backup_path


def _acquire_lock() -> int:
    """Acquire /tmp/analytics-migration.lock. Returns the fd.

    Raises MigrationError if another migration is running.
    """
    fd = os.open(_LOCK_PATH, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise MigrationError(
            f"another migration is in progress ({_LOCK_PATH} held). "
            "Wait for it or release the lock."
        )
    return fd


def _release_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _rebuild_news_items(conn: sqlite3.Connection) -> None:
    """CREATE new → COPY → DROP old → RENAME. Runs inside active txn."""
    # Create new table with composite unique constraint.
    conn.execute(
        """
        CREATE TABLE news_items_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT NOT NULL DEFAULT 'commoncreed',
            url TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(channel_id, url)
        )
        """
    )
    # Copy rows — include channel_id if it was already added via ALTER.
    cols = _column_names(conn, "news_items")
    if "channel_id" in cols:
        conn.execute(
            "INSERT INTO news_items_new (id, channel_id, url, normalized_title, fetched_at) "
            "SELECT id, channel_id, url, normalized_title, fetched_at FROM news_items"
        )
    else:
        conn.execute(
            "INSERT INTO news_items_new (id, url, normalized_title, fetched_at) "
            "SELECT id, url, normalized_title, fetched_at FROM news_items"
        )
    # Drop old + rename (channel_id default is applied to pre-existing rows
    # either via the ALTER or via the DEFAULT on the new table).
    conn.execute("DROP TABLE news_items")
    conn.execute("ALTER TABLE news_items_new RENAME TO news_items")
    # Recreate indexes — including an explicit idx_news_items_url so
    # ``WHERE url = ?`` queries still hit an index (the composite unique
    # leads with channel_id, so the old index path needs preserving).
    conn.execute("CREATE INDEX idx_news_items_url ON news_items (url)")
    conn.execute(
        "CREATE INDEX idx_news_items_channel_title "
        "ON news_items (channel_id, normalized_title)"
    )
    conn.execute("CREATE INDEX idx_news_items_fetched_at ON news_items (fetched_at)")


def apply(db_path: str) -> Tuple[bool, str]:
    """Apply the migration atomically. Idempotent.

    Returns (applied, message). ``applied`` is True only if the migration
    ran to completion on this call; False when it was already applied or
    when the DB didn't exist to migrate.
    """
    if not Path(db_path).exists():
        # Nothing to migrate — AnalyticsTracker.__init__ will create the
        # already-scoped schema directly via _init_tables (no migration
        # needed on fresh DBs).
        logger.debug("[migration] db does not exist at %s — skipping", db_path)
        return False, f"db not present at {db_path}; fresh init path will build scoped schema"

    lock_fd = _acquire_lock()
    try:
        # Pre-migration backup (only if DB has data).
        backup_path = _backup(db_path)

        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            # WAL mode change cannot happen inside a transaction — apply after.
            conn.execute("PRAGMA foreign_keys = OFF")

            # Idempotent no-op if already applied.
            if _has_applied(conn, MIGRATION_ID):
                logger.info("[migration] %s already applied — skipping", MIGRATION_ID)
                conn.execute("PRAGMA foreign_keys = ON")
                return False, "already applied"

            # Use BEGIN IMMEDIATE to grab the reserved lock up-front.
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE")

            try:
                # 1. ALTER ADD COLUMN channel_id on posts, revenue, news_items.
                #    Tolerates partial-prior-failure via per-table check.
                for table in ("posts", "revenue", "news_items"):
                    if not _table_exists(conn, table):
                        # Fresh DB path — AnalyticsTracker._init_tables creates
                        # the already-scoped shape directly. Nothing to migrate
                        # for this table.
                        continue
                    if "channel_id" not in _column_names(conn, table):
                        conn.execute(
                            f"ALTER TABLE {table} "
                            "ADD COLUMN channel_id TEXT NOT NULL DEFAULT 'commoncreed'"
                        )

                # 2. Rebuild news_items with composite unique if not already done.
                if _table_exists(conn, "news_items") and not _news_items_has_channel_unique(conn):
                    _rebuild_news_items(conn)

                # 3. Record migration.
                _ensure_schema_migrations(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (id, applied_at) VALUES (?, ?)",
                    (MIGRATION_ID, datetime.now().isoformat()),
                )

                # 4. Post-checks inside the txn.
                fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
                if fk_violations:
                    raise MigrationError(f"foreign_key_check failed: {fk_violations}")

                integrity = conn.execute("PRAGMA integrity_check").fetchone()
                if integrity and integrity[0] != "ok":
                    raise MigrationError(f"integrity_check failed: {integrity[0]}")

                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise

            conn.execute("PRAGMA foreign_keys = ON")
            # WAL mode persists across connections — set once post-commit.
            conn.execute("PRAGMA journal_mode = WAL")

            logger.info(
                "[migration] %s applied; backup at %s",
                MIGRATION_ID, backup_path,
            )
            return True, f"applied; backup at {backup_path}"
        finally:
            conn.close()
    finally:
        _release_lock(lock_fd)


__all__ = ["MIGRATION_ID", "MigrationError", "apply"]
