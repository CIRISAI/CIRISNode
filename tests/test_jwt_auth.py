"""Tests for JWT-protected endpoint access."""

import pytest
from fastapi.testclient import TestClient
from cirisnode.main import app

client = TestClient(app)


def test_invalid_bearer_token_rejected():
    """A bogus Bearer token should get 401 from the benchmarks endpoint."""
    response = client.post(
        "/api/v1/benchmarks/run",
        headers={"Authorization": "Bearer sk_test_abc123"},
        json={"id": "test_benchmark"},
    )
    assert response.status_code == 401


def test_missing_auth_rejected():
    """No auth header at all should also be rejected."""
    response = client.post(
        "/api/v1/benchmarks/run",
        json={"id": "test_benchmark"},
    )
    assert response.status_code == 401
