from fastapi import APIRouter, Depends, Query, Path, Header
from cirisnode.database import get_db
from cirisnode.utils.audit import fetch_audit_logs
from cirisnode.api.auth.routes import get_actor_from_token

audit_router = APIRouter(prefix="/api/v1/audit", tags=["audit"])

@audit_router.get("/logs")
async def get_audit_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    actor: str | None = None,
    db=Depends(get_db)
):
    """
    Get audit logs from the database.
    """
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    logs = fetch_audit_logs(conn, limit=limit, offset=offset, actor=actor)
    return {"logs": logs}

@audit_router.delete("/logs/{log_id}")
async def delete_audit_log(log_id: int = Path(..., description="Log ID must not be null"), db=Depends(get_db)):
    """
    Delete an audit log entry by ID.
    """
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    conn.execute("DELETE FROM audit_logs WHERE id = ?", (log_id,))
    conn.commit()
    return {"id": log_id, "status": "deleted"}

@audit_router.patch("/logs/{log_id}/archive")
async def archive_audit_log(archived: bool, log_id: int = Path(..., description="Log ID must not be null"), db=Depends(get_db)):
    """
    Archive or unarchive an audit log entry by ID.
    """
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    conn.execute("UPDATE audit_logs SET archived = ? WHERE id = ?", (1 if archived else 0, log_id))
    conn.commit()
    return {"id": log_id, "archived": archived}


@audit_router.get("/public")
async def get_public_audit_logs(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), db=Depends(get_db)):
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    logs = fetch_audit_logs(conn, limit=limit, offset=offset)
    for log in logs:
        log["actor"] = None
    return {"logs": logs}


@audit_router.get("/logs/me")
async def get_my_audit_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    Authorization: str = Header(...),
    db=Depends(get_db)
):
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    actor = get_actor_from_token(Authorization)
    logs = fetch_audit_logs(conn, limit=limit, offset=offset, actor=actor)
    return {"logs": logs}
