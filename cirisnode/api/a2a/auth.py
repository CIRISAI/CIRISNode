"""
Dual authentication for A2A and MCP endpoints.

Supports both JWT Bearer tokens and API Key (X-API-Key header).
API keys are stored in the existing agent_tokens table.
"""

import logging
from typing import Optional

import jwt
from fastapi import Header, HTTPException, Depends

from cirisnode.config import settings
from cirisnode.database import get_db

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"


def _validate_jwt(token: str) -> Optional[dict]:
    """Validate JWT and return claims, or None if invalid."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[ALGORITHM],
        )
        return payload
    except jwt.PyJWTError:
        return None


def _validate_api_key(api_key: str, db) -> Optional[str]:
    """Validate API key against agent_tokens table. Returns owner or None."""
    try:
        import sqlite3
        conn = db if isinstance(db, sqlite3.Connection) else next(db)
        row = conn.execute(
            "SELECT owner FROM agent_tokens WHERE token = ?",
            (api_key,),
        ).fetchone()
        if row:
            return row[0] if row[0] else "agent"
        return None
    except Exception as e:
        logger.warning(f"API key validation error: {e}")
        return None


async def validate_a2a_auth(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db=Depends(get_db),
) -> str:
    """
    Validate A2A request authentication.

    Accepts either:
    - Authorization: Bearer <jwt_token>
    - X-API-Key: <api_key>

    Returns the actor identifier (username or "agent").
    Raises 401 if neither is valid.
    """
    # Try JWT first
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        claims = _validate_jwt(token)
        if claims:
            return claims.get("sub", "unknown")

    # Try API key
    if x_api_key:
        owner = _validate_api_key(x_api_key, db)
        if owner:
            return owner

    # Neither worked
    raise HTTPException(
        status_code=401,
        detail="Valid Authorization (Bearer JWT) or X-API-Key header required",
    )
