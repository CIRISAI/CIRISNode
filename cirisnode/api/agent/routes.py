from fastapi import APIRouter, Depends, HTTPException, Body, Header
from pydantic import BaseModel
from typing import Optional
from cirisnode.database import get_db
import uuid
import datetime
import json

agent_router = APIRouter(prefix="/api/v1/agent", tags=["agent"])

class AgentEventRequest(BaseModel):
    agent_uid: str
    event: dict

@agent_router.post("/events")
async def post_agent_event(
    request: AgentEventRequest,
    db=Depends(get_db),
    x_agent_token: str | None = Header(None)
):
    """
    Agents push Task / Thought / Action events for observability.
    """
    event_id = str(uuid.uuid4())
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    if x_agent_token:
        token_row = conn.execute(
            "SELECT token FROM agent_tokens WHERE token = ?",
            (x_agent_token,)
        ).fetchone()
        if not token_row:
            raise HTTPException(status_code=401, detail="Invalid agent token")
        actor = x_agent_token
    else:
        actor = request.agent_uid
    conn.execute(
        """
        INSERT INTO agent_events (id, node_ts, agent_uid, event_json)
        VALUES (?, ?, ?, ?)
        """,
        (event_id, datetime.datetime.utcnow(), request.agent_uid, json.dumps(request.event))
    )
    conn.commit()
    # Write audit log
    try:
        from cirisnode.utils.audit import write_audit_log
        write_audit_log(
            db=conn,
            actor=actor,
            event_type="agent_event",
            payload={"event_id": event_id},
            details=request.event
        )
    except Exception as e:
        print(f"WARNING: Failed to write audit log for agent_event: {e}")
    return {"id": event_id, "status": "ok"}

@agent_router.get("/events")
async def get_agent_events(db=Depends(get_db)):
    """
    List all agent events.
    """
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    cur = conn.execute(
        "SELECT id, node_ts, agent_uid, event_json FROM agent_events ORDER BY node_ts DESC"
    )
    rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "node_ts": str(row[1]),
            "agent_uid": row[2],
            "event": json.loads(row[3]) if row[3] else None
        }
        for row in rows
    ]

@agent_router.delete("/events/{event_id}")
async def delete_agent_event(event_id: str, db=Depends(get_db)):
    """
    Delete an agent event by ID.
    """
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    conn.execute("DELETE FROM agent_events WHERE id = ?", (event_id,))
    conn.commit()
    return {"id": event_id, "status": "deleted"}

@agent_router.patch("/events/{event_id}/archive")
async def archive_agent_event(event_id: str, archived: bool, db=Depends(get_db)):
    """
    Archive or unarchive an agent event by ID.
    """
    conn = next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db
    conn.execute("UPDATE agent_events SET archived = ? WHERE id = ?", (1 if archived else 0, event_id))
    conn.commit()
    return {"id": event_id, "archived": archived}
