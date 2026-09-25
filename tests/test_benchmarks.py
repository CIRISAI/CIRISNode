from cirisnode.config import settings
import jwt


def get_auth_header():
    token = jwt.encode({"sub": "testuser", "role": "user"}, settings.JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}

def test_run_benchmark_refused_when_execution_disabled(client):
    """With EEE_ENABLED=false (the test default and production today) the endpoint
    must refuse with 503 rather than return fabricated results (CIRISNode#33)."""
    headers = get_auth_header()
    response = client.post(
        "/api/v1/benchmarks/run",
        json={"scenario_id": "HE-300-1"},
        headers=headers
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["error"] == "benchmark_execution_disabled"

def test_get_benchmark_results_unknown_job(client):
    headers = get_auth_header()
    results_response = client.get("/api/v1/benchmarks/results/he300-does-not-exist", headers=headers)
    assert results_response.status_code == 404

def test_he300_health_reports_full_dataset(client):
    """Health must count the packaged dataset, not a 10-row sample or a 3-item fallback."""
    response = client.get("/api/v1/benchmarks/he300/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["scenario_source"] == "package"
    assert data["local_scenario_count"] > 300
    assert set(data["local_categories"]) >= {"commonsense", "deontology", "justice", "virtue"}

def test_he300_scenarios_are_real(client):
    response = client.get("/api/v1/benchmarks/he300/scenarios?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "package"
    assert data["total"] == 5
    assert not any(s["id"].startswith("HE-300-FB-") for s in data["scenarios"])

def test_run_simplebench(client):
    headers = get_auth_header()
    response = client.post("/api/v1/simplebench/run", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data

def test_get_simplebench_results(client):
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
