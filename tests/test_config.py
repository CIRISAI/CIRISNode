"""Tests for CIRISNode RBAC config endpoint."""

import os
import sqlite3

# Align JWT_SECRET with auth routes' hardcoded SECRET_KEY ("testsecret")
# so RBAC token verification uses the same key as token signing.
os.environ.setdefault("JWT_SECRET", "testsecret")

import pytest
from fastapi.testclient import TestClient
from cirisnode.main import app


@pytest.fixture(autouse=True)
def _init_sqlite_db():
    """Initialize SQLite DB and align JWT secrets before tests."""
    import importlib
    import cirisnode.utils.rbac as rbac_mod
    importlib.reload(rbac_mod)

    from cirisnode.db.init_db import initialize_database
    os.makedirs("cirisnode/db", exist_ok=True)
    try:
        initialize_database()
    except FileNotFoundError:
        orig = os.getcwd()
        os.chdir(os.path.join(os.path.dirname(__file__), ".."))
        try:
            initialize_database()
        finally:
            os.chdir(orig)


client = TestClient(app)

DB_PATH = "cirisnode/db/cirisnode.db"


def _get_token(username: str):
    resp = client.post("/auth/token", data={"username": username, "password": "pwd"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_config_access_rbac():
    """Anonymous users get 403; admin users get 200 with version info."""
    db = os.path.join(os.path.dirname(__file__), "..", DB_PATH)
    if not os.path.exists(db):
        db = DB_PATH
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)",
        ("anon", "pwd", "anonymous"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO users (username, password, role) VALUES (?, ?, ?)",
        ("admin", "pwd", "admin"),
    )
    conn.commit()
    conn.close()

    anon_token = _get_token("anon")
    r = client.get("/api/v1/config", headers={"Authorization": f"Bearer {anon_token}"})
    assert r.status_code == 403

    admin_token = _get_token("admin")
    r = client.get("/api/v1/config", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert r.json()["version"] == 1
