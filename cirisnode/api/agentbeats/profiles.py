"""Agent profile CRUD — stored in PostgreSQL agent_profiles table.

GET    /api/v1/agent-profiles         — list tenant's saved profiles
POST   /api/v1/agent-profiles         — create a new profile
GET    /api/v1/agent-profiles/{id}    — get single profile
PUT    /api/v1/agent-profiles/{id}    — update profile
DELETE /api/v1/agent-profiles/{id}    — delete profile

All endpoints are tenant-scoped via JWT auth (validate_a2a_auth → actor).
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel, Field

from cirisnode.api.agentbeats.auth import resolve_actor
from cirisnode.db.pg_pool import get_pg_pool

logger = logging.getLogger(__name__)

profiles_router = APIRouter(prefix="/api/v1/agent-profiles", tags=["agent-profiles"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AgentProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    spec: dict[str, Any]
    is_default: bool = False


class AgentProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=128)
    spec: Optional[dict[str, Any]] = None
    is_default: Optional[bool] = None


class AgentProfileResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    spec: dict[str, Any]
    is_default: bool
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

LIST_SQL = """
    SELECT id, tenant_id, name, spec, is_default, created_at, updated_at
    FROM agent_profiles
    WHERE tenant_id = $1
    ORDER BY is_default DESC, updated_at DESC
"""

GET_SQL = """
    SELECT id, tenant_id, name, spec, is_default, created_at, updated_at
    FROM agent_profiles
    WHERE id = $1
"""

INSERT_SQL = """
    INSERT INTO agent_profiles (id, tenant_id, name, spec, is_default, created_at, updated_at)
    VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
    RETURNING id
"""

DELETE_SQL = """
    DELETE FROM agent_profiles WHERE id = $1 AND tenant_id = $2
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

import json

def _row_to_response(row) -> AgentProfileResponse:
    spec = row["spec"]
    if isinstance(spec, str):
        spec = json.loads(spec)
    return AgentProfileResponse(
        id=str(row["id"]),
        tenant_id=row["tenant_id"],
        name=row["name"],
        spec=spec,
        is_default=row["is_default"],
        created_at=row["created_at"].isoformat() if row["created_at"] else "",
        updated_at=row["updated_at"].isoformat() if row["updated_at"] else "",
    )


# ---------------------------------------------------------------------------
# GET /api/v1/agent-profiles
# ---------------------------------------------------------------------------


@profiles_router.get("", response_model=list[AgentProfileResponse])
async def list_profiles(actor: str = Depends(resolve_actor)):
    """List all agent profiles for the authenticated tenant."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(LIST_SQL, actor)
    return [_row_to_response(r) for r in rows]


# ---------------------------------------------------------------------------
# POST /api/v1/agent-profiles
# ---------------------------------------------------------------------------


@profiles_router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_profile(
    body: AgentProfileCreate = Body(...),
    actor: str = Depends(resolve_actor),
):
    """Create a new agent profile."""
    profile_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        # If setting as default, unset existing defaults for this tenant
        if body.is_default:
            await conn.execute(
                "UPDATE agent_profiles SET is_default = false WHERE tenant_id = $1",
                actor,
            )
        await conn.execute(
            INSERT_SQL,
            profile_id, actor, body.name,
            json.dumps(body.spec), body.is_default,
            now, now,
        )

    return {"id": str(profile_id)}


# ---------------------------------------------------------------------------
# GET /api/v1/agent-profiles/{id}
# ---------------------------------------------------------------------------


@profiles_router.get("/{profile_id}", response_model=AgentProfileResponse)
async def get_profile(
    profile_id: str,
    actor: str = Depends(resolve_actor),
):
    """Get a single agent profile. Must be owned by the tenant."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(GET_SQL, uuid.UUID(profile_id))

    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    if row["tenant_id"] != actor:
        raise HTTPException(status_code=404, detail="Profile not found")

    return _row_to_response(row)


# ---------------------------------------------------------------------------
# PUT /api/v1/agent-profiles/{id}
# ---------------------------------------------------------------------------


@profiles_router.put("/{profile_id}", response_model=AgentProfileResponse)
async def update_profile(
    profile_id: str,
    body: AgentProfileUpdate = Body(...),
    actor: str = Depends(resolve_actor),
):
    """Update an existing agent profile. Must be owned by the tenant."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(GET_SQL, uuid.UUID(profile_id))
        if not row:
            raise HTTPException(status_code=404, detail="Profile not found")
        if row["tenant_id"] != actor:
            raise HTTPException(status_code=403, detail="Not the owner")

        sets = []
        params: list[Any] = [uuid.UUID(profile_id)]
        idx = 2

        if body.name is not None:
            sets.append(f"name = ${idx}")
            params.append(body.name)
            idx += 1
        if body.spec is not None:
            sets.append(f"spec = ${idx}::jsonb")
            params.append(json.dumps(body.spec))
            idx += 1
        if body.is_default is not None:
            if body.is_default:
                await conn.execute(
                    "UPDATE agent_profiles SET is_default = false WHERE tenant_id = $1",
                    actor,
                )
            sets.append(f"is_default = ${idx}")
            params.append(body.is_default)
            idx += 1

        if not sets:
            raise HTTPException(status_code=422, detail="No fields to update")

        now = datetime.now(timezone.utc)
        sets.append(f"updated_at = ${idx}")
        params.append(now)

        sql = f"UPDATE agent_profiles SET {', '.join(sets)} WHERE id = $1 RETURNING *"
        updated = await conn.fetchrow(sql, *params)

    return _row_to_response(updated)


# ---------------------------------------------------------------------------
# DELETE /api/v1/agent-profiles/{id}
# ---------------------------------------------------------------------------


@profiles_router.delete("/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: str,
    actor: str = Depends(resolve_actor),
):
    """Delete an agent profile. Must be owned by the tenant."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(DELETE_SQL, uuid.UUID(profile_id), actor)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Profile not found or not owned by you")
