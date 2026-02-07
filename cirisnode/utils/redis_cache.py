"""Redis cache layer for CIRISNode score/evaluation serving.

Replaces in-memory lru_cache for distributed caching with TTL.
Keys are prefixed with 'cache:' and shared with CIRISBench for
direct invalidation (Bench DELETEs keys on eval completion).
"""

import json
import logging
from typing import Any, Optional

import redis.asyncio as aioredis

from cirisnode.config import settings

logger = logging.getLogger(__name__)

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """Get or create the shared async Redis client."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Close the Redis client (call on shutdown)."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def cache_get(key: str) -> Optional[Any]:
    """Get a cached value by key. Returns None on miss."""
    try:
        r = await get_redis()
        data = await r.get(f"cache:{key}")
        if data is not None:
            return json.loads(data)
    except Exception as e:
        logger.debug("Cache miss (error): %s — %s", key, e)
    return None


async def cache_set(key: str, value: Any, ttl: int = 300) -> None:
    """Set a cached value with TTL in seconds."""
    try:
        r = await get_redis()
        await r.set(f"cache:{key}", json.dumps(value, default=str), ex=ttl)
    except Exception as e:
        logger.debug("Cache set failed (non-fatal): %s — %s", key, e)
