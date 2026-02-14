"""Tests for JWT-protected endpoint access."""


def test_invalid_bearer_token_rejected(client):
    """A bogus Bearer token should get 401 from the benchmarks endpoint."""
    response = client.post(
        "/api/v1/benchmarks/run",
        headers={"Authorization": "Bearer sk_test_abc123"},
        json={"id": "test_benchmark"},
    )
    assert response.status_code == 401


def test_missing_auth_rejected(client):
    """No auth header at all should also be rejected."""
    response = client.post(
        "/api/v1/benchmarks/run",
        json={"id": "test_benchmark"},
    )
    assert response.status_code == 401
