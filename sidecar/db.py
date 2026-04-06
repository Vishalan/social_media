"""
SQLite bootstrap for the sidecar.

Uses stdlib sqlite3 (no ORM). WAL mode is enabled for concurrent readers
while the scheduler writes. The schema here is intentionally minimal —
Units 3-7 will extend these tables with ALTER TABLE patterns.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at             TEXT NOT NULL DEFAULT (datetime('now')),
        status                 TEXT NOT NULL DEFAULT 'pending',
        source_newsletter_date TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS approvals (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        pipeline_run_id INTEGER NOT NULL,
        status          TEXT NOT NULL DEFAULT 'pending',
        created_at      TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        key        TEXT PRIMARY KEY,
        value      TEXT,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
]


def _ensure_parent(db_path: str) -> None:
    if db_path == ":memory:":
        return
    parent = Path(db_path).parent
    if parent and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)


def connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with sane defaults for the sidecar."""
    _ensure_parent(db_path)
    # isolation_level=None gives us explicit transaction control via BEGIN/COMMIT;
    # we keep the default deferred isolation for simple writes here.
    conn = sqlite3.connect(db_path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if db_path != ":memory:":
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.DatabaseError:
            # Some filesystems (e.g. certain network mounts) reject WAL; we
            # fall back silently rather than crashing startup.
            pass
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: str) -> None:
    """Create tables if they don't exist. Idempotent."""
    conn = connect(db_path)
    try:
        with conn:
            for stmt in SCHEMA_STATEMENTS:
                conn.execute(stmt)
    finally:
        conn.close()


def list_tables(db_path: str) -> list[str]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]
    finally:
        conn.close()


def db_writable(db_path: str) -> bool:
    """Open a write transaction to confirm the file is writable."""
    try:
        conn = connect(db_path)
    except sqlite3.Error:
        return False
    try:
        with conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS _healthcheck (id INTEGER PRIMARY KEY)"
            )
            conn.execute("INSERT INTO _healthcheck DEFAULT VALUES")
            conn.execute("DELETE FROM _healthcheck")
        return True
    except sqlite3.Error:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


@contextmanager
def cursor(db_path: str) -> Iterator[sqlite3.Cursor]:
    conn = connect(db_path)
    try:
        yield conn.cursor()
        conn.commit()
    finally:
        conn.close()
