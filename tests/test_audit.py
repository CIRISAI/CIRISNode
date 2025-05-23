from fastapi.testclient import TestClient
from cirisnode.main import app
import jwt

client = TestClient(app)

TEST_SECRET = "testsecret"
def get_auth_header():
    token = jwt.encode({"sub": "testuser"}, TEST_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}

def test_get_audit_logs():
    headers = get_auth_header()
    response = client.get("/api/v1/audit/logs", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "logs" in data
    assert isinstance(data["logs"], list)

def test_get_audit_logs_with_filters():
    headers = get_auth_header()
    response = client.get(
        "/api/v1/audit/logs?type=benchmark_run&from_date=2023-01-01&to_date=2023-12-31",
        headers=headers
    )
    assert response.status_code == 200
    data = response.json()
    assert "logs" in data
    assert isinstance(data["logs"], list)
