"""WBD router at /api/v1/wbd — delegates to the wa_router's implementation.

The frontend uses /api/v1/wbd/tasks while the agent-facing API uses /api/v1/wbd/submit.
Both /wbd/submit and /wa/submit share the same signature-based auth logic.

Auth model: agents sign deferrals with their Ed25519 key. Keys are registered
via CIRISPortal (portal.ciris.ai) → CIRISRegistry. Unsigned submissions rejected.
"""
from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
from datetime import datetime, timezone

from cirisnode.db.pg_pool import get_pg_pool
from cirisnode.utils.encryption import decrypt_data
from cirisnode.utils.audit import write_audit_log
from cirisnode.auth.dependencies import require_role, get_current_role, get_actor_from_token
from cirisnode.api.wa.routes import (
    WBDSubmitRequest,
    WBDResolveRequest,
    WBDAssignRequest,
    _get_notification_config,
    _fire_notification,
    submit_wbd_task as _wa_submit_wbd_task,
)
import logging

logger = logging.getLogger(__name__)

wbd_router = APIRouter(prefix="/api/v1/wbd", tags=["wbd"])


@wbd_router.post("/submit", response_model=dict)
async def submit_wbd_task(request: WBDSubmitRequest):
    """Submit a new WBD task. Delegates to wa_router's signature-verified implementation."""
    return await _wa_submit_wbd_task(request)


@wbd_router.get("/tasks")
async def get_wbd_tasks(
    state: Optional[str] = None,
    since: Optional[str] = None,
    role: str = Depends(get_current_role),
    Authorization: str = Header(default=""),
):
    """List WBD tasks. Authorities see only their assigned or unassigned tasks."""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            # SLA auto-escalation
            open_tasks = await conn.fetch(
                "SELECT id FROM wbd_tasks WHERE status = 'open' AND created_at < (NOW() - INTERVAL '24 hours')"
            )
            for task in open_tasks:
                tid = task["id"]
                await conn.execute("UPDATE wbd_tasks SET status = 'sla_breached' WHERE id = $1", tid)
                await write_audit_log(actor="system", event_type="wbd_sla_breach",
                                      payload={"task_id": tid}, details={"reason": "SLA breach (24h)"})

            query = "SELECT id, agent_task_id, payload, status, created_at, decision, comment, resolved_at, assigned_to, domain_hint, notified_at FROM wbd_tasks WHERE 1=1"
            params: list = []
            param_idx = 1

            if role == "wise_authority":
                actor = get_actor_from_token(Authorization)
                query += f" AND (assigned_to = ${param_idx} OR assigned_to IS NULL)"
                params.append(actor)
                param_idx += 1

            if state:
                query += f" AND status = ${param_idx}"
                params.append(state)
                param_idx += 1
            if since:
                query += f" AND created_at >= ${param_idx}"
                params.append(since)
                param_idx += 1

            rows = await conn.fetch(query, *params)

        tasks = []
        for r in rows:
            try:
                payload = decrypt_data(r["payload"]) if r["payload"] else ""
            except Exception:
                payload = r["payload"] or ""
            tasks.append({
                "id": r["id"],
                "agent_task_id": r["agent_task_id"],
                "payload": payload,
                "status": r["status"],
                "created_at": str(r["created_at"]),
                "decision": r["decision"],
                "comment": r["comment"],
                "resolved_at": str(r["resolved_at"]) if r["resolved_at"] else None,
                "assigned_to": r["assigned_to"],
                "domain_hint": r["domain_hint"],
                "notified_at": str(r["notified_at"]) if r["notified_at"] else None,
            })
        return {"tasks": tasks}
    except Exception:
        logger.exception("Error retrieving WBD tasks")
        raise HTTPException(status_code=500, detail="Internal server error")


@wbd_router.get("/tasks/{task_id}")
async def get_wbd_task(task_id: str):
    """Get a single WBD task by ID. Used by agents to poll resolution status."""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, agent_task_id, payload, status, created_at, decision, comment, resolved_at, assigned_to, domain_hint, notified_at FROM wbd_tasks WHERE id = $1",
                task_id
            )
        if not row:
            raise HTTPException(status_code=404, detail=f"WBD task {task_id} not found")

        try:
            payload = decrypt_data(row["payload"]) if row["payload"] else ""
        except Exception:
            payload = row["payload"] or ""

        return {
            "task": {
                "id": row["id"],
                "agent_task_id": row["agent_task_id"],
                "payload": payload,
                "status": row["status"],
                "created_at": str(row["created_at"]),
                "decision": row["decision"],
                "comment": row["comment"],
                "resolved_at": str(row["resolved_at"]) if row["resolved_at"] else None,
                "assigned_to": row["assigned_to"],
                "domain_hint": row["domain_hint"],
                "notified_at": str(row["notified_at"]) if row["notified_at"] else None,
            }
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error retrieving WBD task %s", task_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@wbd_router.post(
    "/tasks/{task_id}/resolve",
    dependencies=[Depends(require_role(["admin", "wise_authority"]))],
)
async def resolve_wbd_task(
    task_id: str,
    request: WBDResolveRequest,
    Authorization: str = Header(...),
):
    if request.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="Decision must be 'approve' or 'reject'")
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        task = await conn.fetchrow("SELECT id, assigned_to FROM wbd_tasks WHERE id = $1", task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"WBD task {task_id} not found")

        # Extract actual resolver identity from JWT
        actor = get_actor_from_token(Authorization)

        await conn.execute(
            "UPDATE wbd_tasks SET status = 'resolved', decision = $1, comment = $2, resolved_at = $3 WHERE id = $4",
            request.decision, request.comment, datetime.now(timezone.utc), task_id,
        )
    await write_audit_log(actor=actor, event_type="wbd_resolve",
                          payload={"task_id": task_id},
                          details={"decision": request.decision, "comment": request.comment})
    return {
        "status": "success",
        "task_id": task_id,
        "message": f"WBD task resolved: {request.decision}",
        "details": {"decision": request.decision, "comment": request.comment,
                     "resolved_at": datetime.now(timezone.utc).isoformat()},
    }


@wbd_router.patch(
    "/tasks/{task_id}/assign",
    dependencies=[Depends(require_role(["admin"]))],
)
async def assign_wbd_task(task_id: str, request: WBDAssignRequest, Authorization: str = Header(...)):
    """Reassign a WBD task. Admin-only."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        task = await conn.fetchrow("SELECT id, agent_task_id, domain_hint FROM wbd_tasks WHERE id = $1", task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"WBD task {task_id} not found")

        user = await conn.fetchrow("SELECT id, username, role FROM users WHERE username = $1", request.assigned_to)
        if not user:
            raise HTTPException(status_code=404, detail=f"User {request.assigned_to} not found")
        if user["role"] not in ("wise_authority", "admin"):
            raise HTTPException(status_code=400, detail=f"User {request.assigned_to} is not an authority or admin")

        await conn.execute(
            "UPDATE wbd_tasks SET assigned_to = $1, notified_at = $2 WHERE id = $3",
            request.assigned_to, datetime.now(timezone.utc), task_id,
        )

        notification_config = await _get_notification_config(conn, request.assigned_to)
        _fire_notification(request.assigned_to, notification_config, task_id, task["agent_task_id"], task["domain_hint"])

    actor = get_actor_from_token(Authorization)
    await write_audit_log(actor=actor, event_type="wbd_reassign",
                          payload={"task_id": task_id}, details={"assigned_to": request.assigned_to})
    return {"status": "reassigned", "task_id": task_id, "assigned_to": request.assigned_to}
