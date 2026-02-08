"""AgentBeats benchmark proxy — CIRISNode gateway to Engine.

POST  /api/v1/agentbeats/run     — validate auth + quota, proxy to Engine
GET   /api/v1/agentbeats/status   — proxy Engine agentbeats status

Security model:
  1. JWT auth required (validate_a2a_auth → actor / tenant_id)
  2. Usage quota enforced BEFORE proxying (Community=1/week, Pro=100/month)
  3. Agent API keys in the spec are forwarded to Engine but never stored by Node
"""

import logging
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field

from cirisnode.api.a2a.auth import validate_a2a_auth
from cirisnode.api.agentbeats.quota import check_quota, QuotaDenied
from cirisnode.config import settings

logger = logging.getLogger(__name__)

agentbeats_router = APIRouter(prefix="/api/v1/agentbeats", tags=["agentbeats"])


# ---------------------------------------------------------------------------
# Request / Response schemas (mirror Engine's AgentBeatsBenchmarkRequest)
# ---------------------------------------------------------------------------


class AgentBeatsRunRequest(BaseModel):
    """Request forwarded to Engine /he300/agentbeats/run.

    Accepts the full typed AgentSpec from the frontend.
    """
    agent_spec: Optional[dict[str, Any]] = None
    agent_url: Optional[str] = None
    agent_name: Optional[str] = None
    model: Optional[str] = None
    protocol: str = "a2a"
    concurrency: int = Field(default=50, ge=1, le=100)
    sample_size: int = Field(default=300, ge=1, le=300)
    categories: Optional[list[str]] = None
    random_seed: Optional[int] = None
    semantic_evaluation: bool = True
    timeout_per_scenario: int = Field(default=60, ge=5, le=300)
    api_key: Optional[str] = None
    verify_ssl: bool = True
    ca_cert_path: Optional[str] = None
    client_cert_path: Optional[str] = None
    client_key_path: Optional[str] = None
    evaluator_provider: Optional[str] = None
    evaluator_model: Optional[str] = None
    evaluator_api_key: Optional[str] = None
    evaluator_base_url: Optional[str] = None


class AgentBeatsRunResponse(BaseModel):
    batch_id: str
    agent_name: Optional[str] = None
    model: Optional[str] = None
    accuracy: float
    total_scenarios: int
    correct: int
    errors: int
    categories: dict[str, Any] = Field(default_factory=dict)
    avg_latency_ms: float
    processing_time_ms: float
    concurrency_used: int
    protocol: str
    semantic_evaluation: bool
    random_seed: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _engine_base_url() -> str:
    """Return Engine base URL (EEE_BASE_URL points at the Engine container)."""
    return settings.EEE_BASE_URL.rstrip("/")


def _service_jwt() -> str:
    """Create a short-lived service JWT for Engine auth."""
    import jwt as pyjwt

    now = int(time.time())
    return pyjwt.encode(
        {"sub": "cirisnode-service", "iat": now, "exp": now + 3600},
        settings.JWT_SECRET,
        algorithm="HS256",
    )


# ---------------------------------------------------------------------------
# POST /api/v1/agentbeats/run
# ---------------------------------------------------------------------------


@agentbeats_router.post("/run", response_model=AgentBeatsRunResponse)
async def run_agentbeats(
    request: AgentBeatsRunRequest = Body(...),
    actor: str = Depends(validate_a2a_auth),
):
    """Run HE-300 benchmark — auth + quota gated, proxied to Engine.

    1. Validate JWT → actor (tenant_id)
    2. Check quota (Community 1/week, Pro 100/month, Enterprise unlimited)
    3. Forward full request to Engine /he300/agentbeats/run
    4. Return Engine response to frontend
    """
    # --- quota gate ---
    try:
        await check_quota(actor)
    except QuotaDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        )

    # --- proxy to Engine ---
    engine_url = f"{_engine_base_url()}/he300/agentbeats/run"
    payload = request.model_dump(mode="json", exclude_none=True)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600)) as client:
            resp = await client.post(
                engine_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {_service_jwt()}",
                    "Content-Type": "application/json",
                    "X-Tenant-Id": actor,
                },
            )
    except httpx.ConnectError:
        logger.error("Engine connection refused at %s", engine_url)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Benchmark engine is unavailable. Please try again later.",
        )
    except httpx.TimeoutException:
        logger.error("Engine request timed out at %s", engine_url)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Benchmark timed out. Try reducing concurrency or sample size.",
        )

    if resp.status_code != 200:
        detail = resp.text[:500]
        logger.error("Engine returned %d: %s", resp.status_code, detail)
        raise HTTPException(status_code=resp.status_code, detail=detail)

    return resp.json()


# ---------------------------------------------------------------------------
# GET /api/v1/agentbeats/status
# ---------------------------------------------------------------------------


@agentbeats_router.get("/status")
async def agentbeats_status():
    """Proxy Engine agentbeats status + add Node-level tier info."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as client:
            resp = await client.get(
                f"{_engine_base_url()}/he300/agentbeats/status",
                headers={"Authorization": f"Bearer {_service_jwt()}"},
            )
            if resp.status_code == 200:
                data = resp.json()
            else:
                data = {"parallel_runner_available": False, "error": resp.text[:200]}
    except Exception as exc:
        data = {"parallel_runner_available": False, "error": str(exc)}

    data["tiers"] = {
        "community": {"limit_per_week": 1, "price": "$0/mo"},
        "pro": {"limit_per_month": 100, "price": "$399/mo"},
        "enterprise": {"limit_per_month": None, "price": "Custom"},
    }
    return data
