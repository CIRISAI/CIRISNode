"""Stripe customer sync — auto-create customers on first benchmark.

When a user first runs a benchmark, we ensure they have a Stripe customer
record (source of truth) and a tenant_tiers row (quota enforcement).
"""

import asyncio
import logging

import stripe

from cirisnode.config import settings
from cirisnode.db.pg_pool import get_pg_pool

logger = logging.getLogger(__name__)

UPSERT_TIER_SQL = """
    INSERT INTO tenant_tiers (tenant_id, tier, stripe_customer_id, updated_at)
    VALUES ($1, $2, $3, now())
    ON CONFLICT (tenant_id)
    DO UPDATE SET stripe_customer_id = EXCLUDED.stripe_customer_id,
                  updated_at = now()
    RETURNING tier
"""


def _init_stripe() -> bool:
    """Initialise Stripe SDK.  Returns False if no API key configured."""
    if not settings.STRIPE_API_KEY:
        return False
    stripe.api_key = settings.STRIPE_API_KEY
    return True


async def _find_stripe_customer(email: str) -> dict | None:
    """Search Stripe for an existing customer by email."""
    try:
        result = await asyncio.to_thread(
            stripe.Customer.list, email=email, limit=1
        )
        if result.data:
            return result.data[0]
        return None
    except stripe.StripeError as e:
        logger.warning("stripe_customer_search_failed: %s", e)
        return None


async def _create_stripe_customer(email: str) -> dict | None:
    """Create a new Stripe customer with community tier metadata."""
    try:
        customer = await asyncio.to_thread(
            stripe.Customer.create,
            email=email,
            metadata={"tenant_id": email, "tier": "community"},
        )
        logger.info("stripe_customer_created: %s -> %s", email, customer.id)
        return customer
    except stripe.StripeError as e:
        logger.error("stripe_customer_create_failed: %s", e)
        return None


async def ensure_stripe_customer(tenant_id: str) -> str | None:
    """Get-or-create a Stripe customer for *tenant_id* (email).

    Also ensures a ``tenant_tiers`` row exists.
    Returns the stripe_customer_id, or None if Stripe is not configured.
    """
    if not _init_stripe():
        logger.debug("Stripe not configured — skipping customer sync")
        return None

    # Check if we already have a tenant_tiers row with stripe_customer_id
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT tier, stripe_customer_id FROM tenant_tiers WHERE tenant_id = $1",
            tenant_id,
        )

    if existing and existing["stripe_customer_id"]:
        return existing["stripe_customer_id"]

    # Search / create in Stripe
    customer = await _find_stripe_customer(tenant_id)
    if not customer:
        customer = await _create_stripe_customer(tenant_id)
    if not customer:
        return None  # Stripe unavailable — degrade gracefully

    stripe_id = customer["id"]

    # Upsert tenant_tiers (preserves existing tier if row exists)
    tier = (existing["tier"] if existing else None) or "community"
    async with pool.acquire() as conn:
        await conn.execute(UPSERT_TIER_SQL, tenant_id, tier, stripe_id)

    return stripe_id
