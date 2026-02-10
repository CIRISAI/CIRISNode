from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from cirisnode.database import get_db
from cirisnode.utils.rbac import require_role
from cirisnode.api.auth.routes import get_actor_from_token
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


def _profile_from_row(user_row, profile_row) -> dict:
    """Build an authority profile dict from user + profile rows."""
    return {
        "id": profile_row[0],
        "user_id": profile_row[1],
        "username": user_row[1],
        "role": user_row[2],
        "expertise_domains": json.loads(profile_row[2] or "[]"),
        "assigned_agent_ids": json.loads(profile_row[3] or "[]"),
        "availability": json.loads(profile_row[4] or "{}"),
        "notification_config": json.loads(profile_row[5] or "{}"),
        "created_at": profile_row[6] or "",
        "updated_at": profile_row[7] or "",
    }


@authority_router.get("", response_model=List[AuthorityProfileOut])
def list_authorities(db=Depends(get_db)):
    """List all authority profiles with user info."""
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    rows = conn.execute("""
        SELECT u.id, u.username, u.role,
               ap.id, ap.user_id, ap.expertise_domains, ap.assigned_agent_ids,
               ap.availability, ap.notification_config, ap.created_at, ap.updated_at
        FROM authority_profiles ap
        JOIN users u ON u.id = ap.user_id
        ORDER BY u.username
    """).fetchall()
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
            "created_at": r[9] or "",
            "updated_at": r[10] or "",
        })
    return result


@authority_router.get("/{user_id}", response_model=AuthorityProfileOut)
def get_authority(user_id: int, db=Depends(get_db)):
    """Get a single authority profile by user_id."""
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    row = conn.execute("""
        SELECT u.id, u.username, u.role,
               ap.id, ap.user_id, ap.expertise_domains, ap.assigned_agent_ids,
               ap.availability, ap.notification_config, ap.created_at, ap.updated_at
        FROM authority_profiles ap
        JOIN users u ON u.id = ap.user_id
        WHERE ap.user_id = ?
    """, (user_id,)).fetchone()
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
        "created_at": row[9] or "",
        "updated_at": row[10] or "",
    }


@authority_router.put("/{user_id}", response_model=AuthorityProfileOut)
def update_authority(user_id: int, req: AuthorityProfileUpdate, Authorization: str = Header(...), db=Depends(get_db)):
    """Update an authority profile (expertise, agents, availability, notifications)."""
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db

    profile = conn.execute(
        "SELECT id FROM authority_profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not profile:
        raise HTTPException(status_code=404, detail="Authority profile not found")

    updates = []
    params = []
    if req.expertise_domains is not None:
        updates.append("expertise_domains = ?")
        params.append(json.dumps(req.expertise_domains))
    if req.assigned_agent_ids is not None:
        updates.append("assigned_agent_ids = ?")
        params.append(json.dumps(req.assigned_agent_ids))
    if req.availability is not None:
        updates.append("availability = ?")
        params.append(json.dumps(req.availability))
    if req.notification_config is not None:
        updates.append("notification_config = ?")
        params.append(json.dumps(req.notification_config))

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(user_id)
        conn.execute(
            f"UPDATE authority_profiles SET {', '.join(updates)} WHERE user_id = ?",
            params,
        )
        conn.commit()

    # Audit
    actor = get_actor_from_token(Authorization)
    write_audit_log(conn, actor=actor, event_type="authority_profile_update", payload={"user_id": user_id})

    return get_authority(user_id, db=iter([conn]))


@authority_router.delete("/{user_id}")
def delete_authority(user_id: int, Authorization: str = Header(...), db=Depends(get_db)):
    """Remove an authority profile (does not delete the user)."""
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db

    profile = conn.execute(
        "SELECT id FROM authority_profiles WHERE user_id = ?", (user_id,)
    ).fetchone()
    if not profile:
        raise HTTPException(status_code=404, detail="Authority profile not found")

    conn.execute("DELETE FROM authority_profiles WHERE user_id = ?", (user_id,))
    conn.commit()

    actor = get_actor_from_token(Authorization)
    write_audit_log(conn, actor=actor, event_type="authority_profile_delete", payload={"user_id": user_id})

    return {"status": "deleted", "user_id": user_id}
