"""Admin endpoints for tenant management.

PUT  /api/v1/admin/tenants/{tenant_id}/tier  — set tier override (DB only)
GET  /api/v1/admin/tenants/{tenant_id}       — get tenant info
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from cirisnode.db.pg_pool import get_pg_pool
from cirisnode.utils.rbac import require_role

logger = logging.getLogger(__name__)

admin_router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_role(["admin"]))],
)

VALID_TIERS = {"community", "pro", "enterprise"}

UPSERT_TIER_SQL = """
    INSERT INTO tenant_tiers (tenant_id, tier, updated_at)
    VALUES ($1, $2, now())
    ON CONFLICT (tenant_id)
    DO UPDATE SET tier = EXCLUDED.tier,
                  updated_at = now()
    RETURNING tier
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
        logger.info("tenant_tier_read", extra={"tenant_id": tenant_id, "tier": "community", "found": False})
        return TenantTierResponse(tenant_id=tenant_id, tier="community")

    logger.info("tenant_tier_read", extra={"tenant_id": tenant_id, "tier": row["tier"], "found": True})
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

    Updates the ``tenant_tiers`` table (DB only — no Stripe calls).
    Stripe is managed exclusively by Portal API.
    """
    if body.tier not in VALID_TIERS:
        raise HTTPException(
            status_code=422,
            detail=f"tier must be one of: {', '.join(sorted(VALID_TIERS))}",
        )

    # Read existing tier for logging
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT tier FROM tenant_tiers WHERE tenant_id = $1", tenant_id
        )

    # Upsert tier
    async with pool.acquire() as conn:
        row = await conn.fetchrow(UPSERT_TIER_SQL, tenant_id, body.tier)

    previous_tier = existing or "community"
    logger.info(
        "tenant_tier_set",
        extra={"tenant_id": tenant_id, "tier": body.tier, "previous_tier": previous_tier},
    )

    return TenantTierResponse(
        tenant_id=tenant_id,
        tier=body.tier,
    )
