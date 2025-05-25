from fastapi import APIRouter, HTTPException, Depends, Request, Header
from cirisnode.database import get_db
import json
import os
import requests
from uuid import uuid4
from datetime import datetime
from fastapi.responses import JSONResponse
import jwt

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")

benchmarks_router = APIRouter(prefix="/api/v1/benchmarks", tags=["benchmarks"])
simplebench_router = APIRouter(prefix="/api/v1/simplebench", tags=["simplebench"])

# In-memory job store for demonstration
benchmark_jobs = {}
simplebench_jobs = {}

@benchmarks_router.post("/run")
async def run_benchmark(request: Request, Authorization: str = Header(None)):
    if not Authorization or not Authorization.startswith("Bearer "):
        raise HTTPException(status_code=400, detail="Missing or invalid Authorization header")
    token = Authorization.split(" ", 1)[1]
    try:
        jwt.decode(token, "testsecret", algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid token")
    data = await request.json()
    scenario_id = data.get("scenario_id", "HE-300-1")
    job_id = str(uuid4())
    # Simulate job creation
    benchmark_jobs[job_id] = {
        "scenario_id": scenario_id,
        "status": "completed",
        "result": {"score": 100, "signature": "dummy-signature"},
        "created_at": datetime.utcnow().isoformat()
    }
    return {"job_id": job_id}

@benchmarks_router.get("/results/{job_id}")
async def get_benchmark_results(job_id: str):
    job = benchmark_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Benchmark job not found")
    return {"result": job["result"]}

@simplebench_router.post("/run")
async def run_simplebench(request: Request):
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
async def run_simplebench_sync(payload: dict, db=Depends(get_db)):
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
        except requests.RequestException as e:
            raise HTTPException(status_code=500, detail=f"Failed to query {provider}: {str(e)}")

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
