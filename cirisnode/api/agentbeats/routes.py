"""AgentBeats benchmark — local HE-300 execution inside CIRISNode.

POST  /api/v1/agentbeats/run     — validate auth + quota, run benchmark locally
GET   /api/v1/agentbeats/status   — runner status

Security model (managed / node mode — AGENTBEATS_MODE unset):
  1. JWT auth required (validate_a2a_auth -> actor / tenant_id)
  2. Usage quota enforced BEFORE running (Community=1/week, Pro=100/month)
  3. Agent API keys in the spec are used during benchmark and discarded — never stored

Standalone mode (AGENTBEATS_MODE=true):
  Auth and quota are bypassed at the CIRISNode layer.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from cirisnode.api.agentbeats.auth import is_standalone, resolve_actor
from cirisnode.api.agentbeats.quota import check_quota, QuotaDenied
from cirisnode.benchmark.agent_spec import (
    AgentSpec,
    OpenAIProtocolConfig,
)
from cirisnode.benchmark.badges import compute_badges
from cirisnode.benchmark.loader import load_scenarios
from cirisnode.benchmark.runner import run_batch
from cirisnode.db.pg_pool import get_pg_pool

logger = logging.getLogger(__name__)

agentbeats_router = APIRouter(prefix="/api/v1/agentbeats", tags=["agentbeats"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class AgentBeatsRunRequest(BaseModel):
    """Request for POST /api/v1/agentbeats/run.

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
    semantic_evaluation: bool = False
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


def _extract_model_name(spec: AgentSpec) -> str:
    """Extract the model name from an AgentSpec."""
    if isinstance(spec.protocol_config, OpenAIProtocolConfig):
        return spec.protocol_config.model
    return spec.name


def _extract_provider(spec: AgentSpec) -> str:
    """Infer provider from the agent endpoint URL."""
    url = spec.url.lower()
    if "openai.com" in url:
        return "OpenAI"
    elif "anthropic.com" in url:
        return "Anthropic"
    elif "openrouter.ai" in url:
        return "OpenRouter"
    elif "together.xyz" in url or "together.ai" in url:
        return "Together"
    elif "groq.com" in url:
        return "Groq"
    elif "mistral.ai" in url:
        return "Mistral"
    elif "deepseek" in url:
        return "DeepSeek"
    elif spec.provider and spec.provider.organization:
        return spec.provider.organization
    return "Unknown"


INSERT_EVAL_SQL = """
    INSERT INTO evaluations (
        id, tenant_id, eval_type, target_model, target_provider,
        target_endpoint, protocol, agent_name, sample_size, seed,
        concurrency, status, accuracy, total_scenarios, correct,
        errors, categories, avg_latency_ms, processing_ms,
        scenario_results, trace_id, visibility, badges,
        created_at, started_at, completed_at, dataset_meta,
        token_usage
    ) VALUES (
        $1, $2, $3, $4, $5,
        $6, $7, $8, $9, $10,
        $11, $12, $13, $14, $15,
        $16, $17, $18, $19,
        $20, $21, $22, $23,
        $24, $25, $26, $27,
        $28
    )
"""


# ---------------------------------------------------------------------------
# POST /api/v1/agentbeats/run
# ---------------------------------------------------------------------------


@agentbeats_router.post("/run", response_model=AgentBeatsRunResponse)
async def run_agentbeats(
    request: AgentBeatsRunRequest = Body(...),
    actor: str = Depends(resolve_actor),
    authorization: Optional[str] = Header(None),
):
    """Run HE-300 benchmark locally.

    **Managed mode** (ethicsengine.org):
      1. JWT auth enforced via resolve_actor -> validate_a2a_auth
      2. Quota check (Community 1/week, Pro 100/month, Enterprise unlimited)
      3. Execute locally with heuristic classification

    **Standalone mode** (AGENTBEATS_MODE=true):
      1. Auth/quota bypassed at Node layer
    """
    # --- 1. Quota check ---
    if not is_standalone():
        try:
            await check_quota(actor)
        except QuotaDenied as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(exc),
            )

    # --- 2. Parse AgentSpec ---
    if not request.agent_spec:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="agent_spec is required",
        )

    try:
        agent_spec = AgentSpec(**request.agent_spec)
    except Exception as exc:
        logger.warning("Invalid agent_spec: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid agent_spec: {exc}",
        )

    # --- 3. Load scenarios ---
    seed = request.random_seed if request.random_seed is not None else int(uuid.uuid4().int % 2**31)
    scenarios, dataset_meta = load_scenarios(
        sample_size=request.sample_size,
        categories=request.categories,
        seed=seed,
    )
    dataset_meta_dict = dataset_meta.to_dict()

    if not scenarios:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No scenarios loaded. Check categories parameter.",
        )

    # --- 4. Execute batch ---
    batch_id = f"he300-{uuid.uuid4().hex[:8]}"
    logger.info(
        "Starting HE-300 batch %s: %d scenarios, concurrency=%d, protocol=%s, actor=%s",
        batch_id, len(scenarios), request.concurrency, agent_spec.protocol, actor,
    )

    batch_result = await run_batch(
        scenarios=scenarios,
        agent_spec=agent_spec,
        batch_id=batch_id,
        concurrency=request.concurrency,
        timeout_per_scenario=float(request.timeout_per_scenario),
        dataset_meta=dataset_meta_dict,
    )

    # --- 5. Compute badges (only for full HE-300 runs) ---
    badges = compute_badges(batch_result.accuracy, batch_result.categories) if request.sample_size >= 300 else []

    # --- 6. Store in DB ---
    model_name = _extract_model_name(agent_spec)
    provider_name = _extract_provider(agent_spec)
    eval_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                INSERT_EVAL_SQL,
                eval_id,                                # id
                actor,                                  # tenant_id
                "client",                               # eval_type
                model_name,                             # target_model
                provider_name,                          # target_provider
                agent_spec.url,                         # target_endpoint
                agent_spec.protocol,                    # protocol
                request.agent_name or agent_spec.name,  # agent_name
                request.sample_size,                    # sample_size
                seed,                                   # seed
                request.concurrency,                    # concurrency
                "completed",                            # status
                batch_result.accuracy,                  # accuracy
                batch_result.total,                     # total_scenarios
                batch_result.correct,                   # correct
                batch_result.errors,                    # errors
                json.dumps(batch_result.categories),    # categories (JSONB)
                batch_result.avg_latency_ms,            # avg_latency_ms
                int(batch_result.processing_time_ms),   # processing_ms
                json.dumps(batch_result.results),       # scenario_results (JSONB)
                batch_id,                               # trace_id
                "private",                              # visibility
                json.dumps(badges),                     # badges (JSONB)
                now,                                    # created_at
                now,                                    # started_at
                now,                                    # completed_at
                json.dumps(dataset_meta_dict),           # dataset_meta (JSONB)
                json.dumps(batch_result.token_usage) if batch_result.token_usage else None,  # token_usage
            )
        logger.info("Stored evaluation %s (visibility=private)", eval_id)
    except Exception:
        logger.exception("Failed to store evaluation %s — returning results anyway", eval_id)

    # --- 7. Return response ---
    return AgentBeatsRunResponse(
        batch_id=batch_id,
        agent_name=request.agent_name or agent_spec.name,
        model=model_name,
        accuracy=batch_result.accuracy,
        total_scenarios=batch_result.total,
        correct=batch_result.correct,
        errors=batch_result.errors,
        categories=batch_result.categories,
        avg_latency_ms=batch_result.avg_latency_ms,
        processing_time_ms=batch_result.processing_time_ms,
        concurrency_used=request.concurrency,
        protocol=agent_spec.protocol,
        semantic_evaluation=False,
        random_seed=seed,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/agentbeats/status
# ---------------------------------------------------------------------------


@agentbeats_router.get("/status")
async def agentbeats_status():
    """Return local runner status."""
    data: dict[str, Any] = {
        "parallel_runner_available": True,
        "engine": "local",
    }

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
