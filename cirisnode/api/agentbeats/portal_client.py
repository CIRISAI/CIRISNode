"""Portal API client — fetches actor standing for quota enforcement.

CIRISNode delegates all billing/gating decisions to Portal API.
This client:
  1. Generates a service JWT (role: "service")
  2. Calls GET /api/v1/standing/{actor} on Portal API
  3. Caches results in memory (60s TTL)
  4. Returns a StandingResult with tier, standing, limit, window, resets_at

Error handling:
  - If Portal API is unreachable, returns standing="degraded"
  - Callers decide policy: quota checks deny (503), usage display shows cached data
"""

import logging
import time
from dataclasses import dataclass

import httpx
import jwt as pyjwt

from cirisnode.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StandingResult:
    """Actor standing from Portal API."""

    actor: str
    standing: str  # "good" | "suspended" | "payment_failed" | "degraded"
    tier: str  # "community" | "pro" | "enterprise"
    limit: int | None  # None = unlimited
    window: str | None  # "week" | "month" | None
    resets_at: str | None  # ISO datetime or None
    stripe_customer_id: str | None = None
    entity_type: str = "user"


class PortalClient:
    """Async client for Portal API standing checks with in-memory cache."""

    def __init__(
        self,
        base_url: str,
        jwt_secret: str,
        cache_ttl: int = 60,
        timeout: float = 10.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._jwt_secret = jwt_secret
        self._cache: dict[str, tuple[StandingResult, float]] = {}
        self._cache_ttl = cache_ttl
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        logger.info(
            "portal_client_initialized",
            extra={"base_url": self._base_url, "cache_ttl": cache_ttl},
        )

    def _get_client(self) -> httpx.AsyncClient:
        """Lazy-init the httpx client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout),
            )
        return self._client

    def _service_jwt(self) -> str:
        """Generate a short-lived service JWT for Portal API auth."""
        now = int(time.time())
        return pyjwt.encode(
            {
                "sub": "cirisnode-service",
                "role": "service",
                "iat": now,
                "exp": now + 3600,
            },
            self._jwt_secret,
            algorithm="HS256",
        )

    async def get_standing(self, actor: str) -> StandingResult:
        """Get actor standing, using cache if fresh."""
        # Check cache
        cached = self._cache.get(actor)
        if cached:
            result, ts = cached
            if time.time() - ts < self._cache_ttl:
                logger.debug(
                    "portal_standing_cache_hit",
                    extra={"actor": actor, "tier": result.tier},
                )
                return result

        # Call Portal API
        try:
            client = self._get_client()
            resp = await client.get(
                f"/api/v1/standing/{actor}",
                headers={"Authorization": f"Bearer {self._service_jwt()}"},
            )

            if resp.status_code == 200:
                data = resp.json()
                result = StandingResult(
                    actor=data["actor"],
                    standing=data["standing"],
                    tier=data["tier"],
                    limit=data.get("limit"),
                    window=data.get("window"),
                    resets_at=data.get("resets_at"),
                    stripe_customer_id=data.get("stripe_customer_id"),
                    entity_type=data.get("entity_type", "user"),
                )
                self._cache[actor] = (result, time.time())
                logger.info(
                    "portal_standing_fetched",
                    extra={
                        "actor": actor,
                        "tier": result.tier,
                        "standing": result.standing,
                    },
                )
                return result

            logger.error(
                "portal_standing_error",
                extra={"actor": actor, "status": resp.status_code, "body": resp.text[:200]},
            )

        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError) as e:
            logger.error(
                "portal_standing_unreachable",
                extra={"actor": actor, "error": str(e)},
            )

        # Return cached data if available (even if stale), otherwise degraded
        if cached:
            result, _ = cached
            logger.warning(
                "portal_standing_stale_cache",
                extra={"actor": actor, "tier": result.tier},
            )
            return StandingResult(
                actor=result.actor,
                standing="degraded",
                tier=result.tier,
                limit=result.limit,
                window=result.window,
                resets_at=result.resets_at,
                stripe_customer_id=result.stripe_customer_id,
                entity_type=result.entity_type,
            )

        # No cache at all — degraded with unknown tier
        return StandingResult(
            actor=actor,
            standing="degraded",
            tier="unknown",
            limit=None,
            window=None,
            resets_at=None,
        )

    def invalidate(self, actor: str) -> None:
        """Remove an actor from the cache (e.g., after tier change)."""
        self._cache.pop(actor, None)

    async def close(self) -> None:
        """Close the httpx client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Module-level singleton
_portal_client: PortalClient | None = None


def get_portal_client() -> PortalClient:
    """Get the Portal API client singleton."""
    global _portal_client
    if _portal_client is None:
        _portal_client = PortalClient(
            base_url=settings.EEE_BASE_URL,
            jwt_secret=settings.JWT_SECRET,
        )
    return _portal_client
