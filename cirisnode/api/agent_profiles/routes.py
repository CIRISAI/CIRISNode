"""Agent profile CRUD endpoints.

Allows authenticated users to save, list, and delete agent configurations
(protocol, auth, endpoint URL, etc.) scoped to their tenant_id.
"""

import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from cirisnode.auth.dependencies import require_auth
from cirisnode.db.pg_pool import get_pg_pool
from cirisnode.utils.name_filter import check_banned_words

logger = logging.getLogger(__name__)

MAX_PROFILES_PER_USER = 50
MAX_SPEC_BYTES = 65_536  # 64 KB

agent_profiles_router = APIRouter(
    prefix="/api/v1/agent-profiles",
    tags=["agent-profiles"],
)


# -- Request / Response models ------------------------------------------------

class CreateProfileRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    spec: dict

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        banned = check_banned_words(v)
        if banned:
            raise ValueError("name contains a prohibited word")
        return v

    @field_validator("spec")
    @classmethod
    def spec_size_limit(cls, v: dict) -> dict:
        if len(json.dumps(v, separators=(",", ":"))) > MAX_SPEC_BYTES:
            raise ValueError(f"spec payload exceeds {MAX_SPEC_BYTES // 1024} KB")
        return v


class AgentProfileOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    spec: dict
    is_default: bool
    created_at: str
    updated_at: str


# -- Routes --------------------------------------------------------------------

@agent_profiles_router.get("", response_model=list[AgentProfileOut])
async def list_agent_profiles(actor: str = Depends(require_auth)):
    """List all agent profiles owned by the authenticated user."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, tenant_id, name, spec, is_default, created_at, updated_at
            FROM agent_profiles
            WHERE tenant_id = $1
            ORDER BY created_at DESC
            """,
            actor,
        )
    return [
        AgentProfileOut(
            id=str(row["id"]),
            tenant_id=row["tenant_id"],
            name=row["name"],
            spec=row["spec"] if isinstance(row["spec"], dict) else {},
            is_default=row["is_default"],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
        for row in rows
    ]


@agent_profiles_router.post("", status_code=200)
async def create_agent_profile(
    body: CreateProfileRequest,
    actor: str = Depends(require_auth),
):
    """Save a new agent profile for the authenticated user."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        # Enforce per-user profile limit
        count = await conn.fetchval(
            "SELECT count(*) FROM agent_profiles WHERE tenant_id = $1",
            actor,
        )
        if count >= MAX_PROFILES_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Profile limit reached ({MAX_PROFILES_PER_USER})",
            )

        try:
            row = await conn.fetchrow(
                """
                INSERT INTO agent_profiles (tenant_id, name, spec)
                VALUES ($1, $2, $3::jsonb)
                RETURNING id
                """,
                actor,
                body.name,
                json.dumps(body.spec),
            )
        except Exception as exc:
            # Unique constraint on (tenant_id, name)
            if "idx_agent_profiles_tenant" in str(exc) or "unique" in str(exc).lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A profile with that name already exists",
                )
            raise

    return {"id": str(row["id"])}


@agent_profiles_router.delete("/{profile_id}", status_code=200)
async def delete_agent_profile(
    profile_id: UUID,
    actor: str = Depends(require_auth),
):
    """Delete an agent profile owned by the authenticated user."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM agent_profiles WHERE id = $1 AND tenant_id = $2",
            profile_id,
            actor,
        )
    # result is e.g. "DELETE 1" or "DELETE 0"
    if result == "DELETE 0":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
