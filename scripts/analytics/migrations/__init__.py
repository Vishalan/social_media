"""AnalyticsTracker schema migrations.

Each migration is a single module exposing:
  * ``MIGRATION_ID`` — stable string key recorded in ``schema_migrations``.
  * ``apply(db_path)`` — idempotent, atomic migration runner.

Migrations run in filename order. ``AnalyticsTracker.__init__`` invokes
the latest applicable migration on startup (idempotent no-op if already
applied).
"""
