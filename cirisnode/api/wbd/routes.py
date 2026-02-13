"""WBD router at /api/v1/wbd — delegates to the wa_router's implementation.

The frontend uses /api/v1/wbd/tasks while the agent-facing API uses /api/v1/wbd/submit.
Both /wbd/submit and /wa/submit share the same signature-based auth logic.

Auth model: agents sign deferrals with their Ed25519 key. Keys are registered
via CIRISPortal (portal.ciris.ai) → CIRISRegistry. Unsigned submissions rejected.
"""
from fastapi import APIRouter, HTTPException, status, Depends, Header
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import sqlite3

from cirisnode.database import get_db
from cirisnode.utils.encryption import encrypt_data, decrypt_data
from cirisnode.utils.audit import write_audit_log
from cirisnode.utils.rbac import require_role, get_current_role
from cirisnode.api.auth.routes import get_actor_from_token
from cirisnode.api.wa.routes import (
    WBDSubmitRequest,
    WBDResolveRequest,
    WBDAssignRequest,
    _route_wbd_task,
    _get_notification_config,
    _fire_notification,
    submit_wbd_task as _wa_submit_wbd_task,
)
import logging

logger = logging.getLogger(__name__)

wbd_router = APIRouter(prefix="/api/v1/wbd", tags=["wbd"])


@wbd_router.post("/submit", response_model=dict)
def submit_wbd_task(request: WBDSubmitRequest, db: sqlite3.Connection = Depends(get_db)):
    """Submit a new WBD task. Delegates to wa_router's signature-verified implementation."""
    return _wa_submit_wbd_task(request, db)


@wbd_router.get("/tasks")
def get_wbd_tasks(
    state: Optional[str] = None,
    since: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db),
    role: str = Depends(get_current_role),
    Authorization: str = Header(default=""),
):
    """List WBD tasks. Authorities see only their assigned or unassigned tasks."""
    try:
        # SLA auto-escalation
        from datetime import timedelta
        sla_cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
        open_tasks = db.execute(
            "SELECT id FROM wbd_tasks WHERE status = 'open' AND created_at < ?", (sla_cutoff,)
        ).fetchall()
        for (tid,) in open_tasks:
            db.execute("UPDATE wbd_tasks SET status = 'sla_breached' WHERE id = ?", (tid,))
            write_audit_log(db, actor="system", event_type="wbd_sla_breach",
                            payload={"task_id": tid}, details={"reason": "SLA breach (24h)"})
        db.commit()

        query = "SELECT id, agent_task_id, payload, status, created_at, decision, comment, resolved_at, assigned_to, domain_hint, notified_at FROM wbd_tasks WHERE 1=1"
        params: list = []

        if role == "wise_authority":
            actor = get_actor_from_token(Authorization)
            query += " AND (assigned_to = ? OR assigned_to IS NULL)"
            params.append(actor)

        if state:
            query += " AND status = ?"
            params.append(state)
        if since:
            query += " AND created_at >= ?"
            params.append(since)

        rows = db.execute(query, params).fetchall()
        tasks = []
        for r in rows:
            try:
                payload = decrypt_data(r[2]) if r[2] else ""
            except Exception:
                payload = r[2] or ""
            tasks.append({
                "id": r[0],
                "agent_task_id": r[1],
                "payload": payload,
                "status": r[3],
                "created_at": r[4],
                "decision": r[5],
                "comment": r[6],
                "resolved_at": r[7],
                "assigned_to": r[8],
                "domain_hint": r[9],
                "notified_at": r[10],
            })
        return {"tasks": tasks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@wbd_router.get("/tasks/{task_id}")
def get_wbd_task(task_id: str, db: sqlite3.Connection = Depends(get_db)):
    """Get a single WBD task by ID. Used by agents to poll resolution status."""
    try:
        row = db.execute(
            "SELECT id, agent_task_id, payload, status, created_at, decision, comment, resolved_at, assigned_to, domain_hint, notified_at FROM wbd_tasks WHERE id = ?",
            (task_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"WBD task {task_id} not found")

        try:
            payload = decrypt_data(row[2]) if row[2] else ""
        except Exception:
            payload = row[2] or ""

        return {
            "task": {
                "id": row[0],
                "agent_task_id": row[1],
                "payload": payload,
                "status": row[3],
                "created_at": row[4],
                "decision": row[5],
                "comment": row[6],
                "resolved_at": row[7],
                "assigned_to": row[8],
                "domain_hint": row[9],
                "notified_at": row[10],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving WBD task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@wbd_router.post("/tasks/{task_id}/resolve")
def resolve_wbd_task(task_id: str, request: WBDResolveRequest, db: sqlite3.Connection = Depends(get_db)):
    if request.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Decision must be 'approve' or 'reject'")
    task = db.execute("SELECT id FROM wbd_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail=f"WBD task {task_id} not found")
    db.execute(
        "UPDATE wbd_tasks SET status = 'resolved', decision = ?, comment = ?, resolved_at = ? WHERE id = ?",
        (request.decision, request.comment, datetime.utcnow().isoformat(), task_id),
    )
    db.commit()
    write_audit_log(db, actor="system", event_type="wbd_resolve",
                    payload={"task_id": task_id},
                    details={"decision": request.decision, "comment": request.comment})
    return {
        "status": "success",
        "task_id": task_id,
        "message": f"WBD task resolved: {request.decision}",
        "details": {"decision": request.decision, "comment": request.comment,
                     "resolved_at": datetime.utcnow().isoformat()},
    }


@wbd_router.patch(
    "/tasks/{task_id}/assign",
    dependencies=[Depends(require_role(["admin"]))],
)
def assign_wbd_task(task_id: str, request: WBDAssignRequest, Authorization: str = Header(...), db: sqlite3.Connection = Depends(get_db)):
    """Reassign a WBD task. Admin-only."""
    task = db.execute("SELECT id, agent_task_id, domain_hint FROM wbd_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail=f"WBD task {task_id} not found")

    user = db.execute("SELECT id, username, role FROM users WHERE username = ?", (request.assigned_to,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {request.assigned_to} not found")
    if user[2] not in ("wise_authority", "admin"):
        raise HTTPException(status_code=400, detail=f"User {request.assigned_to} is not an authority or admin")

    db.execute(
        "UPDATE wbd_tasks SET assigned_to = ?, notified_at = ? WHERE id = ?",
        (request.assigned_to, datetime.utcnow().isoformat(), task_id),
    )
    db.commit()

    notification_config = _get_notification_config(db, request.assigned_to)
    _fire_notification(request.assigned_to, notification_config, task_id, task[1], task[2])

    actor = get_actor_from_token(Authorization)
    write_audit_log(db, actor=actor, event_type="wbd_reassign",
                    payload={"task_id": task_id}, details={"assigned_to": request.assigned_to})
    return {"status": "reassigned", "task_id": task_id, "assigned_to": request.assigned_to}
