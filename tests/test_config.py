"""Tests for CIRISNode RBAC config endpoint."""

import os
import asyncio
import asyncpg


def _seed_users():
    """Insert test users into PostgreSQL."""
    db_url = os.environ.get("DATABASE_URL", "postgresql://localhost/cirisnode_test")

    async def _seed():
        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute(
                "INSERT INTO users (username, password, role) VALUES ($1, $2, $3) ON CONFLICT (username) DO NOTHING",
                "anon", "pwd", "anonymous",
            )
            await conn.execute(
                "INSERT INTO users (username, password, role) VALUES ($1, $2, $3) "
                "ON CONFLICT (username) DO UPDATE SET role = $3",
                "admin", "pwd", "admin",
            )
        finally:
            await conn.close()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_seed())
    loop.close()


def _get_token(client, username: str):
    resp = client.post("/auth/token", data={"username": username, "password": "pwd"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_config_access_rbac(client):
    """Anonymous users get 403; admin users get 200 with version info."""
    _seed_users()

    anon_token = _get_token(client, "anon")
    r = client.get("/api/v1/config", headers={"Authorization": f"Bearer {anon_token}"})
    assert r.status_code == 403

    admin_token = _get_token(client, "admin")
    r = client.get("/api/v1/config", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert r.json()["version"] == 1
