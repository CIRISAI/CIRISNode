"""
Dual authentication for A2A and MCP endpoints.

Supports both JWT Bearer tokens and API Key (X-API-Key header).
JWT validation tries the CIRISNode JWT_SECRET first, then falls back
to the NextAuth NEXTAUTH_SECRET (shared with the frontend AUTH_SECRET).
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
    """Validate JWT against CIRISNode JWT_SECRET, then NextAuth secret."""
    # Try CIRISNode-issued JWT (JWT_SECRET)
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        pass

    # Try NextAuth-issued JWT (NEXTAUTH_SECRET / AUTH_SECRET)
    nextauth_secret = settings.NEXTAUTH_SECRET
    if nextauth_secret and nextauth_secret != settings.JWT_SECRET:
        try:
            payload = jwt.decode(token, nextauth_secret, algorithms=[ALGORITHM])
            return payload
        except jwt.PyJWTError as e:
            logger.debug("NextAuth JWT validation failed: %s", e)

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
