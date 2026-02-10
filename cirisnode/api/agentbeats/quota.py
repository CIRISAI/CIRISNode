"""Tiered usage quota enforcement — delegated to Portal API.

CIRISNode no longer decides tiers locally. All billing/gating logic is
owned by Portal API + Stripe. CIRISNode only:
  1. Asks Portal API for actor standing (tier, limit, window)
  2. Counts evaluations locally from the evaluations table
  3. Compares count vs limit

Subscription tiers (defined in Portal API):
  - community (free):   1 eval / week    (resets Monday 00:00 UTC)
  - pro ($399/mo):     100 evals / month  (resets 1st of month 00:00 UTC)
  - enterprise:        unlimited
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from cirisnode.api.agentbeats.portal_client import StandingResult, get_portal_client
from cirisnode.db.pg_pool import get_pg_pool

logger = logging.getLogger(__name__)


class QuotaDenied(Exception):
    """Raised when a tenant has exhausted their quota."""


# ---------------------------------------------------------------------------
# SQL — local eval counting (CIRISNode owns this data)
# ---------------------------------------------------------------------------

USAGE_SQL = """
    SELECT count(*) FROM evaluations
    WHERE tenant_id = $1
      AND eval_type = 'client'
      AND created_at > $2
"""


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------


def _week_start(now: datetime) -> datetime:
    """Monday 00:00 UTC of the current ISO week."""
    days = now.weekday()
    return (now.replace(hour=0, minute=0, second=0, microsecond=0)).__class__(
        now.year, now.month, now.day - days, tzinfo=timezone.utc
    )


def _month_start(now: datetime) -> datetime:
    """1st of the current month 00:00 UTC."""
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Local eval count
# ---------------------------------------------------------------------------


async def count_evals_in_window(actor: str, window: str | None) -> int:
    """Count evaluations for the actor in the current usage window."""
    if window is None:
        return 0  # unlimited (enterprise)

    now = datetime.now(timezone.utc)
    if window == "month":
        window_start = _month_start(now)
    else:
        window_start = _week_start(now)

    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(USAGE_SQL, actor, window_start) or 0

    return count


# ---------------------------------------------------------------------------
# Quota check — delegates to Portal API
# ---------------------------------------------------------------------------


async def check_quota(actor: str) -> None:
    """Check quota via Portal API standing. Raise QuotaDenied if exhausted."""
    standing = await get_portal_client().get_standing(actor)

    # Portal API unreachable — deny benchmark runs (503)
    if standing.standing == "degraded":
        raise HTTPException(
            status_code=503,
            detail="Billing service temporarily unavailable. Please try again shortly.",
        )

    # Account not in good standing
    if standing.standing != "good":
        raise QuotaDenied(
            f"Account standing: {standing.standing}. "
            "Please check your subscription at https://ethicsengine.org/pricing"
        )

    # Unlimited tier (enterprise)
    if standing.limit is None:
        logger.info(
            "quota_check_passed",
            extra={"actor": actor, "tier": standing.tier, "usage": 0, "limit": None},
        )
        return

    # Count local evals and check against Portal-provided limit
    count = await count_evals_in_window(actor, standing.window)

    if count >= standing.limit:
        tier_label = standing.tier.capitalize()
        window = standing.window or "week"
        resets = standing.resets_at or ""
        logger.warning(
            "quota_denied",
            extra={"actor": actor, "tier": standing.tier, "usage": count, "limit": standing.limit},
        )
        raise QuotaDenied(
            f"{tier_label} plan limit reached: {count}/{standing.limit} evaluations this {window}. "
            f"Resets {resets}. Upgrade at https://ethicsengine.org/pricing"
        )

    logger.info(
        "quota_check_passed",
        extra={
            "actor": actor,
            "tier": standing.tier,
            "usage": count,
            "limit": standing.limit,
            "resets": standing.resets_at,
        },
    )
