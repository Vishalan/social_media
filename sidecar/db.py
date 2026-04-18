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
    """
    CREATE TABLE IF NOT EXISTS meme_candidates (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at             TEXT NOT NULL DEFAULT (datetime('now')),
        source                 TEXT NOT NULL,
        source_url             TEXT NOT NULL,
        author_handle          TEXT NOT NULL,
        title                  TEXT NOT NULL,
        media_url              TEXT NOT NULL,
        media_type             TEXT NOT NULL,
        engagement_json        TEXT,
        published_at           TEXT,
        status                 TEXT NOT NULL DEFAULT 'pending_review',
        telegram_message_id    INTEGER,
        normalized_path        TEXT,
        credited_path          TEXT,
        postiz_response_json   TEXT,
        publish_error          TEXT,
        reviewed_at            TEXT,
        published_at_local     TEXT,
        audio_url              TEXT,
        humor_score            REAL,
        relevance_score        REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS meme_denylist (
        handle     TEXT NOT NULL,
        source     TEXT NOT NULL,
        reason     TEXT,
        added_at   TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (handle, source)
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
    # Unit 4 — pipeline subprocess result artifacts
    ("video_path", "TEXT"),
    ("thumbnail_path", "TEXT"),
    ("audio_path", "TEXT"),
    ("cost_sonnet", "REAL DEFAULT 0"),
    ("cost_haiku", "REAL DEFAULT 0"),
    ("cost_elevenlabs", "REAL DEFAULT 0"),
    ("cost_veed", "REAL DEFAULT 0"),
    ("error_log", "TEXT"),
    ("started_at", "TEXT"),
    ("finished_at", "TEXT"),
    # Unit 7 — publish results
    ("post_ids_json", "TEXT"),
    ("publish_attempted_at", "TEXT"),
    ("publish_error", "TEXT"),
    # Unit 9 — retention job stamp
    ("retention_pruned_at", "TEXT"),
]


# Unit 6 — additive migrations for the approvals table.
_APPROVALS_COLUMN_MIGRATIONS: list[tuple[str, str]] = [
    ("owner_action_at", "TEXT"),
    ("proposed_time", "TEXT"),
    ("telegram_message_id", "INTEGER"),
]


def _apply_column_migrations(conn: sqlite3.Connection) -> None:
    for name, ddl in _PIPELINE_RUNS_COLUMN_MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE pipeline_runs ADD COLUMN {name} {ddl}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                continue
            raise
    # Meme candidates additive column migrations
    for name, ddl in [("audio_url", "TEXT"), ("humor_score", "REAL"), ("relevance_score", "REAL")]:
        try:
            conn.execute(f"ALTER TABLE meme_candidates ADD COLUMN {name} {ddl}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                continue
            raise
    for name, ddl in _APPROVALS_COLUMN_MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE approvals ADD COLUMN {name} {ddl}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                continue
            raise


def create_approval(
    conn: sqlite3.Connection,
    pipeline_run_id: int,
    telegram_message_id: int,
) -> int:
    """Insert a pending approvals row, returning its id."""
    _apply_column_migrations(conn)
    cur = conn.execute(
        """
        INSERT INTO approvals (pipeline_run_id, status, telegram_message_id)
        VALUES (?, 'pending', ?)
        """,
        (pipeline_run_id, telegram_message_id),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_approval_by_run_id(
    conn: sqlite3.Connection, pipeline_run_id: int
) -> Optional[dict]:
    _apply_column_migrations(conn)
    row = conn.execute(
        "SELECT * FROM approvals WHERE pipeline_run_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (pipeline_run_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def update_approval_status(
    conn: sqlite3.Connection,
    approval_id: int,
    status: str,
    owner_action_at: str,
    proposed_time: Optional[str] = None,
) -> None:
    _apply_column_migrations(conn)
    with conn:
        if proposed_time is not None:
            conn.execute(
                """
                UPDATE approvals
                   SET status = ?, owner_action_at = ?, proposed_time = ?
                 WHERE id = ?
                """,
                (status, owner_action_at, proposed_time, approval_id),
            )
        else:
            conn.execute(
                """
                UPDATE approvals
                   SET status = ?, owner_action_at = ?
                 WHERE id = ?
                """,
                (status, owner_action_at, approval_id),
            )


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


def get_pending_pipeline_runs(conn: sqlite3.Connection) -> list[dict]:
    """Return all rows with status=='pending_generation' ordered by created_at."""
    _apply_column_migrations(conn)
    rows = conn.execute(
        "SELECT * FROM pipeline_runs WHERE status = 'pending_generation' "
        "ORDER BY created_at ASC, id ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_pipeline_run(conn: sqlite3.Connection, run_id: int) -> Optional[dict]:
    """Fetch a single pipeline_runs row as a dict, or None if not found."""
    _apply_column_migrations(conn)
    row = conn.execute(
        "SELECT * FROM pipeline_runs WHERE id = ?", (run_id,)
    ).fetchone()
    return dict(row) if row is not None else None


def update_pipeline_run_generation_result(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    video_path: Optional[str],
    thumbnail_path: Optional[str],
    audio_path: Optional[str],
    cost_sonnet: float,
    cost_haiku: float,
    cost_elevenlabs: float,
    cost_veed: float,
    error_log: Optional[str],
    started_at: Optional[str],
    finished_at: Optional[str],
) -> None:
    """Single-statement UPDATE of all Unit 4 generation-result columns."""
    _apply_column_migrations(conn)
    with conn:
        conn.execute(
            """
            UPDATE pipeline_runs SET
                status          = ?,
                video_path      = ?,
                thumbnail_path  = ?,
                audio_path      = ?,
                cost_sonnet     = ?,
                cost_haiku      = ?,
                cost_elevenlabs = ?,
                cost_veed       = ?,
                error_log       = ?,
                started_at      = ?,
                finished_at     = ?
            WHERE id = ?
            """,
            (
                status,
                video_path,
                thumbnail_path,
                audio_path,
                cost_sonnet,
                cost_haiku,
                cost_elevenlabs,
                cost_veed,
                error_log,
                started_at,
                finished_at,
                run_id,
            ),
        )


def get_pipeline_run_with_captions(
    conn: sqlite3.Connection, run_id: int
) -> Optional[dict]:
    """Fetch a pipeline_run row and deserialize its captions_json field.

    Returns the row dict with an extra ``captions`` key (parsed dict, possibly
    empty) or None if the row doesn't exist.
    """
    row = get_pipeline_run(conn, run_id)
    if row is None:
        return None
    raw = row.get("captions_json") or "{}"
    try:
        row["captions"] = json.loads(raw)
    except (TypeError, ValueError):
        row["captions"] = {}
    return row


def update_pipeline_run_publish_result(
    conn: sqlite3.Connection,
    run_id: int,
    status: str,
    post_ids: Optional[dict],
    error: Optional[str] = None,
) -> None:
    """Persist Unit 7 publish-result columns on a pipeline_runs row."""
    _apply_column_migrations(conn)
    from datetime import datetime as _dt

    payload = json.dumps(post_ids) if post_ids is not None else None
    with conn:
        conn.execute(
            """
            UPDATE pipeline_runs SET
                status               = ?,
                post_ids_json        = ?,
                publish_attempted_at = ?,
                publish_error        = ?
             WHERE id = ?
            """,
            (
                status,
                payload,
                _dt.utcnow().isoformat(timespec="seconds"),
                error,
                run_id,
            ),
        )


def get_recent_pipeline_runs(
    conn: sqlite3.Connection, limit: int = 50
) -> list[dict]:
    """Return the most recent pipeline_runs rows (newest first)."""
    _apply_column_migrations(conn)
    rows = conn.execute(
        "SELECT * FROM pipeline_runs ORDER BY created_at DESC, id DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]


def count_approvals_by_status(conn: sqlite3.Connection, status: str) -> int:
    """Return how many approval rows currently match the given status."""
    _apply_column_migrations(conn)
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM approvals WHERE status = ?", (status,)
    ).fetchone()
    return int(row["n"]) if row is not None else 0


def get_pending_approvals(conn: sqlite3.Connection) -> list[dict]:
    """Return all approvals with status='pending', joined with their run topic."""
    _apply_column_migrations(conn)
    rows = conn.execute(
        """
        SELECT a.*, r.topic_title AS topic_title, r.topic_url AS topic_url,
               r.thumbnail_path AS thumbnail_path
          FROM approvals a
          LEFT JOIN pipeline_runs r ON r.id = a.pipeline_run_id
         WHERE a.status = 'pending'
         ORDER BY a.created_at ASC, a.id ASC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_settings_audit(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Return the most recent rows from the settings audit table."""
    rows = conn.execute(
        "SELECT * FROM settings ORDER BY updated_at DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]


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


def mark_retention_pruned(conn: sqlite3.Connection, run_id: int) -> None:
    """Stamp retention_pruned_at and NULL the artifact path columns."""
    _apply_column_migrations(conn)
    from datetime import datetime as _dt

    with conn:
        conn.execute(
            """
            UPDATE pipeline_runs
               SET retention_pruned_at = ?,
                   video_path          = NULL,
                   thumbnail_path      = NULL,
                   audio_path          = NULL
             WHERE id = ?
            """,
            (_dt.utcnow().isoformat(timespec="seconds"), run_id),
        )


def get_settings_value(
    conn: sqlite3.Connection, key: str, default: str = ""
) -> str:
    """Read a value from the settings key/value table."""
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    except sqlite3.Error:
        return default
    if row is None:
        return default
    v = row["value"] if "value" in row.keys() else None
    return v if v is not None else default


def set_settings_value(
    conn: sqlite3.Connection, key: str, value: str
) -> None:
    """Upsert a key/value row in the settings table."""
    from datetime import datetime as _dt

    with conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value      = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, _dt.utcnow().isoformat(timespec="seconds")),
        )


def get_runs_for_cost_report(
    conn: sqlite3.Connection, start_date: str, end_date: str
) -> list[dict]:
    """Return pipeline_runs rows created between start_date and end_date (inclusive).

    Dates are ISO ``YYYY-MM-DD`` strings.
    """
    _apply_column_migrations(conn)
    rows = conn.execute(
        """
        SELECT * FROM pipeline_runs
         WHERE date(created_at) >= date(?)
           AND date(created_at) <= date(?)
         ORDER BY created_at ASC, id ASC
        """,
        (start_date, end_date),
    ).fetchall()
    return [dict(r) for r in rows]


@contextmanager
def cursor(db_path: str) -> Iterator[sqlite3.Cursor]:
    conn = connect(db_path)
    try:
        yield conn.cursor()
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# meme_candidates helpers (v0 Reddit meme reposter)
# ---------------------------------------------------------------------------


def insert_meme_candidate(
    conn: sqlite3.Connection,
    candidate: dict,
    title_similarity_threshold: float = 0.8,
    lookback_days: int = 7,
) -> int:
    """Insert a MemeCandidate dict from meme_sources, return new id.

    Dedup layers:
      1. Exact (source, source_url) match — idempotent, any status.
      2. Title similarity (Jaccard >= 0.8) against recent candidates —
         catches the same meme reposted by different users or across
         subreddits. Only checks the last ``lookback_days`` of candidates
         in non-rejected statuses.

    Returns -1 when the candidate is a content duplicate (layer 2).
    """
    # Layer 1: exact URL match
    existing = conn.execute(
        "SELECT id FROM meme_candidates WHERE source=? AND source_url=? LIMIT 1",
        (candidate["source"], candidate["source_url"]),
    ).fetchone()
    if existing:
        return int(existing["id"])

    # Layer 2: title similarity against recent candidates
    import re as _re

    def _tokenize(text: str) -> set:
        return set(_re.findall(r"[a-z0-9]+", (text or "").lower()))

    new_tokens = _tokenize(candidate.get("title") or "")
    if new_tokens:
        recent = conn.execute(
            """
            SELECT id, title FROM meme_candidates
            WHERE status NOT IN ('rejected', 'rejected_creator_denied')
              AND created_at >= datetime('now', ?)
            ORDER BY id DESC
            """,
            (f"-{lookback_days} days",),
        ).fetchall()
        for row in recent:
            row_tokens = _tokenize(row["title"])
            if not row_tokens:
                continue
            inter = len(new_tokens & row_tokens)
            union = len(new_tokens | row_tokens)
            if union > 0 and (inter / union) >= title_similarity_threshold:
                return -1  # content duplicate

    import json as _json

    cur = conn.execute(
        """
        INSERT INTO meme_candidates (
            source, source_url, author_handle, title, media_url, media_type,
            engagement_json, published_at, status, audio_url, humor_score,
            relevance_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_review', ?, ?, ?)
        """,
        (
            candidate["source"],
            candidate["source_url"],
            candidate["author_handle"],
            candidate["title"],
            candidate["media_url"],
            candidate["media_type"],
            _json.dumps(candidate.get("engagement") or {}),
            candidate.get("published_at"),
            candidate.get("audio_url"),
            candidate.get("humor_score"),
            candidate.get("relevance_score"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_meme_candidate(conn: sqlite3.Connection, candidate_id: int) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM meme_candidates WHERE id=?", (candidate_id,)
    ).fetchone()
    return dict(row) if row else None


def update_meme_candidate(
    conn: sqlite3.Connection,
    candidate_id: int,
    **fields,
) -> None:
    """Update arbitrary fields on a meme_candidates row."""
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [candidate_id]
    with conn:
        conn.execute(f"UPDATE meme_candidates SET {cols} WHERE id=?", vals)


def is_meme_creator_denied(
    conn: sqlite3.Connection, handle: str, source: str
) -> bool:
    row = conn.execute(
        "SELECT 1 FROM meme_denylist WHERE handle=? AND source=? LIMIT 1",
        (handle, source),
    ).fetchone()
    return row is not None


def add_meme_creator_to_denylist(
    conn: sqlite3.Connection,
    handle: str,
    source: str,
    reason: str = "",
) -> None:
    with conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO meme_denylist (handle, source, reason)
            VALUES (?, ?, ?)
            """,
            (handle, source, reason),
        )
