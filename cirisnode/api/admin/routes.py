"""Admin endpoints for tenant management.

PUT  /api/v1/admin/tenants/{tenant_id}/tier  — set tier override + sync Stripe metadata
GET  /api/v1/admin/tenants/{tenant_id}       — get tenant info
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cirisnode.db.pg_pool import get_pg_pool
from cirisnode.utils.rbac import require_role
from cirisnode.services.stripe_sync import ensure_stripe_customer, _init_stripe

logger = logging.getLogger(__name__)

admin_router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_role(["admin"]))],
)

VALID_TIERS = {"community", "pro", "enterprise"}

UPSERT_TIER_SQL = """
    INSERT INTO tenant_tiers (tenant_id, tier, stripe_customer_id, updated_at)
    VALUES ($1, $2, $3, now())
    ON CONFLICT (tenant_id)
    DO UPDATE SET tier = EXCLUDED.tier,
                  stripe_customer_id = COALESCE(EXCLUDED.stripe_customer_id, tenant_tiers.stripe_customer_id),
                  updated_at = now()
    RETURNING tier, stripe_customer_id
"""

GET_TIER_SQL = """
    SELECT tenant_id, tier, stripe_customer_id, stripe_subscription_id, updated_at
    FROM tenant_tiers WHERE tenant_id = $1
"""


class SetTierRequest(BaseModel):
    tier: str


class TenantTierResponse(BaseModel):
    tenant_id: str
    tier: str
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    updated_at: Optional[str] = None


@admin_router.get("/tenants/{tenant_id}", response_model=TenantTierResponse)
async def get_tenant(tenant_id: str):
    """Get tenant tier info."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(GET_TIER_SQL, tenant_id)

    if not row:
        return TenantTierResponse(tenant_id=tenant_id, tier="community")

    return TenantTierResponse(
        tenant_id=row["tenant_id"],
        tier=row["tier"],
        stripe_customer_id=row["stripe_customer_id"],
        stripe_subscription_id=row["stripe_subscription_id"],
        updated_at=row["updated_at"].isoformat() if row["updated_at"] else None,
    )


@admin_router.put("/tenants/{tenant_id}/tier", response_model=TenantTierResponse)
async def set_tenant_tier(tenant_id: str, body: SetTierRequest):
    """Set tier override for a tenant.

    Updates the ``tenant_tiers`` table and syncs the tier to Stripe
    customer metadata (if Stripe is configured).
    """
    if body.tier not in VALID_TIERS:
        raise HTTPException(
            status_code=422,
            detail=f"tier must be one of: {', '.join(sorted(VALID_TIERS))}",
        )

    # Ensure Stripe customer exists (creates if needed)
    stripe_id = None
    try:
        stripe_id = await ensure_stripe_customer(tenant_id)
    except Exception as exc:
        logger.warning("Stripe customer sync failed: %s", exc)

    # Upsert tier
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(UPSERT_TIER_SQL, tenant_id, body.tier, stripe_id)

    # Sync tier to Stripe metadata
    final_stripe_id = row["stripe_customer_id"] if row else stripe_id
    if final_stripe_id and _init_stripe():
        try:
            import stripe
            await asyncio.to_thread(
                stripe.Customer.modify,
                final_stripe_id,
                metadata={"tier": body.tier},
            )
            logger.info(
                "Stripe metadata synced: %s -> tier=%s", final_stripe_id, body.tier
            )
        except Exception as exc:
            logger.warning("Stripe metadata sync failed: %s", exc)

    logger.info("tenant_tier_set: %s -> %s", tenant_id, body.tier)

    return TenantTierResponse(
        tenant_id=tenant_id,
        tier=body.tier,
        stripe_customer_id=final_stripe_id,
    )
