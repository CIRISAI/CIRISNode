"""Frontier model registry + sweep management endpoints.

POST   /api/v1/admin/frontier-models           — register a model
GET    /api/v1/admin/frontier-models           — list registered models
DELETE /api/v1/admin/frontier-models/{model_id} — remove a model

POST   /api/v1/admin/frontier-sweep            — launch sweep
GET    /api/v1/admin/frontier-sweep/{sweep_id}  — sweep progress
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
from pydantic import BaseModel, Field

from cirisnode.benchmark.agent_spec import (
    AgentSpec,
    BearerAuth,
    OpenAIProtocolConfig,
)
from cirisnode.benchmark.badges import compute_badges
from cirisnode.benchmark.loader import load_scenarios
from cirisnode.benchmark.runner import run_batch
from cirisnode.config import settings
from cirisnode.db.pg_pool import get_pg_pool
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


# In-memory INSERT SQL (matches agentbeats INSERT_EVAL_SQL)
INSERT_EVAL_SQL = """
    INSERT INTO evaluations (
        id, tenant_id, eval_type, target_model, target_provider,
        target_endpoint, protocol, agent_name, sample_size, seed,
        concurrency, status, accuracy, total_scenarios, correct,
        errors, categories, avg_latency_ms, processing_ms,
        scenario_results, trace_id, visibility, badges,
        created_at, started_at, completed_at
    ) VALUES (
        $1, $2, $3, $4, $5,
        $6, $7, $8, $9, $10,
        $11, $12, $13, $14, $15,
        $16, $17, $18, $19,
        $20, $21, $22, $23,
        $24, $25, $26
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
        completed_at = $11
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

class FrontierModelCreate(BaseModel):
    model_id: str = Field(..., description="Unique model identifier (e.g. 'gpt-4o')")
    display_name: str = Field(..., description="Human-readable name")
    provider: str = Field(..., description="Provider name (e.g. 'OpenAI')")
    api_base_url: str = Field(default="https://api.openai.com/v1", description="API base URL")
    default_model_name: Optional[str] = Field(None, description="Model name for API calls (defaults to model_id)")


class FrontierModelResponse(BaseModel):
    model_id: str
    display_name: str
    provider: str
    api_base_url: str
    default_model_name: Optional[str] = None
    created_at: Optional[datetime] = None


class FrontierSweepRequest(BaseModel):
    model_ids: Optional[List[str]] = Field(None, description="Specific models to sweep (None = all)")
    concurrency: int = Field(default=50, ge=1, le=100, description="Per-model concurrency")
    random_seed: Optional[int] = Field(None, description="Random seed for reproducibility")


class SweepModelStatus(BaseModel):
    model_id: str
    display_name: str
    status: str
    accuracy: Optional[float] = None
    error: Optional[str] = None


class SweepProgressResponse(BaseModel):
    sweep_id: str
    total: int
    completed: int
    failed: int
    pending: int
    running: int
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
    INSERT INTO frontier_models (model_id, display_name, provider, api_base_url, default_model_name, created_at)
    VALUES ($1, $2, $3, $4, $5, now())
    ON CONFLICT (model_id) DO UPDATE SET
        display_name = EXCLUDED.display_name,
        provider = EXCLUDED.provider,
        api_base_url = EXCLUDED.api_base_url,
        default_model_name = EXCLUDED.default_model_name
    RETURNING model_id, display_name, provider, api_base_url, default_model_name, created_at
"""

LIST_MODELS_SQL = """
    SELECT model_id, display_name, provider, api_base_url, default_model_name, created_at
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
        )
    return FrontierModelResponse(
        model_id=row["model_id"],
        display_name=row["display_name"],
        provider=row["provider"],
        api_base_url=row["api_base_url"],
        default_model_name=row["default_model_name"],
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
                f"SELECT model_id, display_name, provider, api_base_url, default_model_name "
                f"FROM frontier_models WHERE model_id IN ({placeholders})",
                *body.model_ids,
            )
        else:
            rows = await conn.fetch(
                "SELECT model_id, display_name, provider, api_base_url, default_model_name "
                "FROM frontier_models ORDER BY created_at"
            )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No frontier models registered",
        )

    # Validate API keys exist for each model's provider
    models_to_run = []
    for row in rows:
        provider_key = row["provider"].lower()
        if provider_key not in api_keys:
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
    scenarios = load_scenarios(sample_size=300, seed=seed)

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
            )

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
        elif s == "running":
            running += 1
        else:
            pending += 1

        models.append(SweepModelStatus(
            model_id=row["target_model"],
            display_name=row["display_name"] or row["target_model"],
            status=s,
            accuracy=row["accuracy"],
            error=error,
        ))

    return SweepProgressResponse(
        sweep_id=sweep_id,
        total=len(rows),
        completed=completed,
        failed=failed,
        pending=pending,
        running=running,
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
) -> None:
    """Run benchmark for each model with bounded parallelism (2 at a time)."""
    semaphore = asyncio.Semaphore(2)  # Limit parallel model runs to avoid rate limits

    async def _run_model(model: Dict[str, Any]) -> None:
        model_id = model["model_id"]
        eval_id = eval_ids[model_id]
        provider_key = model["provider"].lower()
        api_key = api_keys[provider_key]

        try:
            # Mark as running
            pool = await get_pg_pool()
            now = datetime.now(timezone.utc)
            async with pool.acquire() as conn:
                await conn.execute(UPDATE_EVAL_RUNNING_SQL, eval_id, now)

            # Build AgentSpec for this model
            model_name = model.get("default_model_name") or model_id
            agent_spec = AgentSpec(
                name=model.get("display_name", model_id),
                url=model["api_base_url"],
                protocol_config=OpenAIProtocolConfig(
                    protocol="openai",
                    model=model_name,
                    temperature=0.0,
                    max_tokens=256,
                ),
                auth=BearerAuth(auth_type="bearer", token=api_key),
            )

            batch_id = f"{sweep_id}/{model_id}"
            logger.info("[SWEEP] Starting model %s (batch=%s)", model_id, batch_id)

            async with semaphore:
                batch_result = await run_batch(
                    scenarios=scenarios,
                    agent_spec=agent_spec,
                    batch_id=batch_id,
                    concurrency=concurrency,
                )

            # Compute badges (always full HE-300)
            badges = compute_badges(batch_result.accuracy, batch_result.categories)

            # Update eval row with results
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

    # Run all models with bounded concurrency
    tasks = [_run_model(m) for m in models]
    await asyncio.gather(*tasks, return_exceptions=True)

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
