"""Tests for CIRISNode guards: org allowlist, feature flags, and domain routing."""

import os
import asyncio
import asyncpg
import pytest
from fastapi import HTTPException

# Set env vars before any cirisnode imports
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/cirisnode_test")
os.environ.setdefault("JWT_SECRET", "testsecret")


def _update_config(supported_domains: list[str]):
    """Update the config's supported_domains in the database."""
    import json
    db_url = os.environ["DATABASE_URL"]

    async def _update():
        conn = await asyncpg.connect(db_url)
        try:
            # Get current config
            row = await conn.fetchrow("SELECT config_json FROM config WHERE id = 1")
            if row:
                config = json.loads(row["config_json"]) if isinstance(row["config_json"], str) else row["config_json"]
            else:
                config = {"version": 1, "llm": {}, "allowed_org_ids": [], "features": {}}

            config["supported_domains"] = supported_domains

            await conn.execute(
                """
                INSERT INTO config (id, version, config_json)
                VALUES (1, $1, $2::jsonb)
                ON CONFLICT (id) DO UPDATE SET version = $1, config_json = $2::jsonb
                """,
                config.get("version", 1),
                json.dumps(config),
            )
        finally:
            await conn.close()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_update())
    loop.close()


def test_config_includes_supported_domains():
    """Config model should include supported_domains field."""
    from cirisnode.schema.config_models import CIRISConfigV1
    config = CIRISConfigV1()
    assert hasattr(config, "supported_domains")
    assert config.supported_domains == []

    config2 = CIRISConfigV1(supported_domains=["MEDICAL", "FINANCIAL"])
    assert config2.supported_domains == ["MEDICAL", "FINANCIAL"]


def test_domain_check_no_hint_passes(client):
    """No domain_hint should always be accepted."""
    from cirisnode.guards import check_domain_supported

    _update_config([])  # General-purpose node

    async def _test():
        # Should not raise
        await check_domain_supported(None)
        await check_domain_supported("")

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_test())
    loop.close()


def test_domain_check_general_passes(client):
    """GENERAL domain_hint should always be accepted."""
    from cirisnode.guards import check_domain_supported

    _update_config([])  # General-purpose node

    async def _test():
        await check_domain_supported("GENERAL")

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_test())
    loop.close()


def test_domain_check_specialized_rejected_on_general_node(client):
    """Specialized domain should be rejected when node has no supported_domains."""
    from cirisnode.guards import check_domain_supported

    _update_config([])  # General-purpose node (no specialized domains)

    async def _test():
        with pytest.raises(HTTPException) as exc_info:
            await check_domain_supported("MEDICAL")
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["error"] == "domain_not_supported"
        assert exc_info.value.detail["domain"] == "MEDICAL"

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_test())
    loop.close()


def test_domain_check_specialized_accepted_when_supported(client):
    """Specialized domain should be accepted when in node's supported_domains."""
    from cirisnode.guards import check_domain_supported

    _update_config(["MEDICAL", "FINANCIAL"])

    async def _test():
        # Should not raise
        await check_domain_supported("MEDICAL")
        await check_domain_supported("FINANCIAL")

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_test())
    loop.close()


def test_domain_check_specialized_rejected_when_not_supported(client):
    """Specialized domain should be rejected when not in node's supported_domains."""
    from cirisnode.guards import check_domain_supported

    _update_config(["MEDICAL"])  # Only MEDICAL supported

    async def _test():
        with pytest.raises(HTTPException) as exc_info:
            await check_domain_supported("LEGAL")
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["error"] == "domain_not_supported"
        assert exc_info.value.detail["domain"] == "LEGAL"
        assert "MEDICAL" in exc_info.value.detail["supported_domains"]

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_test())
    loop.close()


def test_wbd_submit_rejects_unsupported_domain(client):
    """WBD submit should reject deferrals for unsupported domains."""
    from cirisnode.config import settings
    import jwt

    _update_config([])  # General-purpose node

    token = jwt.encode({"sub": "testuser", "role": "admin"}, settings.JWT_SECRET, algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/v1/wbd/submit",
        json={
            "agent_task_id": "task_domain_test",
            "payload": "Test payload",
            "domain_hint": "MEDICAL",  # Node doesn't support MEDICAL
        },
        headers=headers,
    )

    assert response.status_code == 403
    data = response.json()
    assert data["detail"]["error"] == "domain_not_supported"
    assert data["detail"]["domain"] == "MEDICAL"


def test_accord_registration_returns_supported_domains(client):
    """Public key registration response should include supported_domains."""
    import base64
    from cryptography.hazmat.primitives.asymmetric import ed25519

    _update_config(["MEDICAL", "LEGAL"])

    # Generate a test Ed25519 key
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_key_bytes = public_key.public_bytes_raw()
    public_key_b64 = base64.b64encode(public_key_bytes).decode()

    response = client.post(
        "/api/v1/accord/public-keys",
        json={
            "key_id": "test-key-domain-check",
            "public_key_base64": public_key_b64,
            "algorithm": "ed25519",
            "description": "Test key for domain check",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "supported_domains" in data
    assert data["supported_domains"] == ["MEDICAL", "LEGAL"]
