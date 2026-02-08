"""Billing proxy — CIRISNode gateway to Engine /billing endpoints.

GET  /api/v1/billing/plans     — Public tier/plan definitions (no auth)
POST /api/v1/billing/checkout  — Get Stripe Checkout URL (auth required)
GET  /api/v1/billing/portal    — Get Stripe Customer Portal URL (auth required)
POST /api/v1/billing/webhook   — Stripe webhook (forwarded raw to Engine)
"""

import logging
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from cirisnode.api.agentbeats.auth import resolve_actor
from cirisnode.api.agentbeats.quota import TIERS
from cirisnode.config import settings

logger = logging.getLogger(__name__)

billing_router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


def _engine_base_url() -> str:
    return settings.EEE_BASE_URL.rstrip("/")


def _service_jwt() -> str:
    import jwt as pyjwt
    now = int(time.time())
    return pyjwt.encode(
        {"sub": "cirisnode-service", "iat": now, "exp": now + 3600},
        settings.JWT_SECRET,
        algorithm="HS256",
    )


_PLAN_PRICES = {
    "community": {"amount": 0, "formatted": "Free"},
    "pro": {"amount": 39900, "formatted": "$399/mo"},
    "enterprise": {"amount": None, "formatted": "Custom"},
}


@billing_router.get("/plans")
async def list_plans():
    """Return available subscription plans (public, no auth required)."""
    plans = []
    for name, tier_def in TIERS.items():
        price = _PLAN_PRICES.get(name, {"amount": None, "formatted": "Contact us"})
        plans.append({
            "id": name,
            "name": name.capitalize(),
            "price": price["formatted"],
            "price_cents": price["amount"],
            "limit": tier_def["limit"],
            "window": tier_def["window"],
            "features": _plan_features(name),
        })
    return {"plans": plans}


def _plan_features(plan: str) -> list[str]:
    """Return feature list per plan for display."""
    base = ["HE-300 benchmark access", "Public leaderboard"]
    if plan == "community":
        return base + ["1 evaluation per week", "Community support"]
    if plan == "pro":
        return base + [
            "100 evaluations per month",
            "Private evaluation results",
            "Priority support",
            "API access",
        ]
    return base + [
        "Unlimited evaluations",
        "Private evaluation results",
        "Dedicated support",
        "Custom integrations",
        "SLA guarantee",
    ]


@billing_router.post("/checkout")
async def proxy_checkout(
    request: Request,
    actor: str = Depends(resolve_actor),
):
    """Proxy checkout session creation to Engine."""
    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
            resp = await client.post(
                f"{_engine_base_url()}/billing/checkout",
                content=body,
                headers={
                    "Authorization": f"Bearer {_service_jwt()}",
                    "Content-Type": "application/json",
                    "X-Tenant-Id": actor,
                },
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Billing service unavailable")

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    return resp.json()


@billing_router.get("/portal")
async def proxy_portal(
    actor: str = Depends(resolve_actor),
):
    """Proxy customer portal session creation to Engine."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
            resp = await client.get(
                f"{_engine_base_url()}/billing/portal",
                headers={
                    "Authorization": f"Bearer {_service_jwt()}",
                    "X-Tenant-Id": actor,
                },
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Billing service unavailable")

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    return resp.json()


@billing_router.post("/webhook")
async def proxy_webhook(request: Request):
    """Forward Stripe webhook to Engine (no auth — signature verified by Engine)."""
    body = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
            resp = await client.post(
                f"{_engine_base_url()}/billing/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "stripe-signature": sig,
                },
            )
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Billing service unavailable")

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:500])
    return resp.json()
