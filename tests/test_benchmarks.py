from fastapi.testclient import TestClient
from cirisnode.main import app
from cirisnode.config import settings
import jwt

client = TestClient(app)

def get_auth_header():
    token = jwt.encode({"sub": "testuser", "role": "user"}, settings.JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}

def test_run_benchmark():
    headers = get_auth_header()
    response = client.post(
        "/api/v1/benchmarks/run",
        json={"scenario_id": "HE-300-1"},
        headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data

def test_get_benchmark_results():
    headers = get_auth_header()
    # First, run a benchmark to get a job_id
    run_response = client.post(
        "/api/v1/benchmarks/run",
        json={"scenario_id": "HE-300-1"},
        headers=headers
    )
    job_id = run_response.json()["job_id"]
    
    # Then, get the results
    results_response = client.get(f"/api/v1/benchmarks/results/{job_id}", headers=headers)
    assert results_response.status_code == 200
    data = results_response.json()
    assert "result" in data
    assert "signature" in data["result"]

def test_run_simplebench():
    headers = get_auth_header()
    response = client.post("/api/v1/simplebench/run", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data

def test_get_simplebench_results():
    headers = get_auth_header()
    # First, run simplebench to get a job_id
    run_response = client.post("/api/v1/simplebench/run", headers=headers)
    job_id = run_response.json()["job_id"]
    
    # Then, get the results
    results_response = client.get(f"/api/v1/simplebench/results/{job_id}", headers=headers)
    assert results_response.status_code == 200
    data = results_response.json()
    assert "id" in data
    assert data["id"] == "SimpleBench"
