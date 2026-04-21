"""
Analytics tracking and performance reporting for social media content.

Stores data in SQLite for simplicity, provides detailed metrics and
revenue estimation.

Schema is ``channel_id``-scoped as of migration 2026-04-21_channel_id
(see :mod:`analytics.migrations._2026_04_21_channel_id`).

Phase A shim: methods that now accept ``channel_id`` warn when a
caller invokes them without it and default to ``"commoncreed"``. This
lets CommonCreed's existing call sites keep working while the AST
audit + caller migration completes. After one production week without
warnings, the defaults flip to required-keyword-only.
"""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Default CPM rates (USD). Phase-A compatibility — channels that supply
# their own CPM map via the channel profile (Unit 2b) override these.
_DEFAULT_CPM_RATES: Dict[str, float] = {
    "youtube": 4.50,
    "tiktok": 0.25,
    "instagram": 0.40,
    "twitter": 0.30,
    "default": 0.50,
}


def _warn_missing_channel_id(method: str) -> None:
    """Phase-A shim: log a WARNING when a caller forgot the channel_id kwarg.

    After one warning-free production week, the kwarg-default is removed
    and this helper is deleted. The warning text matches a documented
    grep target so operators can find stragglers.
    """
    logger.warning(
        "AnalyticsTracker.%s called without channel_id — "
        "defaulting to 'commoncreed'; this is likely a bug in multi-channel mode",
        method,
    )


class AnalyticsTracker:
    """Track and analyze performance metrics for social media posts."""

    def __init__(
        self,
        db_path: str = "./analytics.db",
        *,
        apply_migrations: bool = True,
    ):
        """Initialize the tracker.

        Args:
            db_path: Path to SQLite database file.
            apply_migrations: When True (default), run pending schema
                migrations before opening the main connection. Tests can
                pass ``False`` to inspect pre-migration state.
        """
        self.db_path = db_path

        if apply_migrations:
            # Run migrations on-disk before opening our connection so a
            # partial-prior-failure is resolved first. ``apply`` is
            # idempotent and no-ops when the DB doesn't exist yet.
            try:
                from .migrations._2026_04_21_channel_id import apply as apply_channel_id
                apply_channel_id(db_path)
            except Exception as exc:
                # Migration is intentionally loud — don't let tracker init
                # silently skip it. Re-raise so the operator sees it.
                logger.error("AnalyticsTracker migration failed: %s", exc)
                raise

        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        # Tolerate up to 30s of lock contention from concurrent writers.
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self._init_tables()
        logger.info("AnalyticsTracker initialized with database: %s", db_path)

    def _init_tables(self) -> None:
        """Initialize SQLite tables.

        On fresh DBs this creates the channel_id-scoped schema directly
        (no ALTER needed). On migrated DBs the migration has already
        done its work and these CREATE IF NOT EXISTS statements are
        no-ops.
        """
        cursor = self.conn.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                content_id TEXT NOT NULL,
                title TEXT,
                description TEXT,
                channel_id TEXT NOT NULL DEFAULT 'commoncreed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                posted_at TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS metrics (
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
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS revenue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                estimated_revenue REAL DEFAULT 0,
                views INTEGER DEFAULT 0,
                channel_id TEXT NOT NULL DEFAULT 'commoncreed',
                calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (post_id) REFERENCES posts(id)
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL DEFAULT 'commoncreed',
                url TEXT NOT NULL,
                normalized_title TEXT NOT NULL,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_id, url)
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_news_items_url "
            "ON news_items (url)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_news_items_channel_title "
            "ON news_items (channel_id, normalized_title)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_news_items_fetched_at "
            "ON news_items (fetched_at)"
        )

        # Schema-migrations sentinel — the migration module also creates
        # this; redundant-safe.
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id TEXT PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL
            )
            """
        )

        self.conn.commit()
        logger.debug("Database tables initialized")

    # ─── Posts ─────────────────────────────────────────────────────────────

    def log_post(
        self,
        platform: str,
        content_id: str,
        post_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        channel_id: Optional[str] = None,
    ) -> str:
        """Log a new social media post.

        Args:
            platform: Platform name (youtube, tiktok, instagram, twitter)
            content_id: ID from the platform
            post_id: Custom post ID (generated if not provided)
            metadata: Optional additional metadata
            channel_id: Which channel this post belongs to. Phase A shim:
                defaults to 'commoncreed' with a WARNING log when omitted.

        Returns:
            The post_id used
        """
        if channel_id is None:
            _warn_missing_channel_id("log_post")
            channel_id = "commoncreed"

        if not post_id:
            post_id = f"{platform}_{content_id}_{datetime.now().timestamp()}"

        cursor = self.conn.cursor()

        title = metadata.get("title", "") if metadata else ""
        description = metadata.get("description", "") if metadata else ""

        cursor.execute(
            """
            INSERT OR REPLACE INTO posts
                (id, platform, content_id, title, description, channel_id, posted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (post_id, platform, content_id, title, description, channel_id, datetime.now()),
        )

        self.conn.commit()
        logger.info("Logged post: %s (channel=%s)", post_id, channel_id)

        return post_id

    def update_metrics(
        self,
        post_id: str,
        views: int = 0,
        likes: int = 0,
        comments: int = 0,
        shares: int = 0,
        watch_time_minutes: float = 0,
        click_through_rate: float = 0,
    ) -> None:
        """Update metrics for a post.

        Metrics inherit their ``channel_id`` via the ``post_id`` join on
        ``posts``, so no explicit channel_id parameter is needed here.
        """
        cursor = self.conn.cursor()

        cursor.execute(
            """
            INSERT INTO metrics
                (post_id, views, likes, comments, shares,
                 watch_time_minutes, click_through_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post_id, views, likes, comments, shares,
                watch_time_minutes, click_through_rate,
            ),
        )

        self.conn.commit()
        logger.info("Updated metrics for post: %s", post_id)

    # ─── Reports ───────────────────────────────────────────────────────────

    def get_report(
        self,
        period: str = "week",
        *,
        channel_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Generate a performance report for a time period.

        Args:
            period: 'day', 'week', 'month', or 'all'.
            channel_id: Filter to one channel's posts. ``None`` means
                cross-channel aggregate (dashboards). Omitted without
                ``None`` is a Phase-A shim that warns and defaults to
                ``"commoncreed"``.
        """
        cursor = self.conn.cursor()

        now = datetime.now()
        if period == "day":
            cutoff = now - timedelta(days=1)
        elif period == "week":
            cutoff = now - timedelta(weeks=1)
        elif period == "month":
            cutoff = now - timedelta(days=30)
        else:  # all
            cutoff = datetime.min

        if channel_id is None:
            # Intentionally None = cross-channel aggregate.
            cursor.execute(
                """
                SELECT p.platform, COUNT(DISTINCT p.id) as post_count,
                       SUM(m.views) as total_views,
                       SUM(m.likes) as total_likes,
                       SUM(m.comments) as total_comments,
                       SUM(m.shares) as total_shares,
                       SUM(m.watch_time_minutes) as total_watch_time,
                       AVG(m.click_through_rate) as avg_ctr
                FROM posts p
                LEFT JOIN metrics m ON p.id = m.post_id
                WHERE p.posted_at > ?
                GROUP BY p.platform
                """,
                (cutoff,),
            )
        else:
            cursor.execute(
                """
                SELECT p.platform, COUNT(DISTINCT p.id) as post_count,
                       SUM(m.views) as total_views,
                       SUM(m.likes) as total_likes,
                       SUM(m.comments) as total_comments,
                       SUM(m.shares) as total_shares,
                       SUM(m.watch_time_minutes) as total_watch_time,
                       AVG(m.click_through_rate) as avg_ctr
                FROM posts p
                LEFT JOIN metrics m ON p.id = m.post_id
                WHERE p.posted_at > ? AND p.channel_id = ?
                GROUP BY p.platform
                """,
                (cutoff, channel_id),
            )

        rows = cursor.fetchall()

        report: Dict[str, Any] = {
            "period": period,
            "channel_id": channel_id,  # None means "all channels"
            "generated_at": datetime.now().isoformat(),
            "by_platform": {},
            "total_views": 0,
            "total_engagement": 0,
        }

        for row in rows:
            platform_data = {
                "posts": row["post_count"] or 0,
                "views": row["total_views"] or 0,
                "likes": row["total_likes"] or 0,
                "comments": row["total_comments"] or 0,
                "shares": row["total_shares"] or 0,
                "watch_time_minutes": row["total_watch_time"] or 0,
                "avg_ctr": row["avg_ctr"] or 0,
            }

            platform_data["engagement_rate"] = (
                (platform_data["likes"] + platform_data["comments"] + platform_data["shares"])
                / max(platform_data["views"], 1)
            ) * 100

            report["by_platform"][row["platform"]] = platform_data
            report["total_views"] += platform_data["views"]
            report["total_engagement"] += (
                platform_data["likes"]
                + platform_data["comments"]
                + platform_data["shares"]
            )

        logger.info(
            "Generated %s report (channel=%s)",
            period, channel_id if channel_id else "ALL",
        )
        return report

    def top_performing(
        self,
        n: int = 10,
        *,
        channel_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get the top-performing posts. ``channel_id=None`` is cross-channel."""
        cursor = self.conn.cursor()

        if channel_id is None:
            cursor.execute(
                """
                SELECT p.id, p.platform, p.title, p.description, p.channel_id,
                       MAX(m.views) as views,
                       MAX(m.likes) as likes,
                       MAX(m.comments) as comments,
                       MAX(m.shares) as shares
                FROM posts p
                LEFT JOIN metrics m ON p.id = m.post_id
                GROUP BY p.id
                ORDER BY views DESC, likes DESC
                LIMIT ?
                """,
                (n,),
            )
        else:
            cursor.execute(
                """
                SELECT p.id, p.platform, p.title, p.description, p.channel_id,
                       MAX(m.views) as views,
                       MAX(m.likes) as likes,
                       MAX(m.comments) as comments,
                       MAX(m.shares) as shares
                FROM posts p
                LEFT JOIN metrics m ON p.id = m.post_id
                WHERE p.channel_id = ?
                GROUP BY p.id
                ORDER BY views DESC, likes DESC
                LIMIT ?
                """,
                (channel_id, n),
            )

        rows = cursor.fetchall()

        top_posts = []
        for row in rows:
            engagement = (
                (row["likes"] or 0)
                + (row["comments"] or 0)
                + (row["shares"] or 0)
            )
            engagement_rate = (
                (engagement / max(row["views"] or 1, 1)) * 100
            )

            top_posts.append(
                {
                    "id": row["id"],
                    "platform": row["platform"],
                    "channel_id": row["channel_id"],
                    "title": row["title"],
                    "views": row["views"] or 0,
                    "likes": row["likes"] or 0,
                    "comments": row["comments"] or 0,
                    "shares": row["shares"] or 0,
                    "engagement_rate": engagement_rate,
                }
            )

        logger.info("Retrieved top %d performing posts", len(top_posts))
        return top_posts

    def revenue_estimate(
        self,
        views_by_platform: Optional[Dict[str, int]] = None,
        *,
        channel_id: Optional[str] = None,
        cpm_rates: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Estimate revenue from views across platforms.

        Args:
            views_by_platform: Dictionary with platform names and view counts.
                If None, uses latest metrics from the database (filtered by
                ``channel_id`` when provided).
            channel_id: When provided, restricts the DB-driven fallback to
                one channel. ``None`` aggregates across channels.
            cpm_rates: Per-platform CPM map. When omitted, falls back to
                :data:`_DEFAULT_CPM_RATES`. Unit 2b lands per-channel CPM
                via the channel profile.

        Returns:
            Dictionary with revenue estimates by platform and total.
        """
        cpm_rates = cpm_rates or _DEFAULT_CPM_RATES

        if not views_by_platform:
            cursor = self.conn.cursor()
            if channel_id is None:
                cursor.execute(
                    """
                    SELECT p.platform, SUM(m.views) as total_views
                    FROM posts p
                    LEFT JOIN metrics m ON p.id = m.post_id
                    GROUP BY p.platform
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT p.platform, SUM(m.views) as total_views
                    FROM posts p
                    LEFT JOIN metrics m ON p.id = m.post_id
                    WHERE p.channel_id = ?
                    GROUP BY p.platform
                    """,
                    (channel_id,),
                )
            rows = cursor.fetchall()
            views_by_platform = {row["platform"]: row["total_views"] or 0 for row in rows}

        estimates: Dict[str, Any] = {}
        total_revenue = 0.0

        for platform, views in views_by_platform.items():
            if views == 0:
                continue

            cpm = cpm_rates.get(platform, cpm_rates.get("default", 0.5))
            revenue = (views / 1000) * cpm

            estimates[platform] = {
                "views": views,
                "cpm": cpm,
                "estimated_revenue": round(revenue, 2),
            }

            total_revenue += revenue

        estimates["channel_id"] = channel_id
        estimates["total_estimated_revenue"] = round(total_revenue, 2)
        estimates["note"] = "CPM rates are estimates. Actual rates vary by region and content."

        logger.info(
            "Calculated revenue estimates: $%.2f (channel=%s)",
            total_revenue, channel_id if channel_id else "ALL",
        )
        return estimates

    # ─── Export ────────────────────────────────────────────────────────────

    def export_to_csv(
        self,
        output_path: str,
        period: str = "week",
    ) -> str:
        """Export report data to CSV. Does not filter by channel today —
        the ``channel_id`` column is included in the header so downstream
        consumers can filter."""
        cursor = self.conn.cursor()

        now = datetime.now()
        if period == "day":
            cutoff = now - timedelta(days=1)
        elif period == "week":
            cutoff = now - timedelta(weeks=1)
        elif period == "month":
            cutoff = now - timedelta(days=30)
        else:
            cutoff = datetime.min

        cursor.execute(
            """
            SELECT p.id, p.platform, p.channel_id, p.title, p.description,
                   MAX(m.timestamp) as last_updated,
                   MAX(m.views) as views,
                   MAX(m.likes) as likes,
                   MAX(m.comments) as comments,
                   MAX(m.shares) as shares
            FROM posts p
            LEFT JOIN metrics m ON p.id = m.post_id
            WHERE p.posted_at > ?
            GROUP BY p.id
            ORDER BY MAX(m.views) DESC
            """,
            (cutoff,),
        )

        rows = cursor.fetchall()

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            writer.writerow(
                [
                    "Post ID",
                    "Platform",
                    "Channel",
                    "Title",
                    "Description",
                    "Views",
                    "Likes",
                    "Comments",
                    "Shares",
                    "Last Updated",
                ]
            )

            for row in rows:
                writer.writerow(
                    [
                        row["id"],
                        row["platform"],
                        row["channel_id"],
                        row["title"],
                        row["description"],
                        row["views"] or 0,
                        row["likes"] or 0,
                        row["comments"] or 0,
                        row["shares"] or 0,
                        row["last_updated"],
                    ]
                )

        logger.info("Exported report to %s", output_path)
        return output_path

    # ─── News items / dedup ────────────────────────────────────────────────

    def is_duplicate_topic(
        self,
        url: str,
        title: str,
        window_days: int = 7,
        *,
        channel_id: Optional[str] = None,
    ) -> bool:
        """Return True if this URL or normalized title appeared within
        ``window_days`` *for this channel*. Default window 7 days
        (CommonCreed's current behavior). Vesper passes 180.

        Phase-A shim: callers that omit ``channel_id`` get a WARNING and
        are scoped to ``'commoncreed'``.
        """
        if channel_id is None:
            _warn_missing_channel_id("is_duplicate_topic")
            channel_id = "commoncreed"

        normalized = self._normalize_title(title)
        cutoff = datetime.now() - timedelta(days=window_days)
        row = self.conn.execute(
            """SELECT 1 FROM news_items
               WHERE channel_id = ?
                 AND (url = ? OR normalized_title = ?)
                 AND fetched_at >= ?
               LIMIT 1""",
            (channel_id, url, normalized, cutoff),
        ).fetchone()
        return row is not None

    def record_news_item(
        self,
        url: str,
        title: str,
        *,
        channel_id: Optional[str] = None,
    ) -> None:
        """Insert a news item; ignore if (channel_id, url) already present.

        Phase-A shim: callers that omit ``channel_id`` get a WARNING and
        are scoped to ``'commoncreed'``.
        """
        if channel_id is None:
            _warn_missing_channel_id("record_news_item")
            channel_id = "commoncreed"

        normalized = self._normalize_title(title)
        self.conn.execute(
            "INSERT OR IGNORE INTO news_items "
            "(channel_id, url, normalized_title) VALUES (?, ?, ?)",
            (channel_id, url, normalized),
        )
        self.conn.commit()

    @staticmethod
    def _normalize_title(title: str) -> str:
        import re
        return re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()
        logger.info("Database connection closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def main():
    """Example usage of AnalyticsTracker."""
    with AnalyticsTracker(db_path="./sample_analytics.db") as tracker:
        # Log some sample posts — pass channel_id explicitly now that
        # the schema is scoped.
        post1 = tracker.log_post(
            platform="youtube",
            content_id="dQw4w9WgXcQ",
            metadata={"title": "AI Tools for 2024", "description": "Exploring latest AI"},
            channel_id="commoncreed",
        )

        post2 = tracker.log_post(
            platform="tiktok",
            content_id="viral123",
            metadata={"title": "Quick AI Tips", "description": "30-second tips"},
            channel_id="commoncreed",
        )

        tracker.update_metrics(post1, views=5000, likes=250, comments=50, shares=100)
        tracker.update_metrics(post2, views=15000, likes=1200, comments=300, shares=500)

        print("\nWeek Report (CommonCreed):")
        report = tracker.get_report("week", channel_id="commoncreed")
        print(json.dumps(report, indent=2))

        print("\nTop Performing (all channels):")
        top = tracker.top_performing(5)
        for post in top:
            print(f"  [{post['channel_id']}] {post['title']}: {post['views']} views")

        print("\nRevenue Estimate (CommonCreed):")
        revenue = tracker.revenue_estimate(channel_id="commoncreed")
        print(f"  Total: ${revenue['total_estimated_revenue']}")

        csv_path = tracker.export_to_csv("./analytics_report.csv", period="week")
        print(f"\nExported to {csv_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
