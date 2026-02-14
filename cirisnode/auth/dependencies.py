"""Centralized FastAPI auth dependencies for CIRISNode.

Replaces scattered JWT validation, role checking, and agent token
validation across multiple files. All auth logic lives here.
"""

import logging
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, status

from cirisnode.config import settings
from cirisnode.db.pg_pool import get_pg_pool

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"


def decode_jwt(token: str) -> Optional[dict]:
    """Validate a JWT token against configured secrets.

    Tries JWT_SECRET first, then NEXTAUTH_SECRET as fallback.
    Returns the decoded payload or None if invalid.

    Raises ValueError if no JWT secret is configured.
    """
    if not settings.JWT_SECRET:
        raise ValueError("JWT_SECRET is not configured")

    # Try CIRISNode JWT_SECRET
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        pass

    # Try NextAuth secret (shared with frontend)
    nextauth_secret = settings.NEXTAUTH_SECRET
    if nextauth_secret and nextauth_secret != settings.JWT_SECRET:
        try:
            return jwt.decode(token, nextauth_secret, algorithms=[ALGORITHM])
        except jwt.PyJWTError:
            pass

    return None


def get_actor_from_token(authorization: str) -> str:
    """Extract actor (subject) from a Bearer token. Returns 'unknown' on failure."""
    if not authorization or not authorization.startswith("Bearer "):
        return "unknown"
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_jwt(token)
        if payload:
            return payload.get("sub", "unknown")
    except (ValueError, Exception):
        pass
    return "unknown"


def get_current_user(
    authorization: str = Header(..., alias="Authorization"),
) -> dict:
    """Extract full user claims from JWT. Returns dict with sub, role, etc."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_jwt(token)
        if payload:
            return payload
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
    )


def get_current_role(
    authorization: str = Header(..., alias="Authorization"),
) -> str:
    """Extract role from JWT. Used as a FastAPI dependency."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_jwt(token)
        if payload:
            return payload.get("role", "anonymous")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token",
    )


def require_role(allowed_roles: list):
    """FastAPI dependency factory: require one of the specified roles."""
    def checker(role: str = Depends(get_current_role)):
        if role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Forbidden",
            )
    return checker


async def require_agent_token(
    x_agent_token: str = Header(..., alias="x-agent-token"),
) -> str:
    """Validate agent token from X-Agent-Token header. Returns token as actor."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT token, owner FROM agent_tokens WHERE token = $1",
            x_agent_token,
        )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid agent token",
        )
    return x_agent_token


async def require_auth(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> str:
    """Validate JWT Bearer token or API key. Returns actor identifier.

    Accepts either:
    - Authorization: Bearer <jwt_token>
    - X-API-Key: <api_key>

    Raises 401 if neither is valid.
    """
    # Try JWT first
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
        try:
            payload = decode_jwt(token)
            if payload:
                return payload.get("sub", "unknown")
        except ValueError:
            pass

    # Try API key
    if x_api_key:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT owner FROM agent_tokens WHERE token = $1",
                x_api_key,
            )
        if row:
            return row["owner"] or "agent"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Valid Authorization (Bearer JWT) or X-API-Key header required",
    )


async def optional_auth(
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> Optional[str]:
    """Like require_auth, but returns None instead of raising 401."""
    try:
        return await require_auth(authorization, x_api_key)
    except HTTPException:
        return None
