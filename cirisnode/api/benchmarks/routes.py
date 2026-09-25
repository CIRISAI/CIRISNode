"""
CIRISNode Benchmark API Routes

REST API endpoints for running HE-300 and SimpleBench benchmarks.
Includes integration with EthicsEngine Enterprise when enabled.
"""

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from cirisnode.config import settings
from cirisnode.auth.dependencies import require_auth
import json
import os
import requests
import logging
from uuid import uuid4
from datetime import datetime
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

benchmarks_router = APIRouter(prefix="/api/v1/benchmarks", tags=["benchmarks"])
simplebench_router = APIRouter(prefix="/api/v1/simplebench", tags=["simplebench"])

# Job store. The API runs under `uvicorn --workers 4`; a per-process dict meant
# /status/{job_id} 404'd on three workers out of four (CIRISNode#33). Jobs live in
# Redis (shared with the Celery workers) with a 7-day TTL; the dict is only a
# last-resort fallback when Redis is unreachable, and is logged as such.
JOB_TTL_SECONDS = 7 * 24 * 3600
_JOB_KEY = "benchjob:{job_id}"
_local_jobs: Dict[str, Dict[str, Any]] = {}
simplebench_jobs: Dict[str, Dict[str, Any]] = {}


async def _job_set(job_id: str, data: Dict[str, Any]) -> None:
    try:
        from cirisnode.utils.redis_cache import get_redis
        r = await get_redis()
        await r.set(_JOB_KEY.format(job_id=job_id), json.dumps(data, default=str), ex=JOB_TTL_SECONDS)
    except Exception as e:  # pragma: no cover - depends on infra
        logger.warning("Redis unavailable for job %s (%s); using process-local store", job_id, e)
        _local_jobs[job_id] = data


async def _job_get(job_id: str) -> Optional[Dict[str, Any]]:
    try:
        from cirisnode.utils.redis_cache import get_redis
        r = await get_redis()
        raw = await r.get(_JOB_KEY.format(job_id=job_id))
        if raw is not None:
            return json.loads(raw)
    except Exception as e:  # pragma: no cover - depends on infra
        logger.warning("Redis unavailable reading job %s (%s); trying process-local store", job_id, e)
    return _local_jobs.get(job_id)


# --- HE-300 Benchmark Endpoints ---

@benchmarks_router.post("/run")
async def run_benchmark(request: Request, actor: str = Depends(require_auth)):
    from cirisnode.guards import require_feature
    await require_feature("benchmarking")
    """
    Start an HE-300 benchmark job. Requires authentication.

    When EEE_ENABLED=true, scenarios are queued to the Celery worker for evaluation.
    Otherwise the request is refused with 503 benchmark_execution_disabled.

    Request body:
        - benchmark_type: "he300" (optional, defaults to he300)
        - scenario_id: Specific scenario to run (optional)
        - scenario_ids: List of scenario IDs to run (optional)
        - category: Filter by category (optional)
        - model: LLM model to use (optional)
        - n_scenarios: Number of scenarios to run (optional, default 300)

    Returns:
        - job_id: Unique identifier for polling results
    """
    
    data = await request.json()
    job_id = f"he300-{uuid4().hex[:12]}"
    
    # Extract parameters
    benchmark_type = data.get("benchmark_type", "he300")
    scenario_id = data.get("scenario_id")
    scenario_ids = data.get("scenario_ids", [])
    category = data.get("category")
    n_scenarios = data.get("n_scenarios", 300)
    
    # Handle single scenario_id
    if scenario_id and scenario_id not in scenario_ids:
        scenario_ids.append(scenario_id)
    
    # Benchmark execution on this node is only available through the Celery path.
    # When it is disabled we say so — we never return synthetic results from a
    # production route (CIRISNode#33). This runs before anything is recorded so a
    # refused call consumes no quota.
    if not settings.EEE_ENABLED:
        logger.info("Benchmark run refused: execution disabled on this node (actor=%s)", actor)
        raise HTTPException(
            status_code=503,
            detail={
                "error": "benchmark_execution_disabled",
                "message": (
                    "Benchmark execution is not enabled on this node. Frontier scores are "
                    "available at /api/v1/scores; contact the operator to enable runs."
                ),
            },
        )

    try:
        from cirisnode.celery_tasks import run_he300_scenario_task

        run_he300_scenario_task(
            job_id=job_id,
            scenario_ids=scenario_ids if scenario_ids else None,
            category=category,
            n_scenarios=n_scenarios,
        )
    except Exception:
        logger.exception("Failed to queue benchmark job")
        raise HTTPException(status_code=500, detail="Internal server error")

    await _job_set(job_id, {
        "status": "pending",
        "created_at": datetime.utcnow().isoformat(),
        "benchmark_type": benchmark_type,
        "scenario_ids": scenario_ids,
        "category": category,
        "actor": actor,
        "eee_enabled": True,
    })
    logger.info("Queued HE-300 benchmark job %s", job_id)

    return {"job_id": job_id}


@benchmarks_router.get("/status/{job_id}")
async def get_benchmark_status(job_id: str):
    """
    Get the status of a benchmark job.
    
    Returns:
        - status: "pending", "running", "completed", "failed"
        - created_at: When job was created
        - progress: Optional progress information
    """
    job = await _job_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Benchmark job not found")

    return {
        "job_id": job_id,
        "status": job.get("status", "unknown"),
        "created_at": job.get("created_at"),
        "eee_enabled": job.get("eee_enabled", False),
    }


@benchmarks_router.get("/results/{job_id}")
async def get_benchmark_results(job_id: str):
    """
    Get the results of a completed benchmark job.
    
    Returns:
        - result: Contains summary statistics and signature
        - results: Individual scenario results (if available)
    """
    job = await _job_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Benchmark job not found")

    if job.get("status") == "pending":
        raise HTTPException(status_code=202, detail="Job still pending")
    
    if job.get("status") == "running":
        raise HTTPException(status_code=202, detail="Job still running")
    
    if job.get("status") == "failed":
        return {
            "job_id": job_id,
            "status": "failed",
            "error": job.get("error", "Unknown error"),
        }
    
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "result": job.get("result", {}),
    }


@benchmarks_router.get("/he300/scenarios")
async def list_he300_scenarios(
    category: Optional[str] = None,
    limit: int = 100,
):
    """
    List available HE-300 scenarios.
    
    When EEE_ENABLED=true, fetches from EthicsEngine Enterprise.
    Otherwise, returns locally available scenarios.
    """
    from cirisnode.utils.data_loaders import HE300DataUnavailable, he300_data_source, load_he300_data

    try:
        scenarios = load_he300_data(category=category, limit=limit)
    except HE300DataUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "total": len(scenarios),
        "scenarios": scenarios,
        "source": he300_data_source(),
    }


@benchmarks_router.get("/he300/health")
async def he300_health():
    """
    Health check for HE-300 benchmark subsystem.
    
    Checks:
        - EEE connectivity (if enabled)
        - Local data availability
    """
    from cirisnode.utils.data_loaders import (
        HE300DataUnavailable, he300_data_source, load_he300_data,
    )

    health_info: Dict[str, Any] = {
        "status": "healthy",
        "eee_enabled": settings.EEE_ENABLED,
        "eee_base_url": settings.EEE_BASE_URL if settings.EEE_ENABLED else None,
        "scenario_source": he300_data_source(),
    }

    # Local data: report the full dataset size (the old `limit=10` made a healthy
    # node and a node with 3 placeholder scenarios look the same, CIRISNode#32).
    try:
        local_scenarios = load_he300_data()
        health_info["local_data_available"] = len(local_scenarios) > 0
        health_info["local_scenario_count"] = len(local_scenarios)
        health_info["local_categories"] = sorted({s["category"] for s in local_scenarios})
    except HE300DataUnavailable as e:
        health_info["status"] = "degraded"
        health_info["local_data_available"] = False
        health_info["local_scenario_count"] = 0
        health_info["local_data_error"] = str(e)
    except Exception as e:
        health_info["status"] = "degraded"
        health_info["local_data_available"] = False
        health_info["local_data_error"] = str(e)

    # Check EEE connectivity if enabled
    if settings.EEE_ENABLED:
        try:
            from cirisnode.utils.eee_client import check_eee_available
            import asyncio
            
            loop = asyncio.get_event_loop()
            eee_available = loop.run_until_complete(check_eee_available())
            health_info["eee_connected"] = eee_available
        except Exception as e:
            health_info["eee_connected"] = False
            health_info["eee_error"] = str(e)

    if health_info["status"] != "healthy":
        return JSONResponse(status_code=503, content=health_info)
    return health_info


# --- SimpleBench Endpoints (unchanged) ---

@simplebench_router.post("/run")
async def run_simplebench(request: Request, actor: str = Depends(require_auth)):
    """Start a SimpleBench job. Requires authentication."""
    job_id = str(uuid4())
    # Simulate job creation
    simplebench_jobs[job_id] = {
        "status": "completed",
        "result": {"score": 42, "signature": "simplebench-signature"},
        "created_at": datetime.utcnow().isoformat()
    }
    return {"job_id": job_id}


@simplebench_router.get("/results/{job_id}")
async def get_simplebench_results(job_id: str):
    job = simplebench_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="SimpleBench job not found")
    return {"id": "SimpleBench", "result": job["result"]}


@simplebench_router.post("/run-sync")
async def run_simplebench_sync(payload: dict, actor: str = Depends(require_auth)):
    """
    Run a SimpleBench job synchronously.
    """
    # Load the SimpleBench scenarios from the JSON file
    json_path = os.path.join("ui", "public", "simple_bench_public.json")
    try:
        with open(json_path, "r") as f:
            simple_bench_data = json.load(f)
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="SimpleBench data file not found.")
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse SimpleBench data file.")

    # Extract the eval_data
    scenarios = simple_bench_data.get("eval_data", [])
    if not scenarios:
        raise HTTPException(status_code=500, detail="No scenarios found in SimpleBench data.")

    # Filter scenarios based on the provided scenario_ids
    scenario_ids = payload.get("scenario_ids", [])
    filtered_scenarios = [s for s in scenarios if str(s["question_id"]) in scenario_ids]

    # Determine the provider and model
    provider = payload.get("provider")
    model = payload.get("model")
    if not provider or not model:
        raise HTTPException(status_code=400, detail="Provider and model must be specified.")

    # Generate results by querying the AI model
    results = []
    for scenario in filtered_scenarios:
        prompt = scenario["prompt"]
        try:
            if provider == "openai":
                # Query OpenAI API
                response = requests.post(
                    "https://api.openai.com/v1/completions",
                    headers={
                        "Authorization": f"Bearer {payload.get('apiKey')}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": model,
                        "prompt": prompt,
                        "max_tokens": 100,
                        "temperature": 0.7
                    }
                )
                response.raise_for_status()
                ai_response = response.json().get("choices", [{}])[0].get("text", "").strip()
            elif provider == "ollama":
                # Query Ollama API
                response = requests.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={"model": model, "prompt": prompt}
                )
                response.raise_for_status()
                # Debugging: Log the raw response
                # Log the raw response to a file for debugging
                # Process streaming JSON response
                ai_response = ""
                for line in response.iter_lines():
                    if line.strip():
                        try:
                            json_line = json.loads(line)
                            ai_response += json_line.get("response", "")
                        except json.JSONDecodeError:
                            continue
                ai_response = ai_response.strip()
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")
        except requests.RequestException:
            logger.exception("Failed to query provider %s", provider)
            raise HTTPException(status_code=500, detail="Internal server error")

        # Determine if the response matches the expected answer
        passed = ai_response.lower() == scenario["answer"].lower()

        # Append the result
        results.append({
            "scenario_id": str(scenario["question_id"]),
            "prompt": prompt,
            "response": ai_response,
            "expected_answer": scenario["answer"],
            "model_used": model,
            "passed": passed
        })

    return {
        "status": "success",
        "results": results
    }
