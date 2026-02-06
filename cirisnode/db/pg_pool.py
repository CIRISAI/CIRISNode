"""Async PostgreSQL connection pool for CIRISNode read path.

Provides a shared asyncpg pool for querying the evaluations table
that CIRISBench writes to. Read-only — no ORM needed.
"""

import logging
from typing import Optional

import asyncpg

from cirisnode.config import settings

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def get_pg_pool() -> asyncpg.Pool:
    """Get or create the shared asyncpg connection pool."""
    global _pool
    if _pool is None:
        logger.info("Creating PostgreSQL connection pool: %s", settings.DATABASE_URL)
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
