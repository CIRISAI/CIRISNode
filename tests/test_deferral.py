import pytest
from fastapi.testclient import TestClient
from cirisnode.main import app


def test_deferral_ponder_negative(client):
    """Test WISE DEFERRAL with 'ponder' decision type - unsigned, should be rejected with 403."""
    response = client.post("/api/v1/wa/deferral", json={
        "deferral_type": "ponder",
        "reason": "Need more time to think",
        "target_object": "decision_001"
    })
    assert response.status_code == 403  # Unsigned deferral rejected
    data = response.json()
    assert "detail" in data

def test_deferral_reject_negative(client):
    """Test WISE DEFERRAL with 'reject' decision type - unsigned, should be rejected."""
    response = client.post("/api/v1/wa/deferral", json={
        "deferral_type": "reject",
        "reason": "Not feasible",
        "target_object": "decision_002"
    })
    assert response.status_code == 403
    data = response.json()
    assert "detail" in data

def test_deferral_defer_positive(client):
    """Test WISE DEFERRAL with 'defer' decision type - unsigned, should be rejected."""
    response = client.post("/api/v1/wa/deferral", json={
        "deferral_type": "defer",
        "reason": "Awaiting input",
        "target_object": "decision_003"
    })
    assert response.status_code == 403
    data = response.json()
    assert "detail" in data

def test_deferral_no_did_header(client):
    """Test WISE DEFERRAL without X-DID header - unsigned, should be rejected."""
    response = client.post("/api/v1/wa/deferral", json={
        "deferral_type": "ponder",
        "reason": "Need more time to think"
    })
    assert response.status_code == 403
    data = response.json()
    assert "detail" in data

def test_deferral_missing_deferral_type(client):
    """Test WISE DEFERRAL with missing deferral type - validation error."""
    response = client.post("/api/v1/wa/deferral", json={
        "reason": "Missing type"
    })
    # deferral_type has default None, so it passes validation but fails on unsigned
    assert response.status_code == 403
    data = response.json()
    assert "detail" in data

def test_deferral_invalid_deferral_type(client):
    """Test WISE DEFERRAL with invalid deferral type - unsigned, rejected."""
    response = client.post("/api/v1/wa/deferral", json={
        "deferral_type": "delay",
        "reason": "Invalid type"
    })
    assert response.status_code == 403
    data = response.json()
    assert "detail" in data
