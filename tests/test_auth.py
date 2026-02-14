"""Tests for CIRISNode JWT token issuance and refresh."""

import jwt
from cirisnode.auth.dependencies import ALGORITHM
from cirisnode.config import settings


def test_get_token(client):
    response = client.post("/auth/token", data={"username": "testuser", "password": "testpassword"})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    decoded = jwt.decode(data["access_token"], settings.JWT_SECRET, algorithms=[ALGORITHM])
    assert decoded["role"] == "anonymous"


def test_refresh_token(client):
    response = client.post("/auth/token", data={"username": "testuser", "password": "testpassword"})
    token = response.json()["access_token"]

    response = client.post("/auth/refresh", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    decoded = jwt.decode(data["access_token"], settings.JWT_SECRET, algorithms=[ALGORITHM])
    assert decoded["role"] == "anonymous"
