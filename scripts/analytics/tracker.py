"""
Analytics tracking and performance reporting for social media content.

Stores data in SQLite for simplicity, provides detailed metrics and revenue estimation.
"""

import csv
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AnalyticsTracker:
    """Track and analyze performance metrics for social media posts."""

    def __init__(self, db_path: str = "./analytics.db"):
        """
        Initialize the analytics tracker.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_tables()
        logger.info(f"AnalyticsTracker initialized with database: {db_path}")

    def _init_tables(self) -> None:
        """Initialize SQLite tables."""
        cursor = self.conn.cursor()

        # Posts table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                content_id TEXT NOT NULL,
                title TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                posted_at TIMESTAMP
            )
        """
        )

        # Metrics table
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

        # Revenue table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS revenue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                estimated_revenue REAL DEFAULT 0,
                views INTEGER DEFAULT 0,
                calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (post_id) REFERENCES posts(id)
            )
        """
        )

        # News items table (for deduplication)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                normalized_title TEXT NOT NULL,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(url)
            )
        """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_news_items_normalized_title "
            "ON news_items (normalized_title)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_news_items_fetched_at "
            "ON news_items (fetched_at)"
        )

        self.conn.commit()
        logger.debug("Database tables initialized")

    def log_post(
        self,
        platform: str,
        content_id: str,
        post_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Log a new social media post.

        Args:
            platform: Platform name (youtube, tiktok, instagram, twitter)
            content_id: ID from the platform
            post_id: Custom post ID (generated if not provided)
            metadata: Optional additional metadata

        Returns:
            The post_id used
        """
        if not post_id:
            post_id = f"{platform}_{content_id}_{datetime.now().timestamp()}"

        cursor = self.conn.cursor()

        title = metadata.get("title", "") if metadata else ""
        description = metadata.get("description", "") if metadata else ""

        cursor.execute(
            """
            INSERT OR REPLACE INTO posts (id, platform, content_id, title, description, posted_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (post_id, platform, content_id, title, description, datetime.now()),
        )

        self.conn.commit()
        logger.info(f"Logged post: {post_id}")

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
        """
        Update metrics for a post.

        Args:
            post_id: The post ID
            views: Number of views
            likes: Number of likes
            comments: Number of comments
            shares: Number of shares
            watch_time_minutes: Total watch time in minutes
            click_through_rate: CTR as decimal (0-1)
        """
        cursor = self.conn.cursor()

        cursor.execute(
            """
            INSERT INTO metrics
            (post_id, views, likes, comments, shares, watch_time_minutes, click_through_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                post_id,
                views,
                likes,
                comments,
                shares,
                watch_time_minutes,
                click_through_rate,
            ),
        )

        self.conn.commit()
        logger.info(f"Updated metrics for post: {post_id}")

    def get_report(self, period: str = "week") -> Dict[str, Any]:
        """
        Generate a performance report for a time period.

        Args:
            period: 'day', 'week', 'month', or 'all'

        Returns:
            Dictionary with aggregated metrics
        """
        cursor = self.conn.cursor()

        # Calculate date cutoff
        now = datetime.now()
        if period == "day":
            cutoff = now - timedelta(days=1)
        elif period == "week":
            cutoff = now - timedelta(weeks=1)
        elif period == "month":
            cutoff = now - timedelta(days=30)
        else:  # all
            cutoff = datetime.min

        # Get posts in period
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

        rows = cursor.fetchall()

        report = {
            "period": period,
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

        logger.info(f"Generated {period} report")
        return report

    def top_performing(self, n: int = 10) -> List[Dict[str, Any]]:
        """
        Get the top-performing posts.

        Args:
            n: Number of top posts to return

        Returns:
            List of top posts with metrics
        """
        cursor = self.conn.cursor()

        cursor.execute(
            """
            SELECT p.id, p.platform, p.title, p.description,
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
                    "title": row["title"],
                    "views": row["views"] or 0,
                    "likes": row["likes"] or 0,
                    "comments": row["comments"] or 0,
                    "shares": row["shares"] or 0,
                    "engagement_rate": engagement_rate,
                }
            )

        logger.info(f"Retrieved top {len(top_posts)} performing posts")
        return top_posts

    def revenue_estimate(
        self, views_by_platform: Optional[Dict[str, int]] = None
    ) -> Dict[str, Any]:
        """
        Estimate revenue from views across platforms.

        Uses typical CPM (cost per mille/1000 views) rates by platform.

        Args:
            views_by_platform: Dictionary with platform names and view counts.
                              If None, uses latest metrics from database.

        Returns:
            Dictionary with revenue estimates by platform and total
        """
        # Default CPM rates (in USD) - adjust based on niche and region
        CPM_RATES = {
            "youtube": 4.50,
            "tiktok": 0.25,
            "instagram": 0.40,
            "twitter": 0.30,
            "default": 0.50,
        }

        if not views_by_platform:
            # Get latest metrics from database
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT p.platform, SUM(m.views) as total_views
                FROM posts p
                LEFT JOIN metrics m ON p.id = m.post_id
                GROUP BY p.platform
            """
            )

            rows = cursor.fetchall()
            views_by_platform = {row["platform"]: row["total_views"] or 0 for row in rows}

        estimates = {}
        total_revenue = 0

        for platform, views in views_by_platform.items():
            if views == 0:
                continue

            cpm = CPM_RATES.get(platform, CPM_RATES["default"])
            revenue = (views / 1000) * cpm

            estimates[platform] = {
                "views": views,
                "cpm": cpm,
                "estimated_revenue": round(revenue, 2),
            }

            total_revenue += revenue

        estimates["total_estimated_revenue"] = round(total_revenue, 2)
        estimates["note"] = "CPM rates are estimates. Actual rates vary by region and content."

        logger.info(f"Calculated revenue estimates: ${total_revenue:.2f}")
        return estimates

    def export_to_csv(
        self, output_path: str, period: str = "week"
    ) -> str:
        """
        Export report data to CSV.

        Args:
            output_path: Path to save CSV file
            period: Report period ('day', 'week', 'month', 'all')

        Returns:
            Path to exported file
        """
        cursor = self.conn.cursor()

        # Calculate date cutoff
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
            SELECT p.id, p.platform, p.title, p.description,
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

            # Write header
            writer.writerow(
                [
                    "Post ID",
                    "Platform",
                    "Title",
                    "Description",
                    "Views",
                    "Likes",
                    "Comments",
                    "Shares",
                    "Last Updated",
                ]
            )

            # Write data
            for row in rows:
                writer.writerow(
                    [
                        row["id"],
                        row["platform"],
                        row["title"],
                        row["description"],
                        row["views"] or 0,
                        row["likes"] or 0,
                        row["comments"] or 0,
                        row["shares"] or 0,
                        row["last_updated"],
                    ]
                )

        logger.info(f"Exported report to {output_path}")
        return output_path

    def is_duplicate_topic(self, url: str, title: str, window_days: int = 7) -> bool:
        """Return True if this URL or normalized title appeared within window_days."""
        normalized = self._normalize_title(title)
        cutoff = datetime.now() - timedelta(days=window_days)
        row = self.conn.execute(
            """SELECT 1 FROM news_items
               WHERE (url = ? OR normalized_title = ?)
                 AND fetched_at >= ?
               LIMIT 1""",
            (url, normalized, cutoff),
        ).fetchone()
        return row is not None

    def record_news_item(self, url: str, title: str) -> None:
        """Insert a news item; ignore if URL already present."""
        normalized = self._normalize_title(title)
        self.conn.execute(
            "INSERT OR IGNORE INTO news_items (url, normalized_title) VALUES (?, ?)",
            (url, normalized),
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
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


def main():
    """Example usage of AnalyticsTracker."""
    with AnalyticsTracker(db_path="./sample_analytics.db") as tracker:
        # Log some sample posts
        post1 = tracker.log_post(
            platform="youtube",
            content_id="dQw4w9WgXcQ",
            metadata={"title": "AI Tools for 2024", "description": "Exploring latest AI"},
        )

        post2 = tracker.log_post(
            platform="tiktok",
            content_id="viral123",
            metadata={"title": "Quick AI Tips", "description": "30-second tips"},
        )

        # Update metrics
        tracker.update_metrics(post1, views=5000, likes=250, comments=50, shares=100)
        tracker.update_metrics(post2, views=15000, likes=1200, comments=300, shares=500)

        # Generate reports
        print("\nWeek Report:")
        report = tracker.get_report("week")
        print(json.dumps(report, indent=2))

        print("\nTop Performing:")
        top = tracker.top_performing(5)
        for post in top:
            print(f"  {post['title']}: {post['views']} views")

        print("\nRevenue Estimate:")
        revenue = tracker.revenue_estimate()
        print(f"  Total: ${revenue['total_estimated_revenue']}")

        # Export to CSV
        csv_path = tracker.export_to_csv("./analytics_report.csv", period="week")
        print(f"\nExported to {csv_path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
