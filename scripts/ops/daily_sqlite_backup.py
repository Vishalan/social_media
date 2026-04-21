"""Daily SQLite backup for :mod:`scripts.analytics.tracker`.

Runs once per day (via a LaunchAgent — see
``deploy/com.vesper.sqlite_backup.plist``) and produces a crash-safe
copy of ``data/analytics.db`` under ``data/backups/``. Retention is
applied in-place: older-than-N backups are removed after each run.

Why a dedicated backup script and not just ``shutil.copy2``?
  * SQLite under WAL mode is two files (``.db`` and ``.db-wal``).
    Copying the ``.db`` alone while writes are in-flight risks an
    inconsistent snapshot. :meth:`sqlite3.Connection.backup`
    performs an online-atomic copy that's safe under concurrent
    writes from ``AnalyticsTracker``.
  * The backup filename carries a timestamp so the restore path
    (see ``docs/runbooks/vesper/vesper-incident-response.md``) can
    pick a specific point-in-time rather than the most-recent-only.
  * Failures MUST NOT kill the calling shell with a zero status —
    the LaunchAgent log is the only visibility the operator has;
    we exit non-zero on real failure so launchd surfaces it in
    the system log.

Invocation:
    python -m scripts.ops.daily_sqlite_backup
    python -m scripts.ops.daily_sqlite_backup \\
        --db data/analytics.db \\
        --backup-dir data/backups --retention-days 30
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


DEFAULT_DB_PATH = "data/analytics.db"
DEFAULT_BACKUP_DIR = "data/backups"
DEFAULT_RETENTION_DAYS = 30
BACKUP_FILENAME_FMT = "analytics_%Y-%m-%d_%H%M%S.db"

# Security posture S8 — backups are mode 0600, same as the live DB.
_BACKUP_MODE = 0o600


class BackupError(RuntimeError):
    """Raised on unrecoverable backup failure. LaunchAgent sees the
    non-zero exit + message in stderr."""


def run_backup(
    *,
    db_path: str = DEFAULT_DB_PATH,
    backup_dir: str = DEFAULT_BACKUP_DIR,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    clock=datetime.utcnow,
) -> Path:
    """Create one backup and trim older-than-``retention_days`` files.

    Returns the new backup's :class:`Path`.
    """
    db = Path(db_path)
    if not db.exists():
        raise BackupError(f"source DB not found: {db_path}")

    out_dir = Path(backup_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    now = clock()
    out_name = now.strftime(BACKUP_FILENAME_FMT)
    out_path = out_dir / out_name

    # Online backup via sqlite3 C API — safe under concurrent writes.
    src_conn = sqlite3.connect(str(db))
    try:
        dst_conn = sqlite3.connect(str(out_path))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()

    try:
        os.chmod(out_path, _BACKUP_MODE)
    except PermissionError:
        # Not fatal — OS may lock down chmod on bind-mounted volumes.
        logger.warning(
            "daily_sqlite_backup: could not chmod %s to 0600", out_path,
        )

    # Sanity check: the new file is non-empty.
    if out_path.stat().st_size == 0:
        out_path.unlink(missing_ok=True)
        raise BackupError(
            f"backup produced zero-byte file for {db_path}; removed"
        )

    logger.info(
        "daily_sqlite_backup: wrote %s (%d bytes)",
        out_path, out_path.stat().st_size,
    )
    trim_old_backups(
        backup_dir=str(out_dir),
        retention_days=retention_days,
        now=now,
    )
    return out_path


def trim_old_backups(
    *,
    backup_dir: str,
    retention_days: int,
    now: datetime,
) -> List[Path]:
    """Remove backups older than ``retention_days`` in ``backup_dir``.

    Returns the list of removed paths (for test visibility). The
    caller's ``now`` is passed through to keep time-windowing
    deterministic in tests."""
    if retention_days <= 0:
        return []
    cutoff = now - timedelta(days=retention_days)
    removed: List[Path] = []
    out_dir = Path(backup_dir)
    if not out_dir.exists():
        return []
    for p in out_dir.iterdir():
        if not p.is_file():
            continue
        if not p.name.startswith("analytics_") or not p.name.endswith(".db"):
            continue
        # Prefer embedded timestamp; fall back to mtime if it won't parse.
        stem = p.stem  # analytics_YYYY-MM-DD_HHMMSS
        ts: Optional[datetime] = None
        try:
            ts = datetime.strptime(stem, "analytics_%Y-%m-%d_%H%M%S")
        except ValueError:
            ts = datetime.utcfromtimestamp(p.stat().st_mtime)
        if ts < cutoff:
            try:
                p.unlink()
                removed.append(p)
                logger.info("daily_sqlite_backup: trimmed %s", p)
            except OSError as exc:
                logger.warning(
                    "daily_sqlite_backup: could not remove %s: %s", p, exc,
                )
    return removed


# ─── CLI entry ─────────────────────────────────────────────────────────────


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Daily SQLite backup for analytics.db",
    )
    p.add_argument("--db", default=DEFAULT_DB_PATH)
    p.add_argument("--backup-dir", default=DEFAULT_BACKUP_DIR)
    p.add_argument(
        "--retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="log per-action at INFO level",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    try:
        run_backup(
            db_path=args.db,
            backup_dir=args.backup_dir,
            retention_days=args.retention_days,
        )
    except BackupError as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # Unexpected — still exit non-zero so launchd flags it, but
        # print the traceback since this is unfamiliar territory.
        import traceback
        traceback.print_exc()
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BackupError",
    "run_backup",
    "trim_old_backups",
]
