"""Lightweight PostgreSQL migration runner for CIRISNode.

Tracks applied migrations in a ``schema_migrations`` table and runs any
pending ``.sql`` files from ``cirisnode/db/migrations/`` in filename order.

Usage:
  # From Python (called during FastAPI lifespan startup):
  await run_migrations(pool)

  # From CLI / entrypoint:
  python -m cirisnode.db.migrator
"""

import asyncio
import logging
import pathlib

import asyncpg

from cirisnode.config import settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = pathlib.Path(__file__).parent / "migrations"

ENSURE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version  VARCHAR(128) PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
"""

APPLIED_SQL = "SELECT version FROM schema_migrations ORDER BY version"

INSERT_SQL = "INSERT INTO schema_migrations (version) VALUES ($1)"


async def run_migrations(pool: asyncpg.Pool) -> int:
    """Apply pending SQL migrations. Returns count of applied migrations."""
    applied = 0

    async with pool.acquire() as conn:
        # Ensure tracking table exists
        await conn.execute(ENSURE_TABLE_SQL)

        # Get already-applied versions
        rows = await conn.fetch(APPLIED_SQL)
        applied_versions = {r["version"] for r in rows}

        # Discover migration files
        if not MIGRATIONS_DIR.is_dir():
            logger.info("No migrations directory at %s — skipping", MIGRATIONS_DIR)
            return 0

        migration_files = sorted(
            f for f in MIGRATIONS_DIR.iterdir()
            if f.suffix == ".sql" and f.stem not in applied_versions
        )

        if not migration_files:
            logger.info("All migrations up to date (%d applied)", len(applied_versions))
            return 0

        for mf in migration_files:
            version = mf.stem
            logger.info("Applying migration: %s", version)
            sql = mf.read_text()
            try:
                # Run the entire migration in a transaction
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(INSERT_SQL, version)
                applied += 1
                logger.info("Migration %s applied successfully", version)
            except Exception:
                logger.exception("Migration %s FAILED — stopping", version)
                break

    if applied:
        logger.info("Applied %d migration(s)", applied)
    return applied


async def _main() -> None:
    """CLI entrypoint: connect to DATABASE_URL and run migrations."""
    pool = await asyncpg.create_pool(settings.DATABASE_URL, min_size=1, max_size=2)
    try:
        count = await run_migrations(pool)
        print(f"Applied {count} migration(s)")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_main())
