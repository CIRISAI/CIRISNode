from fastapi import APIRouter, Depends, Query, Path, Header
from cirisnode.db.pg_pool import get_pg_pool
from cirisnode.utils.audit import fetch_audit_logs
from cirisnode.auth.dependencies import get_actor_from_token, require_role

audit_router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

@audit_router.get("/logs", dependencies=[Depends(require_role(["admin", "wise_authority"]))])
async def get_audit_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    actor: str | None = None,
):
    """
    Get audit logs from the database. Requires admin or wise_authority role.
    """
    logs = await fetch_audit_logs(limit=limit, offset=offset, actor=actor)
    return {"logs": logs}

@audit_router.delete("/logs/{log_id}", dependencies=[Depends(require_role(["admin"]))])
async def delete_audit_log(log_id: int = Path(..., description="Log ID must not be null")):
    """
    Delete an audit log entry by ID. Requires admin role.
    """
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM audit_logs WHERE id = $1", log_id)
    return {"id": log_id, "status": "deleted"}

@audit_router.patch("/logs/{log_id}/archive", dependencies=[Depends(require_role(["admin"]))])
async def archive_audit_log(archived: bool, log_id: int = Path(..., description="Log ID must not be null")):
    """
    Archive or unarchive an audit log entry by ID. Requires admin role.
    """
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE audit_logs SET archived = $1 WHERE id = $2", archived, log_id)
    return {"id": log_id, "archived": archived}


@audit_router.get("/public")
async def get_public_audit_logs(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    logs = await fetch_audit_logs(limit=limit, offset=offset)
    for log in logs:
        log["actor"] = None
    return {"logs": logs}


@audit_router.get("/logs/me")
async def get_my_audit_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    Authorization: str = Header(...),
):
    actor = get_actor_from_token(Authorization)
    logs = await fetch_audit_logs(limit=limit, offset=offset, actor=actor)
    return {"logs": logs}
