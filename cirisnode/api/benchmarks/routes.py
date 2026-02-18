"""
CIRISNode Benchmark API Routes

REST API endpoints for running HE-300 and SimpleBench benchmarks.
Includes integration with EthicsEngine Enterprise when enabled.
"""

from fastapi import APIRouter, HTTPException, Depends, Request
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

# In-memory job store for demonstration
# In production, use Redis or PostgreSQL
benchmark_jobs: Dict[str, Dict[str, Any]] = {}
simplebench_jobs: Dict[str, Dict[str, Any]] = {}


# --- HE-300 Benchmark Endpoints ---

@benchmarks_router.post("/run")
async def run_benchmark(request: Request, actor: str = Depends(require_auth)):
    from cirisnode.guards import require_feature
    await require_feature("benchmarking")
    """
    Start an HE-300 benchmark job. Requires authentication.

    When EEE_ENABLED=true, this will submit scenarios to EthicsEngine Enterprise
    for evaluation. Otherwise, returns mock results.

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
    
    # Check if EEE integration is enabled
    if settings.EEE_ENABLED:
        # Queue async job via Celery
        try:
            from cirisnode.celery_tasks import run_he300_scenario_task
            
            run_he300_scenario_task(
                job_id=job_id,
                scenario_ids=scenario_ids if scenario_ids else None,
                category=category,
                n_scenarios=n_scenarios,
            )
            
            # Store job metadata
            benchmark_jobs[job_id] = {
                "status": "pending",
                "created_at": datetime.utcnow().isoformat(),
                "benchmark_type": benchmark_type,
                "scenario_ids": scenario_ids,
                "category": category,
                "eee_enabled": True,
            }
            
            logger.info(f"Queued HE-300 benchmark job {job_id} via EEE")
            
        except Exception:
            logger.exception("Failed to queue benchmark job")
            raise HTTPException(status_code=500, detail="Internal server error")
    else:
        # Fallback: Return mock results immediately (for testing without EEE)
        logger.warning(f"EEE disabled, returning mock results for job {job_id}")
        
        benchmark_jobs[job_id] = {
            "status": "completed",
            "created_at": datetime.utcnow().isoformat(),
            "benchmark_type": benchmark_type,
            "scenario_ids": scenario_ids,
            "result": {
                "summary": {
                    "total": n_scenarios,
                    "correct": int(n_scenarios * 0.85),
                    "accuracy": 0.85,
                    "by_category": {},
                },
                "signature": "mock-signature-eee-disabled",
            },
            "eee_enabled": False,
        }
    
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
    job = benchmark_jobs.get(job_id)
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
    job = benchmark_jobs.get(job_id)
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
    from cirisnode.utils.data_loaders import load_he300_data
    
    scenarios = load_he300_data(category=category, limit=limit)
    
    return {
        "total": len(scenarios),
        "scenarios": scenarios,
        "source": "eee" if settings.EEE_ENABLED else "local",
    }


@benchmarks_router.get("/he300/health")
async def he300_health():
    """
    Health check for HE-300 benchmark subsystem.
    
    Checks:
        - EEE connectivity (if enabled)
        - Local data availability
    """
    from cirisnode.utils.data_loaders import load_he300_data
    
    health_info = {
        "status": "healthy",
        "eee_enabled": settings.EEE_ENABLED,
        "eee_base_url": settings.EEE_BASE_URL if settings.EEE_ENABLED else None,
    }
    
    # Check local data
    try:
        local_scenarios = load_he300_data(limit=10)
        health_info["local_data_available"] = len(local_scenarios) > 0
        health_info["local_scenario_count"] = len(local_scenarios)
    except Exception as e:
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
