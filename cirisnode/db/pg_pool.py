"""Async PostgreSQL connection pool for CIRISNode read path.

Provides a shared asyncpg pool for querying the evaluations table
that CIRISBench writes to. Read-only — no ORM needed.
"""

import logging
import re
from typing import Optional

import asyncpg

from cirisnode.config import settings

logger = logging.getLogger(__name__)


def _sanitize_db_url(url: str) -> str:
    """Mask password in database URL for safe logging."""
    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1****\2", url)

_pool: Optional[asyncpg.Pool] = None


async def get_pg_pool() -> asyncpg.Pool:
    """Get or create the shared asyncpg connection pool.

    Automatically recreates the pool if it was previously closed
    (e.g. after app lifespan shutdown in tests).
    """
    global _pool
    if _pool is None or _pool._closed:
        logger.info("Creating PostgreSQL connection pool: %s", _sanitize_db_url(settings.DATABASE_URL))
        _pool = await asyncpg.create_pool(
            settings.DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
    return _pool


async def close_pg_pool() -> None:
    """Close the connection pool (call on shutdown)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL connection pool closed")
