from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from cirisnode.db.pg_pool import get_pg_pool
from cirisnode.auth.dependencies import require_role, get_actor_from_token
from cirisnode.utils.audit import write_audit_log
import json

authority_router = APIRouter(
    prefix="/api/v1/admin/authorities",
    tags=["authorities"],
    dependencies=[Depends(require_role(["admin"]))],
)


class AuthorityProfileUpdate(BaseModel):
    expertise_domains: Optional[List[str]] = None
    assigned_agent_ids: Optional[List[str]] = None
    availability: Optional[Dict[str, Any]] = None
    notification_config: Optional[Dict[str, Any]] = None


class AuthorityProfileOut(BaseModel):
    id: int
    user_id: int
    username: str
    role: str
    expertise_domains: List[str]
    assigned_agent_ids: List[str]
    availability: Dict[str, Any]
    notification_config: Dict[str, Any]
    created_at: str
    updated_at: str


@authority_router.get("", response_model=List[AuthorityProfileOut])
async def list_authorities():
    """List all authority profiles with user info."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.id, u.username, u.role,
                   ap.id, ap.user_id, ap.expertise_domains, ap.assigned_agent_ids,
                   ap.availability, ap.notification_config, ap.created_at, ap.updated_at
            FROM authority_profiles ap
            JOIN users u ON u.id = ap.user_id
            ORDER BY u.username
        """)
    result = []
    for r in rows:
        result.append({
            "id": r[3],
            "user_id": r[4],
            "username": r[1],
            "role": r[2],
            "expertise_domains": json.loads(r[5] or "[]"),
            "assigned_agent_ids": json.loads(r[6] or "[]"),
            "availability": json.loads(r[7] or "{}"),
            "notification_config": json.loads(r[8] or "{}"),
            "created_at": str(r[9] or ""),
            "updated_at": str(r[10] or ""),
        })
    return result


@authority_router.get("/{user_id}", response_model=AuthorityProfileOut)
async def get_authority(user_id: int):
    """Get a single authority profile by user_id."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT u.id, u.username, u.role,
                   ap.id, ap.user_id, ap.expertise_domains, ap.assigned_agent_ids,
                   ap.availability, ap.notification_config, ap.created_at, ap.updated_at
            FROM authority_profiles ap
            JOIN users u ON u.id = ap.user_id
            WHERE ap.user_id = $1
        """, user_id)
    if not row:
        raise HTTPException(status_code=404, detail="Authority profile not found")
    return {
        "id": row[3],
        "user_id": row[4],
        "username": row[1],
        "role": row[2],
        "expertise_domains": json.loads(row[5] or "[]"),
        "assigned_agent_ids": json.loads(row[6] or "[]"),
        "availability": json.loads(row[7] or "{}"),
        "notification_config": json.loads(row[8] or "{}"),
        "created_at": str(row[9] or ""),
        "updated_at": str(row[10] or ""),
    }


@authority_router.put("/{user_id}", response_model=AuthorityProfileOut)
async def update_authority(user_id: int, req: AuthorityProfileUpdate, Authorization: str = Header(...)):
    """Update an authority profile (expertise, agents, availability, notifications)."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT id FROM authority_profiles WHERE user_id = $1", user_id
        )
        if not profile:
            raise HTTPException(status_code=404, detail="Authority profile not found")

        updates = []
        params = []
        param_idx = 1
        if req.expertise_domains is not None:
            updates.append(f"expertise_domains = ${param_idx}")
            params.append(json.dumps(req.expertise_domains))
            param_idx += 1
        if req.assigned_agent_ids is not None:
            updates.append(f"assigned_agent_ids = ${param_idx}")
            params.append(json.dumps(req.assigned_agent_ids))
            param_idx += 1
        if req.availability is not None:
            updates.append(f"availability = ${param_idx}")
            params.append(json.dumps(req.availability))
            param_idx += 1
        if req.notification_config is not None:
            updates.append(f"notification_config = ${param_idx}")
            params.append(json.dumps(req.notification_config))
            param_idx += 1

        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(user_id)
            await conn.execute(
                f"UPDATE authority_profiles SET {', '.join(updates)} WHERE user_id = ${param_idx}",
                *params,
            )

    # Audit
    actor = get_actor_from_token(Authorization)
    await write_audit_log(actor=actor, event_type="authority_profile_update", payload={"user_id": user_id})

    return await get_authority(user_id)


@authority_router.delete("/{user_id}")
async def delete_authority(user_id: int, Authorization: str = Header(...)):
    """Remove an authority profile (does not delete the user)."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        profile = await conn.fetchrow(
            "SELECT id FROM authority_profiles WHERE user_id = $1", user_id
        )
        if not profile:
            raise HTTPException(status_code=404, detail="Authority profile not found")

        await conn.execute("DELETE FROM authority_profiles WHERE user_id = $1", user_id)

    actor = get_actor_from_token(Authorization)
    await write_audit_log(actor=actor, event_type="authority_profile_delete", payload={"user_id": user_id})

    return {"status": "deleted", "user_id": user_id}
