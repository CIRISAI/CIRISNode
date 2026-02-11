"""Frontier model registry + sweep management endpoints.

POST   /api/v1/admin/frontier-models           — register a model
GET    /api/v1/admin/frontier-models           — list registered models
DELETE /api/v1/admin/frontier-models/{model_id} — remove a model

POST   /api/v1/admin/frontier-sweep            — launch sweep
GET    /api/v1/admin/frontier-sweep/{sweep_id}  — sweep progress
GET    /api/v1/admin/frontier-sweep/{sweep_id}/stream — SSE status stream
POST   /api/v1/admin/frontier-sweep/{sweep_id}/pause  — pause sweep
POST   /api/v1/admin/frontier-sweep/{sweep_id}/resume — resume sweep
POST   /api/v1/admin/frontier-sweep/{sweep_id}/cancel — cancel sweep
GET    /api/v1/admin/frontier-sweeps            — list recent sweeps

All endpoints require admin JWT (role='admin').
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from cirisnode.benchmark.agent_spec import (
    AgentSpec,
    AnthropicProtocolConfig,
    ApiKeyAuth,
    BearerAuth,
    GeminiProtocolConfig,
    OpenAIProtocolConfig,
)
from cirisnode.benchmark.badges import compute_badges
from cirisnode.benchmark.loader import load_scenarios
from cirisnode.benchmark.runner import BENCHMARK_SYSTEM_PROMPT, SemanticEvalConfig, run_batch
from cirisnode.config import settings
from cirisnode.db.pg_pool import get_pg_pool
from cirisnode.utils.log_buffer import get_log_buffer
from cirisnode.utils.rbac import require_role
from cirisnode.utils.redis_cache import cache_set, get_redis

logger = logging.getLogger(__name__)

frontier_router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin-frontier"],
    dependencies=[Depends(require_role(["admin"]))],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_api_keys() -> Dict[str, str]:
    """Parse FRONTIER_API_KEYS env var into {provider_lower: key}."""
    try:
        raw = json.loads(settings.FRONTIER_API_KEYS)
        return {k.lower(): v for k, v in raw.items()}
    except (json.JSONDecodeError, AttributeError):
        return {}


# ---------------------------------------------------------------------------
# Sweep control state (in-memory, per-process)
# ---------------------------------------------------------------------------

# Per-provider concurrency limit: 1 model at a time per provider
PROVIDER_CONCURRENCY = 1
# Max total parallel model runs across all providers
GLOBAL_CONCURRENCY = 3

# Map model providers to API key provider names when they differ
KEY_PROVIDER_ALIASES: Dict[str, str] = {
    "xai": "grok",          # xAI models use the "grok" API key
    "meta": "openrouter",    # Meta/Llama models route through OpenRouter
    "deepseek": "openrouter", # DeepSeek via OpenRouter
    "mistral": "openrouter",  # Mistral via OpenRouter
    "cohere": "openrouter",   # Cohere via OpenRouter
}

# Providers that use native APIs (not OpenAI-compatible)
ANTHROPIC_PROVIDERS = frozenset({"anthropic"})
GEMINI_PROVIDERS = frozenset({"google"})

# {sweep_id: {"status": "running"|"paused"|"cancelled"}}
_sweep_controls: Dict[str, Dict[str, str]] = {}


def _get_sweep_control(sweep_id: str) -> str:
    """Get control status for a sweep. Returns 'running' if not tracked."""
    return _sweep_controls.get(sweep_id, {}).get("status", "running")


# In-memory INSERT SQL (matches agentbeats INSERT_EVAL_SQL)
INSERT_EVAL_SQL = """
    INSERT INTO evaluations (
        id, tenant_id, eval_type, target_model, target_provider,
        target_endpoint, protocol, agent_name, sample_size, seed,
        concurrency, status, accuracy, total_scenarios, correct,
        errors, categories, avg_latency_ms, processing_ms,
        scenario_results, trace_id, visibility, badges,
        created_at, started_at, completed_at, dataset_meta
    ) VALUES (
        $1, $2, $3, $4, $5,
        $6, $7, $8, $9, $10,
        $11, $12, $13, $14, $15,
        $16, $17, $18, $19,
        $20, $21, $22, $23,
        $24, $25, $26, $27
    )
"""

UPDATE_EVAL_COMPLETED_SQL = """
    UPDATE evaluations SET
        status = 'completed',
        accuracy = $2,
        total_scenarios = $3,
        correct = $4,
        errors = $5,
        categories = $6,
        avg_latency_ms = $7,
        processing_ms = $8,
        scenario_results = $9,
        badges = $10,
        completed_at = $11,
        dataset_meta = $12
    WHERE id = $1
"""

UPDATE_EVAL_FAILED_SQL = """
    UPDATE evaluations SET
        status = 'failed',
        scenario_results = $2,
        completed_at = $3
    WHERE id = $1
"""

UPDATE_EVAL_RUNNING_SQL = """
    UPDATE evaluations SET status = 'running', started_at = $2 WHERE id = $1
"""


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class FrontierKeyInfo(BaseModel):
    provider: str
    key_preview: str
    key_length: int


@frontier_router.get("/frontier-keys", response_model=List[FrontierKeyInfo])
async def list_frontier_keys():
    """List configured frontier API key providers with masked previews."""
    api_keys = _load_api_keys()
    result = []
    for provider, key in sorted(api_keys.items()):
        preview = f"{key[:4]}...{key[-4:]}" if len(key) >= 8 else "****"
        result.append(FrontierKeyInfo(provider=provider, key_preview=preview, key_length=len(key)))
    return result


@frontier_router.get("/logs")
async def get_node_logs(
    limit: int = 200,
    level: Optional[str] = None,
    pattern: Optional[str] = None,
):
    """Return recent CIRISNode application logs from in-memory ring buffer."""
    buf = get_log_buffer()
    if buf is None:
        return {"logs": [], "total": 0}
    logs = buf.get_logs(limit=min(limit, 1000), level=level, pattern=pattern)
    return {"logs": logs, "total": len(logs)}


class FrontierModelCreate(BaseModel):
    model_id: str = Field(..., description="Unique model identifier (e.g. 'gpt-4o')")
    display_name: str = Field(..., description="Human-readable name")
    provider: str = Field(..., description="Provider name (e.g. 'OpenAI')")
    api_base_url: str = Field(default="https://api.openai.com/v1", description="API base URL")
    default_model_name: Optional[str] = Field(None, description="Model name for API calls (defaults to model_id)")
    cost_per_1m_input: Optional[float] = Field(None, description="Cost per 1M input tokens (USD)")
    cost_per_1m_output: Optional[float] = Field(None, description="Cost per 1M output tokens (USD)")
    supports_reasoning: bool = Field(default=False, description="Whether model supports reasoning effort")
    reasoning_effort: Optional[str] = Field(None, description="Reasoning effort: low, medium, high")


class FrontierModelResponse(BaseModel):
    model_id: str
    display_name: str
    provider: str
    api_base_url: str
    default_model_name: Optional[str] = None
    cost_per_1m_input: Optional[float] = None
    cost_per_1m_output: Optional[float] = None
    supports_reasoning: bool = False
    reasoning_effort: Optional[str] = None
    created_at: Optional[datetime] = None


class FrontierSweepRequest(BaseModel):
    model_ids: Optional[List[str]] = Field(None, description="Specific models to sweep (None = all)")
    concurrency: int = Field(default=50, ge=1, le=100, description="Per-model concurrency")
    random_seed: Optional[int] = Field(None, description="Random seed for reproducibility")
    semantic_evaluation: bool = Field(default=True, description="Enable semantic LLM evaluation (default: true)")
    evaluator_model: str = Field(default="gpt-4o-mini", description="Model to use for semantic evaluation")
    evaluator_provider: str = Field(default="openai", description="Provider for evaluator model")


class SweepModelStatus(BaseModel):
    model_id: str
    display_name: str
    status: str
    accuracy: Optional[float] = None
    total_scenarios: Optional[int] = None
    errors: Optional[int] = None
    error: Optional[str] = None


class SweepProgressResponse(BaseModel):
    sweep_id: str
    total: int
    completed: int
    failed: int
    pending: int
    running: int
    control_status: str = "running"  # running | paused | cancelled | finished
    models: List[SweepModelStatus]


class SweepListEntry(BaseModel):
    sweep_id: str
    total: int
    completed: int
    failed: int
    started_at: Optional[datetime] = None


class SweepLaunchResponse(BaseModel):
    sweep_id: str
    models: List[str]
    message: str


# ---------------------------------------------------------------------------
# Frontier Model Registry
# ---------------------------------------------------------------------------

UPSERT_MODEL_SQL = """
    INSERT INTO frontier_models (
        model_id, display_name, provider, api_base_url, default_model_name,
        cost_per_1m_input, cost_per_1m_output, supports_reasoning, reasoning_effort,
        created_at
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now())
    ON CONFLICT (model_id) DO UPDATE SET
        display_name = EXCLUDED.display_name,
        provider = EXCLUDED.provider,
        api_base_url = EXCLUDED.api_base_url,
        default_model_name = EXCLUDED.default_model_name,
        cost_per_1m_input = EXCLUDED.cost_per_1m_input,
        cost_per_1m_output = EXCLUDED.cost_per_1m_output,
        supports_reasoning = EXCLUDED.supports_reasoning,
        reasoning_effort = EXCLUDED.reasoning_effort
    RETURNING model_id, display_name, provider, api_base_url, default_model_name,
              cost_per_1m_input, cost_per_1m_output, supports_reasoning, reasoning_effort,
              created_at
"""

LIST_MODELS_SQL = """
    SELECT model_id, display_name, provider, api_base_url, default_model_name,
           cost_per_1m_input, cost_per_1m_output, supports_reasoning, reasoning_effort,
           created_at
    FROM frontier_models ORDER BY created_at
"""

DELETE_MODEL_SQL = "DELETE FROM frontier_models WHERE model_id = $1 RETURNING model_id"


@frontier_router.post("/frontier-models", response_model=FrontierModelResponse, status_code=201)
async def register_frontier_model(body: FrontierModelCreate):
    """Register or update a frontier model."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            UPSERT_MODEL_SQL,
            body.model_id,
            body.display_name,
            body.provider,
            body.api_base_url,
            body.default_model_name or body.model_id,
            body.cost_per_1m_input,
            body.cost_per_1m_output,
            body.supports_reasoning,
            body.reasoning_effort,
        )
    return FrontierModelResponse(
        model_id=row["model_id"],
        display_name=row["display_name"],
        provider=row["provider"],
        api_base_url=row["api_base_url"],
        default_model_name=row["default_model_name"],
        cost_per_1m_input=float(row["cost_per_1m_input"]) if row["cost_per_1m_input"] is not None else None,
        cost_per_1m_output=float(row["cost_per_1m_output"]) if row["cost_per_1m_output"] is not None else None,
        supports_reasoning=row["supports_reasoning"] or False,
        reasoning_effort=row["reasoning_effort"],
        created_at=row["created_at"],
    )


@frontier_router.get("/frontier-models", response_model=List[FrontierModelResponse])
async def list_frontier_models():
    """List all registered frontier models."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(LIST_MODELS_SQL)
    return [
        FrontierModelResponse(
            model_id=r["model_id"],
            display_name=r["display_name"],
            provider=r["provider"],
            api_base_url=r["api_base_url"],
            default_model_name=r["default_model_name"],
            cost_per_1m_input=float(r["cost_per_1m_input"]) if r["cost_per_1m_input"] is not None else None,
            cost_per_1m_output=float(r["cost_per_1m_output"]) if r["cost_per_1m_output"] is not None else None,
            supports_reasoning=r["supports_reasoning"] or False,
            reasoning_effort=r["reasoning_effort"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


@frontier_router.delete("/frontier-models/{model_id}")
async def delete_frontier_model(model_id: str):
    """Remove a frontier model from the registry."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        deleted = await conn.fetchval(DELETE_MODEL_SQL, model_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    return {"deleted": model_id}


# ---------------------------------------------------------------------------
# Frontier Sweep
# ---------------------------------------------------------------------------

SWEEP_PROGRESS_SQL = """
    SELECT e.id, e.target_model, e.status, e.accuracy,
           e.total_scenarios, e.errors,
           e.scenario_results, fm.display_name
    FROM evaluations e
    LEFT JOIN frontier_models fm ON fm.model_id = e.target_model
    WHERE e.trace_id LIKE $1
    ORDER BY e.target_model
"""

RECENT_SWEEPS_SQL = """
    SELECT
        split_part(trace_id, '/', 1) AS sweep_id,
        COUNT(*) AS total,
        COUNT(*) FILTER (WHERE status = 'completed') AS completed,
        COUNT(*) FILTER (WHERE status = 'failed') AS failed,
        MIN(created_at) AS started_at
    FROM evaluations
    WHERE eval_type = 'frontier' AND trace_id LIKE 'sweep-%'
    GROUP BY split_part(trace_id, '/', 1)
    ORDER BY MIN(created_at) DESC
    LIMIT $1
"""


@frontier_router.post("/frontier-sweep", response_model=SweepLaunchResponse)
async def launch_frontier_sweep(body: FrontierSweepRequest):
    """Launch a frontier sweep across registered models.

    Always runs full HE-300 (300 scenarios). Smaller test runs should use
    the agentbeats/run endpoint as client evals.
    """
    api_keys = _load_api_keys()
    if not api_keys:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="FRONTIER_API_KEYS not configured",
        )

    # Load models
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        if body.model_ids:
            placeholders = ", ".join(f"${i+1}" for i in range(len(body.model_ids)))
            rows = await conn.fetch(
                f"SELECT model_id, display_name, provider, api_base_url, default_model_name, "
                f"reasoning_effort, supports_reasoning "
                f"FROM frontier_models WHERE model_id IN ({placeholders})",
                *body.model_ids,
            )
        else:
            rows = await conn.fetch(
                "SELECT model_id, display_name, provider, api_base_url, default_model_name, "
                "reasoning_effort, supports_reasoning "
                "FROM frontier_models ORDER BY created_at"
            )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No frontier models registered",
        )

    # Validate API keys exist for each model's provider (with alias support)
    models_to_run = []
    for row in rows:
        provider_key = row["provider"].lower()
        key_provider = KEY_PROVIDER_ALIASES.get(provider_key, provider_key)
        if key_provider not in api_keys:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"No API key for provider '{row['provider']}' (model: {row['model_id']}). "
                       f"Available keys: {list(api_keys.keys())}",
            )
        models_to_run.append(dict(row))

    # Generate sweep ID and seed
    sweep_id = f"sweep-{uuid.uuid4().hex[:8]}"
    seed = body.random_seed if body.random_seed is not None else int(uuid.uuid4().int % 2**31)

    # Load scenarios once (shared across all models)
    scenarios, dataset_meta = load_scenarios(sample_size=300, seed=seed)
    dataset_meta_dict = dataset_meta.to_dict()

    # Pre-insert pending evaluation rows
    now = datetime.now(timezone.utc)
    eval_ids: Dict[str, uuid.UUID] = {}
    async with pool.acquire() as conn:
        for model in models_to_run:
            eval_id = uuid.uuid4()
            eval_ids[model["model_id"]] = eval_id
            await conn.execute(
                INSERT_EVAL_SQL,
                eval_id,                                    # id
                "frontier-sweep",                           # tenant_id
                "frontier",                                 # eval_type
                model["model_id"],                          # target_model
                model["provider"],                          # target_provider
                model["api_base_url"],                      # target_endpoint
                "openai",                                   # protocol
                model["display_name"],                      # agent_name
                300,                                        # sample_size
                seed,                                       # seed
                body.concurrency,                           # concurrency
                "pending",                                  # status
                None,                                       # accuracy
                None,                                       # total_scenarios
                None,                                       # correct
                None,                                       # errors
                None,                                       # categories
                None,                                       # avg_latency_ms
                None,                                       # processing_ms
                None,                                       # scenario_results
                f"{sweep_id}/{model['model_id']}",          # trace_id
                "public",                                   # visibility
                json.dumps([]),                              # badges
                now,                                        # created_at
                None,                                       # started_at
                None,                                       # completed_at
                json.dumps(dataset_meta_dict),               # dataset_meta
            )

    # Build semantic evaluator config if enabled
    semantic_config: Optional[SemanticEvalConfig] = None
    if body.semantic_evaluation:
        eval_provider = body.evaluator_provider.lower()
        eval_api_key = api_keys.get(eval_provider)
        if eval_api_key:
            # Map provider to base URL
            _PROVIDER_URLS = {
                "openai": "https://api.openai.com/v1",
                "anthropic": "https://api.anthropic.com/v1",
                "openrouter": "https://openrouter.ai/api/v1",
                "together": "https://api.together.xyz/v1",
                "groq": "https://api.groq.com/openai/v1",
                "google": "https://generativelanguage.googleapis.com/v1beta/openai",
                "grok": "https://api.x.ai/v1",
            }
            eval_base_url = _PROVIDER_URLS.get(eval_provider, "https://api.openai.com/v1")
            semantic_config = SemanticEvalConfig(
                evaluator_base_url=eval_base_url,
                evaluator_model=body.evaluator_model,
                evaluator_api_key=eval_api_key,
            )
            logger.info(
                "[SWEEP] Semantic evaluation enabled: model=%s, provider=%s",
                body.evaluator_model, eval_provider,
            )
        else:
            logger.warning(
                "[SWEEP] Semantic evaluation requested but no API key for provider '%s'",
                eval_provider,
            )

    # Register sweep control state
    _sweep_controls[sweep_id] = {"status": "running"}

    # Fire background sweep task
    asyncio.create_task(
        _execute_sweep(
            sweep_id=sweep_id,
            models=models_to_run,
            eval_ids=eval_ids,
            scenarios=scenarios,
            api_keys=api_keys,
            concurrency=body.concurrency,
            seed=seed,
            dataset_meta_dict=dataset_meta_dict,
            semantic_config=semantic_config,
        )
    )

    model_ids = [m["model_id"] for m in models_to_run]
    logger.info("Launched frontier sweep %s: %d models, seed=%d", sweep_id, len(model_ids), seed)
    return SweepLaunchResponse(
        sweep_id=sweep_id,
        models=model_ids,
        message=f"Sweep launched with {len(model_ids)} models. Check progress via GET /api/v1/admin/frontier-sweep/{sweep_id}",
    )


@frontier_router.get("/frontier-sweep/{sweep_id}", response_model=SweepProgressResponse)
async def get_sweep_progress(sweep_id: str):
    """Get progress of a frontier sweep."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(SWEEP_PROGRESS_SQL, f"{sweep_id}/%")

    if not rows:
        raise HTTPException(status_code=404, detail=f"Sweep '{sweep_id}' not found")

    models = []
    completed = 0
    failed = 0
    pending = 0
    running = 0

    for row in rows:
        s = row["status"]
        error = None
        if s == "completed":
            completed += 1
        elif s == "failed":
            failed += 1
            # Extract error from scenario_results if available
            sr = row["scenario_results"]
            if isinstance(sr, str):
                try:
                    sr = json.loads(sr)
                except json.JSONDecodeError:
                    sr = None
            if isinstance(sr, dict):
                error = sr.get("error")
                first_err = sr.get("first_error")
                if first_err and error:
                    error = f"{error}. First error: {first_err}"
        elif s == "running":
            running += 1
        else:
            pending += 1

        models.append(SweepModelStatus(
            model_id=row["target_model"],
            display_name=row["display_name"] or row["target_model"],
            status=s,
            accuracy=row["accuracy"],
            total_scenarios=row["total_scenarios"],
            errors=row["errors"],
            error=error,
        ))

    # Determine control status
    ctrl = _get_sweep_control(sweep_id)
    if ctrl == "running" and pending == 0 and running == 0:
        ctrl = "finished"

    return SweepProgressResponse(
        sweep_id=sweep_id,
        total=len(rows),
        completed=completed,
        failed=failed,
        pending=pending,
        running=running,
        control_status=ctrl,
        models=models,
    )


@frontier_router.get("/frontier-sweeps", response_model=List[SweepListEntry])
async def list_recent_sweeps(limit: int = 20):
    """List recent frontier sweeps."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(RECENT_SWEEPS_SQL, limit)
    return [
        SweepListEntry(
            sweep_id=r["sweep_id"],
            total=r["total"],
            completed=r["completed"],
            failed=r["failed"],
            started_at=r["started_at"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# SSE stream + sweep controls
# ---------------------------------------------------------------------------

@frontier_router.get("/frontier-sweep/{sweep_id}/stream")
async def stream_sweep_progress(sweep_id: str):
    """SSE endpoint streaming sweep progress every 2 seconds."""
    async def _event_stream():
        while True:
            try:
                progress = await get_sweep_progress(sweep_id)
                data = progress.model_dump_json()
                yield f"data: {data}\n\n"
                # Stop streaming when sweep is done
                if progress.pending == 0 and progress.running == 0:
                    yield f"event: done\ndata: {data}\n\n"
                    break
                # Also stop if cancelled and nothing running
                if progress.control_status == "cancelled" and progress.running == 0:
                    yield f"event: done\ndata: {data}\n\n"
                    break
            except HTTPException:
                yield f"event: error\ndata: {{\"error\": \"Sweep not found\"}}\n\n"
                break
            except Exception as exc:
                logger.exception("[SSE] Error streaming sweep %s", sweep_id)
                yield f"event: error\ndata: {{\"error\": \"{exc}\"}}\n\n"
                break
            await asyncio.sleep(2)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@frontier_router.post("/frontier-sweep/{sweep_id}/pause")
async def pause_sweep(sweep_id: str):
    """Pause a running sweep. Models already running will finish."""
    if sweep_id not in _sweep_controls:
        raise HTTPException(status_code=404, detail=f"Sweep '{sweep_id}' not tracked")
    _sweep_controls[sweep_id]["status"] = "paused"
    logger.info("[SWEEP] Paused %s", sweep_id)
    return {"sweep_id": sweep_id, "control_status": "paused"}


@frontier_router.post("/frontier-sweep/{sweep_id}/resume")
async def resume_sweep(sweep_id: str):
    """Resume a paused sweep."""
    if sweep_id not in _sweep_controls:
        raise HTTPException(status_code=404, detail=f"Sweep '{sweep_id}' not tracked")
    _sweep_controls[sweep_id]["status"] = "running"
    logger.info("[SWEEP] Resumed %s", sweep_id)
    return {"sweep_id": sweep_id, "control_status": "running"}


@frontier_router.post("/frontier-sweep/{sweep_id}/cancel")
async def cancel_sweep(sweep_id: str):
    """Cancel a sweep. Running models finish, pending models are marked failed."""
    if sweep_id not in _sweep_controls:
        raise HTTPException(status_code=404, detail=f"Sweep '{sweep_id}' not tracked")
    _sweep_controls[sweep_id]["status"] = "cancelled"
    logger.info("[SWEEP] Cancelled %s", sweep_id)
    # Mark all pending evals as failed
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE evaluations SET status = 'failed',
                   scenario_results = '{"error": "Sweep cancelled by admin"}'::jsonb,
                   completed_at = now()
                   WHERE trace_id LIKE $1 AND status = 'pending'""",
                f"{sweep_id}/%",
            )
    except Exception:
        logger.exception("[SWEEP] Failed to mark pending evals as cancelled for %s", sweep_id)
    return {"sweep_id": sweep_id, "control_status": "cancelled"}


@frontier_router.delete("/frontier-sweep/{sweep_id}")
async def delete_sweep(sweep_id: str):
    """Delete all evaluation rows for a sweep. Irreversible."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM evaluations WHERE trace_id LIKE $1",
            f"{sweep_id}/%",
        )
        if not count:
            raise HTTPException(status_code=404, detail=f"Sweep '{sweep_id}' not found")
        await conn.execute(
            "DELETE FROM evaluations WHERE trace_id LIKE $1",
            f"{sweep_id}/%",
        )
    # Clean up in-memory control state
    _sweep_controls.pop(sweep_id, None)
    # Invalidate caches
    try:
        r = await get_redis()
        await r.delete("cache:scores:frontier", "cache:embed:scores")
    except Exception:
        pass
    logger.info("[SWEEP] Deleted sweep %s (%d evaluations)", sweep_id, count)
    return {"deleted": sweep_id, "evaluations_removed": count}


# ---------------------------------------------------------------------------
# Background sweep execution
# ---------------------------------------------------------------------------

async def _execute_sweep(
    sweep_id: str,
    models: List[Dict[str, Any]],
    eval_ids: Dict[str, uuid.UUID],
    scenarios: list,
    api_keys: Dict[str, str],
    concurrency: int,
    seed: int,
    dataset_meta_dict: Optional[Dict[str, Any]] = None,
    semantic_config: Optional[SemanticEvalConfig] = None,
) -> None:
    """Run benchmark for each model with per-provider + global rate limiting."""
    global_sem = asyncio.Semaphore(GLOBAL_CONCURRENCY)
    # Per-provider semaphores: 1 concurrent model per provider
    provider_sems: Dict[str, asyncio.Semaphore] = {}
    for m in models:
        prov = m["provider"].lower()
        if prov not in provider_sems:
            provider_sems[prov] = asyncio.Semaphore(PROVIDER_CONCURRENCY)

    async def _run_model(model: Dict[str, Any]) -> None:
        model_id = model["model_id"]
        eval_id = eval_ids[model_id]
        provider_key = model["provider"].lower()
        key_provider = KEY_PROVIDER_ALIASES.get(provider_key, provider_key)
        api_key = api_keys[key_provider]
        prov_sem = provider_sems[provider_key]

        # Wait while paused, bail if cancelled
        while _get_sweep_control(sweep_id) == "paused":
            await asyncio.sleep(1)
        if _get_sweep_control(sweep_id) == "cancelled":
            return  # eval already marked failed by cancel endpoint

        try:
            pool = await get_pg_pool()
            now = datetime.now(timezone.utc)
            async with pool.acquire() as conn:
                await conn.execute(UPDATE_EVAL_RUNNING_SQL, eval_id, now)

            model_name = model.get("default_model_name") or model_id
            reasoning_effort = model.get("reasoning_effort")

            # Build provider-specific protocol config + auth
            if provider_key in ANTHROPIC_PROVIDERS:
                protocol_config = AnthropicProtocolConfig(
                    model=model_name,
                    system_prompt=BENCHMARK_SYSTEM_PROMPT,
                    temperature=0.0,
                    max_tokens=512,
                )
                auth = ApiKeyAuth(auth_type="api_key", key=api_key, header_name="x-api-key")
            elif provider_key in GEMINI_PROVIDERS:
                protocol_config = GeminiProtocolConfig(
                    model=model_name,
                    system_prompt=BENCHMARK_SYSTEM_PROMPT,
                    temperature=0.0,
                    max_tokens=512,
                )
                # Gemini uses API key in URL query param, handled by adapter
                auth = ApiKeyAuth(auth_type="api_key", key=api_key, header_name="x-goog-api-key")
            else:
                # OpenAI-compatible (OpenAI, xAI/Grok, OpenRouter, Together, Groq)
                protocol_config = OpenAIProtocolConfig(
                    model=model_name,
                    system_prompt=BENCHMARK_SYSTEM_PROMPT,
                    temperature=0.0,
                    max_tokens=512,
                    reasoning_effort=reasoning_effort,
                )
                auth = BearerAuth(auth_type="bearer", token=api_key)

            agent_spec = AgentSpec(
                name=model.get("display_name", model_id),
                url=model["api_base_url"],
                protocol_config=protocol_config,
                auth=auth,
            )

            batch_id = f"{sweep_id}/{model_id}"
            logger.info(
                "[SWEEP] Starting %s (provider=%s, protocol=%s, model=%s, url=%s)",
                model_id, provider_key, protocol_config.protocol, model_name, model["api_base_url"],
            )

            # Acquire both provider and global semaphore
            async with prov_sem:
                async with global_sem:
                    batch_result = await run_batch(
                        scenarios=scenarios,
                        agent_spec=agent_spec,
                        batch_id=batch_id,
                        concurrency=concurrency,
                        dataset_meta=dataset_meta_dict,
                        semantic_config=semantic_config,
                    )

            # Guard: refuse to publish catastrophic results
            error_rate = batch_result.errors / batch_result.total if batch_result.total else 1.0
            if error_rate > 0.5:
                first_error = next(
                    (r["error"] for r in batch_result.results if r.get("error") and "aborted" not in r["error"]),
                    next((r["error"] for r in batch_result.results if r.get("error")), "unknown"),
                )
                logger.error(
                    "[SWEEP] Model %s REJECTED: %.0f%% error rate (%d/%d errors). "
                    "First error: %s",
                    model_id, error_rate * 100, batch_result.errors, batch_result.total,
                    first_error,
                )
                # Save as failed so we can inspect, but don't publish
                async with pool.acquire() as conn:
                    await conn.execute(
                        UPDATE_EVAL_FAILED_SQL,
                        eval_id,
                        json.dumps({
                            "error": f"Catastrophic error rate: {batch_result.errors}/{batch_result.total} errors",
                            "first_error": first_error,
                        }),
                        datetime.now(timezone.utc),
                    )
                return

            badges = compute_badges(batch_result.accuracy, batch_result.categories)

            completed_at = datetime.now(timezone.utc)
            async with pool.acquire() as conn:
                await conn.execute(
                    UPDATE_EVAL_COMPLETED_SQL,
                    eval_id,
                    batch_result.accuracy,
                    batch_result.total,
                    batch_result.correct,
                    batch_result.errors,
                    json.dumps(batch_result.categories),
                    batch_result.avg_latency_ms,
                    int(batch_result.processing_time_ms),
                    json.dumps(batch_result.results),
                    json.dumps(badges),
                    completed_at,
                    json.dumps(dataset_meta_dict) if dataset_meta_dict else None,
                )

            logger.info(
                "[SWEEP] Model %s completed: accuracy=%.3f (%d/%d)",
                model_id, batch_result.accuracy, batch_result.correct, batch_result.total,
            )

        except Exception as exc:
            logger.exception("[SWEEP] Model %s failed: %s", model_id, exc)
            try:
                pool = await get_pg_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        UPDATE_EVAL_FAILED_SQL,
                        eval_id,
                        json.dumps({"error": str(exc)}),
                        datetime.now(timezone.utc),
                    )
            except Exception:
                logger.exception("[SWEEP] Failed to update eval row for %s", model_id)

    # Run all models with per-provider + global rate limiting
    tasks = [_run_model(m) for m in models]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Clean up control state
    _sweep_controls.pop(sweep_id, None)

    # Invalidate Redis caches
    try:
        r = await get_redis()
        keys_to_delete = ["cache:scores:frontier", "cache:embed:scores"]
        # Also invalidate per-model caches
        for model in models:
            keys_to_delete.append(f"cache:scores:model:{model['model_id']}")
        for key in keys_to_delete:
            await r.delete(key)
        logger.info("[SWEEP] %s complete — invalidated %d cache keys", sweep_id, len(keys_to_delete))
    except Exception:
        logger.exception("[SWEEP] Cache invalidation failed (non-fatal)")
