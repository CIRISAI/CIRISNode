import pytest


def test_health_check_positive(client):
    """Test HEALTH endpoint for 200 status and correct response."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "message" in data
    assert "timestamp" in data


def test_health_check_no_did_header(client):
    """Test HEALTH endpoint without X-DID header, should still work."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "message" in data
    assert "timestamp" in data
