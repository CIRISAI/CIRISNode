"""Tests for CIRISNode JWT token issuance and refresh."""

import os
import sys

import pytest
import jwt
from fastapi.testclient import TestClient

# Ensure CIRISNode root is importable when pytest runs from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cirisnode.main import app
from cirisnode.auth.dependencies import ALGORITHM
from cirisnode.config import settings


@pytest.fixture(autouse=True)
def _init_sqlite_db():
    """Initialize SQLite DB before tests (handles relative path from project root)."""
    from cirisnode.db.init_db import initialize_database
    os.makedirs("cirisnode/db", exist_ok=True)
    try:
        initialize_database()
    except FileNotFoundError:
        # Running from project root — adjust CWD temporarily
        orig = os.getcwd()
        os.chdir(os.path.join(os.path.dirname(__file__), ".."))
        try:
            initialize_database()
        finally:
            os.chdir(orig)


client = TestClient(app)


def test_get_token():
    response = client.post("/auth/token", data={"username": "testuser", "password": "testpassword"})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    decoded = jwt.decode(data["access_token"], settings.JWT_SECRET, algorithms=[ALGORITHM])
    assert decoded["role"] == "anonymous"


def test_refresh_token():
    response = client.post("/auth/token", data={"username": "testuser", "password": "testpassword"})
    token = response.json()["access_token"]

    response = client.post("/auth/refresh", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    decoded = jwt.decode(data["access_token"], settings.JWT_SECRET, algorithms=[ALGORITHM])
    assert decoded["role"] == "anonymous"
