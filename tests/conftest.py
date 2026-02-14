"""Shared test fixtures for CIRISNode tests.

Requires DATABASE_URL env var pointing to a PostgreSQL database.
Defaults to postgresql://localhost/cirisnode_test for local development.
"""

import os
import asyncio

import pytest
import asyncpg

# Set env vars before any cirisnode imports
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/cirisnode_test")
os.environ.setdefault("JWT_SECRET", "testsecret")

from fastapi.testclient import TestClient
from cirisnode.main import app


@pytest.fixture(scope="session")
def client():
    """Session-scoped TestClient. Keeps the app lifespan (and PG pool) alive
    across all test modules so the asyncpg pool isn't recreated per-module."""
    with TestClient(app) as c:
        # Seed test data after migrations have run (via lifespan)
        db_url = os.environ["DATABASE_URL"]

        async def seed():
            conn = await asyncpg.connect(db_url)
            try:
                await conn.execute(
                    "INSERT INTO agent_tokens (token, owner) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    "test-agent-token-abc123", "test-agent",
                )
            finally:
                await conn.close()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(seed())
        loop.close()

        yield c
