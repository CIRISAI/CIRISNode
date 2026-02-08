"""Tests for AgentBeats dual-mode authentication.

Covers:
  - Mode detection (AGENTBEATS_MODE env var)
  - Standalone mode: auth bypassed, resolve_actor returns "standalone"
  - Managed mode: auth enforced via validate_a2a_auth
  - Engine Bearer API key fallback
"""

import os
import importlib

import pytest


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------


def test_default_is_managed():
    """Without AGENTBEATS_MODE, is_standalone() returns False."""
    os.environ.pop("AGENTBEATS_MODE", None)
    import cirisnode.config
    cirisnode.config.settings = cirisnode.config.Settings()
    import cirisnode.api.agentbeats.auth as auth
    importlib.reload(auth)
    assert not auth.is_standalone()


@pytest.mark.parametrize("value", ["true", "1", "standalone"])
def test_standalone_mode_values(value):
    """AGENTBEATS_MODE=true/1/standalone should all enable standalone."""
    os.environ["AGENTBEATS_MODE"] = value
    import cirisnode.config
    cirisnode.config.settings = cirisnode.config.Settings()
    import cirisnode.api.agentbeats.auth as auth
    importlib.reload(auth)
    assert auth.is_standalone()
    os.environ.pop("AGENTBEATS_MODE", None)


@pytest.mark.parametrize("value", ["false", "", "0", "no"])
def test_managed_mode_values(value):
    """AGENTBEATS_MODE=false/empty/0/no should all be managed."""
    os.environ["AGENTBEATS_MODE"] = value
    import cirisnode.config
    cirisnode.config.settings = cirisnode.config.Settings()
    import cirisnode.api.agentbeats.auth as auth
    importlib.reload(auth)
    assert not auth.is_standalone()
    os.environ.pop("AGENTBEATS_MODE", None)


# ---------------------------------------------------------------------------
# resolve_actor in standalone mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_actor_standalone():
    """In standalone mode, resolve_actor returns 'standalone' without DB access."""
    os.environ["AGENTBEATS_MODE"] = "true"
    import cirisnode.config
    cirisnode.config.settings = cirisnode.config.Settings()
    import cirisnode.api.agentbeats.auth as auth
    importlib.reload(auth)

    actor = await auth.resolve_actor(
        authorization="Bearer some-api-key",
        x_api_key=None,
    )
    assert actor == "standalone"
    os.environ.pop("AGENTBEATS_MODE", None)


# ---------------------------------------------------------------------------
# Engine Bearer API key fallback
# ---------------------------------------------------------------------------


def test_engine_bearer_api_key_fallback():
    """Engine require_auth should accept a static API key as Bearer token."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "engine"))
    os.environ["ENGINE_API_KEYS"] = "test-key-12345678"
    os.environ["AUTH_ENABLED"] = "true"

    from config.settings import Settings
    settings = Settings()

    from api.dependencies import _validate_jwt, _validate_api_key

    # A non-JWT Bearer token should fail JWT but succeed as API key
    token = "test-key-12345678"
    assert _validate_jwt(token) is None
    assert _validate_api_key(token) is not None
    assert _validate_api_key(token).startswith("apikey:")

    os.environ.pop("ENGINE_API_KEYS", None)


# ---------------------------------------------------------------------------
# CIRISNode config: AGENTBEATS_MODE setting
# ---------------------------------------------------------------------------


def test_config_has_agentbeats_mode():
    """CIRISNode Settings should have AGENTBEATS_MODE field."""
    from cirisnode.config import Settings

    s = Settings()
    assert hasattr(s, "AGENTBEATS_MODE")
    assert isinstance(s.AGENTBEATS_MODE, str)
