"""AgentBeats benchmark proxy — CIRISNode gateway to Engine.

POST  /api/v1/agentbeats/run     — validate auth + quota, proxy to Engine
GET   /api/v1/agentbeats/status   — proxy Engine agentbeats status

Security model (managed / node mode — AGENTBEATS_MODE unset):
  1. JWT auth required (validate_a2a_auth -> actor / tenant_id)
  2. Usage quota enforced BEFORE proxying (Community=1/week, Pro=100/month)
  3. Agent API keys in the spec are forwarded to Engine but never stored by Node

Standalone mode (AGENTBEATS_MODE=true):
  Auth and quota are bypassed at the CIRISNode layer.  The AgentBeats
  platform authenticates via AGENTBEATS_API_KEY directly to the Engine
  (which validates it via ENGINE_API_KEYS).  CIRISNode just proxies.
"""

import logging
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from cirisnode.api.agentbeats.auth import is_standalone, resolve_actor
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


async def _proxy_to_engine(
    payload: dict,
    actor: str,
    authorization: Optional[str] = None,
) -> dict:
    """POST payload to Engine /he300/agentbeats/run and return JSON response.

    In standalone mode, forwards the caller's original Authorization header
    (AGENTBEATS_API_KEY) so the Engine can validate it.  In managed mode,
    mints a service JWT.
    """
    engine_url = f"{_engine_base_url()}/he300/agentbeats/run"

    if is_standalone() and authorization:
        auth_header = authorization
    else:
        auth_header = f"Bearer {_service_jwt()}"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600)) as client:
            resp = await client.post(
                engine_url,
                json=payload,
                headers={
                    "Authorization": auth_header,
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
        logger.error("Engine returned %d: %s", resp.status_code, resp.text[:500])
        raise HTTPException(
            status_code=resp.status_code,
            detail="Benchmark engine error. Check server logs for details.",
        )

    return resp.json()


# ---------------------------------------------------------------------------
# POST /api/v1/agentbeats/run
# ---------------------------------------------------------------------------


@agentbeats_router.post("/run", response_model=AgentBeatsRunResponse)
async def run_agentbeats(
    request: AgentBeatsRunRequest = Body(...),
    actor: str = Depends(resolve_actor),
    authorization: Optional[str] = Header(None),
):
    """Run HE-300 benchmark — proxied to Engine.

    **Managed mode** (ethicsengine.org):
      1. JWT auth enforced via resolve_actor -> validate_a2a_auth
      2. Quota check (Community 1/week, Pro 100/month, Enterprise unlimited)
      3. Proxy with service JWT

    **Standalone mode** (AGENTBEATS_MODE=true):
      1. Auth/quota bypassed at Node layer
      2. Forwards original Authorization header to Engine
         (Engine validates via ENGINE_API_KEYS / AUTH_ENABLED)
    """
    if not is_standalone():
        try:
            await check_quota(actor)
        except QuotaDenied as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(exc),
            )

    payload = request.model_dump(mode="json", exclude_none=True)
    return await _proxy_to_engine(payload, actor, authorization)


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

    if is_standalone():
        data["mode"] = "standalone"
    else:
        data["mode"] = "managed"
        data["tiers"] = {
            "community": {"limit_per_week": 1, "price": "$0/mo"},
            "pro": {"limit_per_month": 100, "price": "$399/mo"},
            "enterprise": {"limit_per_month": None, "price": "Custom"},
        }
    return data
