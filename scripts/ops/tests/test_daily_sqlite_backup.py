"""Tests for :mod:`scripts.ops.daily_sqlite_backup`."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ops.daily_sqlite_backup import (  # noqa: E402
    BackupError,
    run_backup,
    trim_old_backups,
)


def _make_sample_db(path: Path) -> None:
    """Create a minimal SQLite database with one row so backups are
    non-trivially non-zero."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE t (id INTEGER, note TEXT)")
        conn.execute("INSERT INTO t VALUES (1, 'hello')")
        conn.commit()
    finally:
        conn.close()


class RunBackupHappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="sqlite-backup-")
        self.db_path = Path(self.tmp) / "analytics.db"
        self.backup_dir = Path(self.tmp) / "backups"
        _make_sample_db(self.db_path)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_backup_produces_non_empty_file(self):
        out = run_backup(
            db_path=str(self.db_path),
            backup_dir=str(self.backup_dir),
            retention_days=30,
        )
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 0)

    def test_backup_filename_follows_convention(self):
        out = run_backup(
            db_path=str(self.db_path),
            backup_dir=str(self.backup_dir),
            retention_days=30,
        )
        self.assertTrue(out.name.startswith("analytics_"))
        self.assertTrue(out.name.endswith(".db"))

    def test_backup_file_is_mode_0600(self):
        out = run_backup(
            db_path=str(self.db_path),
            backup_dir=str(self.backup_dir),
            retention_days=30,
        )
        mode = out.stat().st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_backup_round_trip_is_readable(self):
        out = run_backup(
            db_path=str(self.db_path),
            backup_dir=str(self.backup_dir),
            retention_days=30,
        )
        conn = sqlite3.connect(str(out))
        try:
            rows = list(conn.execute("SELECT id, note FROM t"))
        finally:
            conn.close()
        self.assertEqual(rows, [(1, "hello")])


class RunBackupErrorPathTests(unittest.TestCase):
    def test_missing_source_raises_backup_error(self):
        tmp = tempfile.mkdtemp(prefix="sqlite-backup-err-")
        try:
            missing = os.path.join(tmp, "does-not-exist.db")
            with self.assertRaises(BackupError) as cm:
                run_backup(db_path=missing, backup_dir=tmp)
            self.assertIn("source DB not found", str(cm.exception))
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class RetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="sqlite-backup-ret-")
        self.backup_dir = Path(self.tmp) / "backups"
        self.backup_dir.mkdir()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_backup(self, ts: datetime) -> Path:
        name = ts.strftime("analytics_%Y-%m-%d_%H%M%S.db")
        p = self.backup_dir / name
        p.write_bytes(b"sqlite-stub")
        return p

    def test_trim_removes_older_than_retention(self):
        now = datetime(2026, 4, 21, 10, 0, 0)
        fresh = self._make_backup(now - timedelta(days=5))
        stale = self._make_backup(now - timedelta(days=45))
        very_old = self._make_backup(now - timedelta(days=120))

        removed = trim_old_backups(
            backup_dir=str(self.backup_dir),
            retention_days=30,
            now=now,
        )

        removed_names = {p.name for p in removed}
        self.assertIn(stale.name, removed_names)
        self.assertIn(very_old.name, removed_names)
        self.assertNotIn(fresh.name, removed_names)
        self.assertTrue(fresh.exists())
        self.assertFalse(stale.exists())
        self.assertFalse(very_old.exists())

    def test_trim_ignores_unrelated_files(self):
        now = datetime(2026, 4, 21, 10, 0, 0)
        # File that doesn't match the naming pattern — must survive.
        unrelated = self.backup_dir / "README.md"
        unrelated.write_text("docs")
        trim_old_backups(
            backup_dir=str(self.backup_dir),
            retention_days=1,
            now=now,
        )
        self.assertTrue(unrelated.exists())

    def test_retention_zero_or_negative_is_noop(self):
        now = datetime(2026, 4, 21, 10, 0, 0)
        p = self._make_backup(now - timedelta(days=365))
        removed = trim_old_backups(
            backup_dir=str(self.backup_dir),
            retention_days=0,
            now=now,
        )
        self.assertEqual(removed, [])
        self.assertTrue(p.exists())


class IntegrationTests(unittest.TestCase):
    """run_backup + trim_old_backups working together."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="sqlite-backup-int-")
        self.db_path = Path(self.tmp) / "analytics.db"
        self.backup_dir = Path(self.tmp) / "backups"
        _make_sample_db(self.db_path)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_backup_trims_within_call(self):
        # Seed an old backup that should be trimmed.
        self.backup_dir.mkdir()
        old = self.backup_dir / "analytics_2026-01-01_000000.db"
        old.write_bytes(b"stale")

        now = datetime(2026, 4, 21, 10, 0, 0)
        run_backup(
            db_path=str(self.db_path),
            backup_dir=str(self.backup_dir),
            retention_days=30,
            clock=lambda: now,
        )

        # Old backup removed; new one present.
        self.assertFalse(old.exists())
        new_backups = [
            p for p in self.backup_dir.iterdir()
            if p.name.startswith("analytics_2026-04-21")
        ]
        self.assertEqual(len(new_backups), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
