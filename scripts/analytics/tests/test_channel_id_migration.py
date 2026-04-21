"""Tests for AnalyticsTracker ``channel_id`` migration + Phase-A shim.

Runs without pytest (plain unittest) so the laptop venv without pytest
can still exercise them. Sidecar/CI pytest discovers them naturally.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure ``scripts/`` is on the path so ``analytics.tracker`` resolves
# whether this is invoked as a script or via pytest from the repo root.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from analytics.tracker import AnalyticsTracker
from analytics.migrations._2026_04_21_channel_id import (
    MIGRATION_ID,
    apply as apply_migration,
)


def _make_legacy_db(path: str) -> None:
    """Create a populated pre-migration DB shape for regression testing."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE posts (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                content_id TEXT NOT NULL,
                title TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                posted_at TIMESTAMP
            );
            CREATE TABLE metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                views INTEGER DEFAULT 0,
                likes INTEGER DEFAULT 0,
                comments INTEGER DEFAULT 0,
                shares INTEGER DEFAULT 0,
                watch_time_minutes REAL DEFAULT 0,
                click_through_rate REAL DEFAULT 0,
                FOREIGN KEY (post_id) REFERENCES posts(id)
            );
            CREATE TABLE revenue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                estimated_revenue REAL DEFAULT 0,
                views INTEGER DEFAULT 0,
                calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (post_id) REFERENCES posts(id)
            );
            CREATE TABLE news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                normalized_title TEXT NOT NULL,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(url)
            );
            CREATE INDEX idx_news_items_normalized_title
                ON news_items (normalized_title);
            CREATE INDEX idx_news_items_fetched_at
                ON news_items (fetched_at);
            INSERT INTO posts (id, platform, content_id, title, description)
                VALUES ('p1', 'youtube', 'ytid1', 'Legacy title 1', 'desc 1'),
                       ('p2', 'tiktok',  'ttid1', 'Legacy title 2', 'desc 2');
            INSERT INTO news_items (url, normalized_title)
                VALUES ('https://ex.com/a', 'legacy topic a'),
                       ('https://ex.com/b', 'legacy topic b');
            """
        )
        conn.commit()
    finally:
        conn.close()


class MigrationOnPopulatedDBTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="analytics-mig-")
        self.db_path = os.path.join(self.tmp, "analytics.db")
        _make_legacy_db(self.db_path)

    def tearDown(self) -> None:
        for p in Path(self.tmp).iterdir():
            p.unlink()
        Path(self.tmp).rmdir()

    def test_migration_preserves_rows_and_adds_channel_id(self):
        applied, msg = apply_migration(self.db_path)
        self.assertTrue(applied, msg)

        conn = sqlite3.connect(self.db_path)
        try:
            post_rows = conn.execute(
                "SELECT id, channel_id FROM posts ORDER BY id"
            ).fetchall()
            self.assertEqual(len(post_rows), 2)
            self.assertEqual(post_rows[0][1], "commoncreed")  # default backfill
            self.assertEqual(post_rows[1][1], "commoncreed")

            news_rows = conn.execute(
                "SELECT channel_id, url, normalized_title FROM news_items ORDER BY url"
            ).fetchall()
            self.assertEqual(len(news_rows), 2)
            self.assertTrue(all(r[0] == "commoncreed" for r in news_rows))

            # channel_id columns exist on revenue too
            cols_revenue = {r[1] for r in conn.execute("PRAGMA table_info(revenue)")}
            self.assertIn("channel_id", cols_revenue)

            # sentinel recorded
            row = conn.execute(
                "SELECT id FROM schema_migrations WHERE id = ?", (MIGRATION_ID,)
            ).fetchone()
            self.assertIsNotNone(row)

            # news_items unique constraint is (channel_id, url), not (url)
            idx_list = conn.execute("PRAGMA index_list('news_items')").fetchall()
            unique_cols: list[list[str]] = []
            for idx in idx_list:
                if idx[2] == 1:  # unique
                    info = conn.execute(
                        f"PRAGMA index_info('{idx[1]}')"
                    ).fetchall()
                    unique_cols.append([c[2] for c in info])
            composite = any(
                "channel_id" in cols and "url" in cols for cols in unique_cols
            )
            self.assertTrue(composite, f"no composite unique found: {unique_cols}")

            # explicit url index preserved
            index_names = {i[1] for i in idx_list}
            self.assertIn("idx_news_items_url", index_names)

            # FK integrity holds
            fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(fk_violations, [])

            # WAL mode enabled
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0].lower()
            self.assertEqual(mode, "wal")
        finally:
            conn.close()

    def test_migration_is_idempotent(self):
        applied_first, _ = apply_migration(self.db_path)
        self.assertTrue(applied_first)

        applied_second, msg = apply_migration(self.db_path)
        self.assertFalse(applied_second, f"expected no-op, got: {msg}")
        self.assertIn("already applied", msg)

    def test_migration_backs_up_db_before_mutating(self):
        apply_migration(self.db_path)
        backups = [p for p in Path(self.tmp).iterdir() if p.name.startswith("analytics.db.bak-")]
        self.assertEqual(len(backups), 1, f"expected 1 backup, got: {backups}")
        self.assertGreater(backups[0].stat().st_size, 0)


class FreshDBPathTests(unittest.TestCase):
    """When ``AnalyticsTracker.__init__`` runs on a fresh DB, the
    migration no-ops and ``_init_tables`` builds the scoped schema
    directly."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="analytics-fresh-")
        self.db_path = os.path.join(self.tmp, "analytics.db")

    def tearDown(self) -> None:
        for p in Path(self.tmp).iterdir():
            p.unlink()
        Path(self.tmp).rmdir()

    def test_fresh_init_creates_scoped_schema(self):
        tracker = AnalyticsTracker(db_path=self.db_path)
        try:
            conn = tracker.conn
            cols_posts = {r[1] for r in conn.execute("PRAGMA table_info(posts)")}
            self.assertIn("channel_id", cols_posts)
            cols_news = {r[1] for r in conn.execute("PRAGMA table_info(news_items)")}
            self.assertIn("channel_id", cols_news)

            # Composite unique on fresh DB too
            idx_list = conn.execute("PRAGMA index_list('news_items')").fetchall()
            composite = any(
                "channel_id" in [c[2] for c in conn.execute(f"PRAGMA index_info('{idx[1]}')")]
                and "url" in [c[2] for c in conn.execute(f"PRAGMA index_info('{idx[1]}')")]
                for idx in idx_list if idx[2] == 1
            )
            self.assertTrue(composite)
        finally:
            tracker.close()


class ChannelScopedDedupTests(unittest.TestCase):
    """Cross-channel dedup isolation + same-channel dedup behavior."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="analytics-dedup-")
        self.db_path = os.path.join(self.tmp, "analytics.db")
        self.tracker = AnalyticsTracker(db_path=self.db_path)

    def tearDown(self) -> None:
        self.tracker.close()
        for p in Path(self.tmp).iterdir():
            p.unlink()
        Path(self.tmp).rmdir()

    def test_cross_channel_dedup_isolated(self):
        self.tracker.record_news_item(
            "https://ex.com/topic-x", "Topic X", channel_id="commoncreed"
        )
        # Same URL, different channel — should NOT dedup.
        self.assertFalse(
            self.tracker.is_duplicate_topic(
                "https://ex.com/topic-x", "Topic X",
                window_days=180, channel_id="vesper",
            ),
            "vesper should not see commoncreed's dedup history",
        )

    def test_same_channel_dedup_matches(self):
        self.tracker.record_news_item(
            "https://ex.com/topic-y", "Topic Y", channel_id="commoncreed"
        )
        self.assertTrue(
            self.tracker.is_duplicate_topic(
                "https://ex.com/topic-y", "Topic Y",
                window_days=7, channel_id="commoncreed",
            )
        )

    def test_same_url_in_two_channels_coexists(self):
        self.tracker.record_news_item(
            "https://ex.com/topic-z", "Topic Z", channel_id="commoncreed"
        )
        # Same URL can be recorded in another channel — unique is composite.
        self.tracker.record_news_item(
            "https://ex.com/topic-z", "Topic Z", channel_id="vesper"
        )
        rows = self.tracker.conn.execute(
            "SELECT channel_id FROM news_items WHERE url = ?",
            ("https://ex.com/topic-z",),
        ).fetchall()
        self.assertEqual(
            {r[0] for r in rows}, {"commoncreed", "vesper"},
            "expected both channels to have the row",
        )


class PhaseAShimTests(unittest.TestCase):
    """Missing ``channel_id`` kwarg warns + defaults to 'commoncreed'."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="analytics-shim-")
        self.db_path = os.path.join(self.tmp, "analytics.db")
        self.tracker = AnalyticsTracker(db_path=self.db_path)

    def tearDown(self) -> None:
        self.tracker.close()
        for p in Path(self.tmp).iterdir():
            p.unlink()
        Path(self.tmp).rmdir()

    def test_log_post_without_channel_id_warns(self):
        with self.assertLogs("analytics.tracker", level="WARNING") as captured:
            self.tracker.log_post(
                platform="youtube",
                content_id="legacy123",
                metadata={"title": "Legacy post"},
            )
        messages = "\n".join(captured.output)
        self.assertIn("log_post called without channel_id", messages)

    def test_is_duplicate_topic_without_channel_id_warns_but_works(self):
        self.tracker.record_news_item("https://ex.com/a", "A", channel_id="commoncreed")
        with self.assertLogs("analytics.tracker", level="WARNING") as captured:
            dup = self.tracker.is_duplicate_topic("https://ex.com/a", "A")
        self.assertTrue(dup, "legacy caller should still see the dedup hit")
        self.assertIn("is_duplicate_topic called without channel_id", "\n".join(captured.output))

    def test_record_news_item_without_channel_id_warns_but_works(self):
        with self.assertLogs("analytics.tracker", level="WARNING") as captured:
            self.tracker.record_news_item("https://ex.com/b", "B")
        messages = "\n".join(captured.output)
        self.assertIn("record_news_item called without channel_id", messages)

        # Row landed under 'commoncreed'
        row = self.tracker.conn.execute(
            "SELECT channel_id FROM news_items WHERE url = ?",
            ("https://ex.com/b",),
        ).fetchone()
        self.assertEqual(row[0], "commoncreed")


class CommonCreedRegressionTests(unittest.TestCase):
    """news_sourcer pattern (positional args, no channel_id) still works."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="analytics-regress-")
        self.db_path = os.path.join(self.tmp, "analytics.db")
        self.tracker = AnalyticsTracker(db_path=self.db_path)

    def tearDown(self) -> None:
        self.tracker.close()
        for p in Path(self.tmp).iterdir():
            p.unlink()
        Path(self.tmp).rmdir()

    def test_news_sourcer_pattern_still_works(self):
        """Mirrors scripts/news_sourcing/news_sourcer.py lines 60 + 86."""
        # Pre-emptively silence the Phase-A warnings so the test output stays quiet.
        logging.getLogger("analytics.tracker").setLevel(logging.ERROR)

        url = "https://example.com/ai-news"
        title = "AI News Today"

        # Line 60 pattern: is_duplicate_topic(item["url"], item["title"])
        self.assertFalse(self.tracker.is_duplicate_topic(url, title))

        # Line 86 pattern: record_news_item(item["url"], item["title"])
        self.tracker.record_news_item(url, title)

        # Second call should dedup
        self.assertTrue(self.tracker.is_duplicate_topic(url, title))


if __name__ == "__main__":
    unittest.main(verbosity=2)
