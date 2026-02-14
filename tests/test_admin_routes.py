"""Tests for admin tenant tier management endpoints.

Tests the DB-only tier management that Portal API calls via admin JWT.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cirisnode.config import settings


def _make_token(role: str = "admin") -> str:
    return jwt.encode({"sub": "test@ciris.ai", "role": role}, settings.JWT_SECRET, algorithm="HS256")


ADMIN_TOKEN = _make_token("admin")
USER_TOKEN = _make_token("user")


class FakeConn:
    """Fake asyncpg connection with controllable return values."""

    def __init__(self):
        self.fetchrow_return = None
        self.fetchval_return = None
        self.execute_return = None

    async def fetchrow(self, sql, *args):
        return self.fetchrow_return

    async def fetchval(self, sql, *args):
        return self.fetchval_return

    async def execute(self, sql, *args):
        return self.execute_return


class FakePool:
    """Fake asyncpg pool that yields a FakeConn via acquire()."""

    def __init__(self, conn: FakeConn):
        self._conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


@pytest.fixture()
def fake_conn():
    return FakeConn()


@pytest.fixture()
def client(fake_conn):
    """TestClient with mocked DB pool."""
    pool = FakePool(fake_conn)

    with patch("cirisnode.api.admin.routes.get_pg_pool", new_callable=AsyncMock, return_value=pool):
        from cirisnode.api.admin.routes import admin_router

        app = FastAPI()
        app.include_router(admin_router)
        yield TestClient(app, raise_server_exceptions=False)


class TestSetTierAuth:
    def test_set_tier_requires_admin(self, client):
        """Non-admin JWT returns 403."""
        resp = client.put(
            "/api/v1/admin/tenants/user@test.com/tier",
            json={"tier": "pro"},
            headers={"Authorization": f"Bearer {USER_TOKEN}"},
        )
        assert resp.status_code == 403

    def test_set_tier_no_auth(self, client):
        """No auth header returns 422 (missing required header)."""
        resp = client.put(
            "/api/v1/admin/tenants/user@test.com/tier",
            json={"tier": "pro"},
        )
        assert resp.status_code == 422


class TestSetTier:
    def test_set_tier_valid(self, client, fake_conn):
        """Admin JWT + valid tier returns 200."""
        fake_conn.fetchval_return = None  # no existing tier
        fake_conn.fetchrow_return = {"tier": "pro"}  # upsert result

        resp = client.put(
            "/api/v1/admin/tenants/user@test.com/tier",
            json={"tier": "pro"},
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "user@test.com"
        assert data["tier"] == "pro"

    def test_set_tier_invalid(self, client):
        """Invalid tier returns 422."""
        resp = client.put(
            "/api/v1/admin/tenants/user@test.com/tier",
            json={"tier": "platinum"},
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        assert resp.status_code == 422


class TestGetTenant:
    def test_get_tenant_default(self, client, fake_conn):
        """Missing tenant returns community default."""
        fake_conn.fetchrow_return = None

        resp = client.get(
            "/api/v1/admin/tenants/unknown@test.com",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tenant_id"] == "unknown@test.com"
        assert data["tier"] == "community"

    def test_get_tenant_existing(self, client, fake_conn):
        """Returns stored tier for existing tenant."""
        fake_conn.fetchrow_return = {
            "tenant_id": "alice@example.com",
            "tier": "pro",
            "stripe_customer_id": "cus_123",
            "stripe_subscription_id": None,
            "updated_at": None,
        }

        resp = client.get(
            "/api/v1/admin/tenants/alice@example.com",
            headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "pro"
        assert data["stripe_customer_id"] == "cus_123"
