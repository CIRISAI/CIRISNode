from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, ValidationError
from typing import Optional, Dict, Any, List
from datetime import datetime
from cirisnode.database import get_db
import sqlite3
from cirisnode.utils.encryption import encrypt_data, decrypt_data
import logging

# Setup logging
logger = logging.getLogger(__name__)

wa_router = APIRouter(tags=["wbd"])

# Models for WBD
class WBDSubmitRequest(BaseModel):
    agent_task_id: str
    payload: str

class WBDTask(BaseModel):
    id: int
    agent_task_id: str
    payload: str
    status: str
    created_at: str

class WBDResolveRequest(BaseModel):
    decision: str  # "approve" or "reject"
    comment: Optional[str] = None

@wa_router.post("/submit", response_model=dict)
def submit_wbd_task(request: WBDSubmitRequest, db: sqlite3.Connection = Depends(get_db)):
    """Submit a new WBD task for review."""
    try:
        cursor = db.execute(
            "INSERT INTO wbd_tasks (agent_task_id, payload, status, created_at) VALUES (?, ?, 'open', ?)",
            (request.agent_task_id, encrypt_data(request.payload), datetime.utcnow().isoformat())
        )
        task_id = cursor.lastrowid
        db.commit()
        
        # Log the WBD task submission to audit
        from cirisnode.api.audit.routes import log_audit_event
        event_payload = {
            "action": "submit_wbd_task",
            "task_id": task_id,
            "agent_task_id": request.agent_task_id
        }
        log_audit_event(db, "system", "wbd_submit", event_payload)
        
        logger.info(f"WBD task submitted with ID: {task_id}, Agent Task ID: {request.agent_task_id}")
        return {
            "status": "success",
            "task_id": task_id,
            "message": "WBD task submitted successfully",
            "details": {
                "agent_task_id": request.agent_task_id,
                "payload": request.payload,
                "status": "open",
                "created_at": datetime.utcnow().isoformat(),
            },
        }
    except Exception as e:
        logger.error(f"Error submitting WBD task: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error submitting WBD task: {str(e)}")

@wa_router.get("/tasks", response_model=dict)
def get_wbd_tasks(state: Optional[str] = None, since: Optional[str] = None, db: sqlite3.Connection = Depends(get_db)):
    """List open WBD tasks with optional filters for state and since date. Auto-escalates tasks breaching SLA (24h)."""
    try:
        # Check for SLA breaches (24 hours) and auto-escalate
        sla_threshold = datetime.utcnow().isoformat()
        sla_threshold_dt = datetime.fromisoformat(sla_threshold)
        from datetime import timedelta
        sla_threshold_dt = sla_threshold_dt - timedelta(hours=24)
        sla_threshold = sla_threshold_dt.isoformat()
        
        open_tasks = db.execute("SELECT id, created_at FROM wbd_tasks WHERE status = 'open' AND created_at < ?", (sla_threshold,)).fetchall()
        for task in open_tasks:
            task_id = task[0]
            db.execute("UPDATE wbd_tasks SET status = 'sla_breached' WHERE id = ?", (task_id,))
            # Log the SLA breach to audit
            from cirisnode.api.audit.routes import log_audit_event
            event_payload = {
                "action": "auto_escalate_wbd_task",
                "task_id": task_id,
                "reason": "SLA breach (24h)"
            }
            log_audit_event(db, "system", "wbd_sla_breach", event_payload)
            logger.info(f"WBD task {task_id} auto-escalated due to SLA breach")
        
        db.commit()
        
        # Retrieve tasks with filters
        query = "SELECT id, agent_task_id, payload, status, created_at FROM wbd_tasks WHERE 1=1"
        params = []
        if state:
            query += " AND status = ?"
            params.append(state)
        if since:
            query += " AND created_at >= ?"
            params.append(since)
        
        tasks = db.execute(query, params).fetchall()
        logger.info(f"Retrieved {len(tasks)} WBD tasks with filters state={state}, since={since}")
        return {"tasks": [
            WBDTask(
                id=task[0],
                agent_task_id=task[1],
                payload=decrypt_data(task[2]),
                status=task[3],
                created_at=task[4]
            )
            for task in tasks
        ]}
    except Exception as e:
        logger.error(f"Error retrieving WBD tasks: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error retrieving WBD tasks: {str(e)}")

@wa_router.post("/tasks/{task_id}/resolve", response_model=dict)
def resolve_wbd_task(task_id: int, request: WBDResolveRequest, db: sqlite3.Connection = Depends(get_db), current_user: Dict = Depends(require_admin_scope)): # Changed to require_admin_scope
    """Resolve a WBD task with a decision (approve or reject)."""
    try:
        if request.decision not in ["approve", "reject"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Decision must be 'approve' or 'reject'")

        task = db.execute("SELECT * FROM wbd_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"WBD task with ID {task_id} not found")

        db.execute(
            "UPDATE wbd_tasks SET status = 'resolved', decision = ?, comment = ? WHERE id = ?",
            (request.decision, request.comment, task_id)
        )
        db.commit()
        
        # Log the WBD task resolution to audit
        from cirisnode.api.audit.routes import log_audit_event
        event_payload = {
            "action": "resolve_wbd_task",
            "task_id": task_id,
            "decision": request.decision,
            "comment": request.comment
        }
        log_audit_event(db, current_user.get("sub", "unknown_admin"), "wbd_resolve", event_payload) # Log actor from token
        
        logger.info(f"WBD task {task_id} resolved with decision: {request.decision}")
        return {
            "status": "success",
            "task_id": task_id,
            "message": f"WBD task resolved with decision: {request.decision}",
            "details": {
                "decision": request.decision,
                "comment": request.comment,
                "resolved_at": datetime.utcnow().isoformat(),
            },
        }
    except Exception as e:
        logger.error(f"Error resolving WBD task: {str(e)}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Error resolving WBD task: {str(e)}")
