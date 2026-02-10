"""Tiered usage quota enforcement.

Subscription tiers:
  - community (free):   1 eval / week    (resets Monday 00:00 UTC)
  - pro ($399/mo):     100 evals / month  (resets 1st of month 00:00 UTC)
  - enterprise:        unlimited

Tier resolution:
  The ``tenant_tiers`` table in PostgreSQL stores the current tier per tenant.
  If a row doesn't exist the tenant is assumed to be community (free).
  Portal API writes to this table via CIRISNode admin endpoints when
  subscriptions change in Stripe.
"""

import logging
from datetime import datetime, timezone

from cirisnode.db.pg_pool import get_pg_pool

logger = logging.getLogger(__name__)


class QuotaDenied(Exception):
    """Raised when a tenant has exhausted their quota."""


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

TIERS = {
    "community": {"window": "week", "limit": 1},
    "pro": {"window": "month", "limit": 100},
    "enterprise": {"window": None, "limit": None},  # unlimited
}


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

TIER_SQL = """
    SELECT tier FROM tenant_tiers WHERE tenant_id = $1
"""

USAGE_WEEK_SQL = """
    SELECT count(*) FROM evaluations
    WHERE tenant_id = $1
      AND eval_type = 'client'
      AND created_at > $2
"""

USAGE_MONTH_SQL = """
    SELECT count(*) FROM evaluations
    WHERE tenant_id = $1
      AND eval_type = 'client'
      AND created_at > $2
"""


# ---------------------------------------------------------------------------
# Quota check
# ---------------------------------------------------------------------------


async def get_tenant_tier(actor: str) -> str:
    """Look up the subscription tier for *actor*.  Defaults to 'community'."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchval(TIER_SQL, actor)
    return row or "community"


def _week_start(now: datetime) -> datetime:
    """Monday 00:00 UTC of the current ISO week."""
    days = now.weekday()
    return (now.replace(hour=0, minute=0, second=0, microsecond=0)).__class__(
        now.year, now.month, now.day - days, tzinfo=timezone.utc
    )


def _month_start(now: datetime) -> datetime:
    """1st of the current month 00:00 UTC."""
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def get_usage_count(actor: str, tier: str) -> tuple[int, int | None, datetime]:
    """Return (current_count, limit, window_reset) for the actor's tier."""
    now = datetime.now(timezone.utc)
    tier_def = TIERS.get(tier, TIERS["community"])

    if tier_def["limit"] is None:
        return 0, None, now  # enterprise — unlimited

    pool = await get_pg_pool()
    if tier_def["window"] == "month":
        window_start = _month_start(now)
        sql = USAGE_MONTH_SQL
        # Next reset: 1st of next month
        if now.month == 12:
            reset = now.replace(year=now.year + 1, month=1, day=1,
                                hour=0, minute=0, second=0, microsecond=0)
        else:
            reset = now.replace(month=now.month + 1, day=1,
                                hour=0, minute=0, second=0, microsecond=0)
    else:
        window_start = _week_start(now)
        sql = USAGE_WEEK_SQL
        from datetime import timedelta
        reset = window_start + timedelta(days=7)

    async with pool.acquire() as conn:
        count = await conn.fetchval(sql, actor, window_start) or 0

    return count, tier_def["limit"], reset


async def check_quota(actor: str) -> None:
    """Raise ``QuotaDenied`` if the actor has exhausted their quota."""
    tier = await get_tenant_tier(actor)
    count, limit, reset = await get_usage_count(actor, tier)

    if limit is not None and count >= limit:
        tier_label = tier.capitalize()
        window = "month" if TIERS[tier]["window"] == "month" else "week"
        logger.warning(
            "quota_denied",
            extra={"actor": actor, "tier": tier, "usage": count, "limit": limit},
        )
        raise QuotaDenied(
            f"{tier_label} plan limit reached: {count}/{limit} evaluations this {window}. "
            f"Resets {reset.isoformat()}. Upgrade at https://ethicsengine.org/pricing"
        )

    logger.info(
        "quota_check_passed",
        extra={"actor": actor, "tier": tier, "usage": count, "limit": limit, "resets": reset.isoformat()},
    )
