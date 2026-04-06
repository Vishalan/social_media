"""
SQLite bootstrap for the sidecar.

Uses stdlib sqlite3 (no ORM). WAL mode is enabled for concurrent readers
while the scheduler writes. The schema here is intentionally minimal —
Units 3-7 will extend these tables with ALTER TABLE patterns.
"""
from __future__ import annotations

import json
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


# Additive column migrations for pipeline_runs. Each entry is a
# (column_name, column_ddl) pair. Applied with a try/except so running twice
# (or running alongside a parallel ALTER from another unit adding different
# columns) is safe — SQLite raises OperationalError with "duplicate column
# name" if the column already exists, which we swallow.
_PIPELINE_RUNS_COLUMN_MIGRATIONS: list[tuple[str, str]] = [
    # Unit 5 — generated caption payload
    ("captions_json", "TEXT"),
    # Unit 3 — topic selection metadata from the daily newsletter trigger
    ("topic_title", "TEXT"),
    ("topic_url", "TEXT"),
    ("topic_score", "REAL"),
    ("selection_rationale", "TEXT"),
]


def _apply_column_migrations(conn: sqlite3.Connection) -> None:
    for name, ddl in _PIPELINE_RUNS_COLUMN_MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE pipeline_runs ADD COLUMN {name} {ddl}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                continue
            raise


def init_db(db_path: str) -> None:
    """Create tables if they don't exist. Idempotent."""
    conn = connect(db_path)
    try:
        with conn:
            for stmt in SCHEMA_STATEMENTS:
                conn.execute(stmt)
            _apply_column_migrations(conn)
    finally:
        conn.close()


def insert_pipeline_run(
    conn: sqlite3.Connection,
    topic_title: str,
    topic_url: str,
    topic_score: float,
    selection_rationale: str,
    source_newsletter_date: str,
    status: str = "pending_generation",
) -> int:
    """Insert a pipeline_runs row for a newly selected topic and return its id.

    Runs the additive column migration first so callers who open their own
    connection (e.g. tests with an in-memory DB that only called the raw
    CREATE TABLE) don't have to remember to call ``init_db`` separately.
    """
    _apply_column_migrations(conn)
    cur = conn.execute(
        """
        INSERT INTO pipeline_runs (
            status,
            topic_title,
            topic_url,
            topic_score,
            selection_rationale,
            source_newsletter_date
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            status,
            topic_title,
            topic_url,
            topic_score,
            selection_rationale,
            source_newsletter_date,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def set_captions(
    conn: sqlite3.Connection, pipeline_run_id: int, captions: dict
) -> None:
    """Serialize ``captions`` as JSON and store it on the given pipeline run."""
    payload = json.dumps(captions)
    with conn:
        conn.execute(
            "UPDATE pipeline_runs SET captions_json = ? WHERE id = ?",
            (payload, pipeline_run_id),
        )


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
