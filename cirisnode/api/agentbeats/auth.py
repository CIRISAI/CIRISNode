"""Mode-aware auth for AgentBeats endpoints.

Standalone mode (AGENTBEATS_MODE=true):
  Returns "standalone" — no JWT issuer exists, Engine does its own auth.

Managed mode (default):
  Full JWT/API-key validation via validate_a2a_auth.
"""

from typing import Optional

from fastapi import Header

from cirisnode.config import settings


def is_standalone() -> bool:
    """True when running inside the standalone AgentBeats image."""
    return settings.AGENTBEATS_MODE.lower() in ("true", "1", "standalone")


async def resolve_actor(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> str:
    """FastAPI dependency: mode-aware actor resolution.

    Standalone: returns "standalone" without touching the DB.
    Managed:    delegates to validate_a2a_auth (raises 401 on failure).
    """
    if is_standalone():
        return "standalone"

    from cirisnode.api.a2a.auth import validate_a2a_auth
    from cirisnode.database import get_db

    gen = get_db()
    db = next(gen)
    try:
        return await validate_a2a_auth(
            authorization=authorization,
            x_api_key=x_api_key,
            db=db,
        )
    finally:
        try:
            next(gen)
        except StopIteration:
            pass
