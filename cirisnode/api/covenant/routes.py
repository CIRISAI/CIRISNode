from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from cirisnode.database import get_db
import uuid
import datetime
import json
import hashlib

covenant_router = APIRouter(prefix="/api/v1/covenant", tags=["covenant"])


class CovenantBatchRequest(BaseModel):
    events: List[Dict[str, Any]]
    batch_timestamp: str
    trace_level: str = "generic"
    correlation_metadata: Optional[Dict[str, str]] = None


def _get_conn(db):
    """Unwrap the DB dependency to a connection."""
    return next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db


def _require_agent_token(
    x_agent_token: str = Header(..., alias="x-agent-token"),
    db=Depends(get_db),
) -> str:
    """Validate agent token. Returns the token as actor identifier."""
    conn = _get_conn(db)
    token_row = conn.execute(
        "SELECT token, owner FROM agent_tokens WHERE token = ?",
        (x_agent_token,)
    ).fetchone()
    if not token_row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token")
    return x_agent_token


@covenant_router.post("/events")
async def receive_covenant_events(
    request: CovenantBatchRequest,
    db=Depends(get_db),
    actor: str = Depends(_require_agent_token),
):
    """
    Receive covenant trace events from agents in Lens batch format.
    Requires valid agent token via X-Agent-Token header.
    Events are write-once (immutable after creation).
    """
    conn = _get_conn(db)
    received = 0
    for event in request.events:
        trace = event.get("trace", {})
        event_id = str(uuid.uuid4())
        event_json = json.dumps(event, sort_keys=True)
        content_hash = hashlib.sha256(event_json.encode("utf-8")).hexdigest()

        agent_uid = trace.get("agent_id_hash", event.get("agent_uid", ""))
        trace_id = trace.get("trace_id", "")
        thought_id = trace.get("thought_id", "")
        task_id = trace.get("task_id", "")

        conn.execute(
            """
            INSERT INTO covenant_traces
                (id, agent_uid, trace_id, thought_id, task_id, trace_level, trace_json, content_hash, received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                agent_uid,
                trace_id,
                thought_id,
                task_id,
                request.trace_level,
                event_json,
                content_hash,
                datetime.datetime.utcnow(),
            ),
        )
        received += 1

    conn.commit()
    return {"status": "ok", "events_received": received}


@covenant_router.get("/events")
async def list_covenant_events(
    agent_uid: Optional[str] = None,
    trace_level: Optional[str] = None,
    limit: int = 100,
    db=Depends(get_db),
    actor: str = Depends(_require_agent_token),
):
    """List covenant trace events with optional filtering."""
    conn = _get_conn(db)
    query = "SELECT id, agent_uid, trace_id, thought_id, task_id, trace_level, trace_json, content_hash, received_at FROM covenant_traces WHERE 1=1"
    params: list = []

    if agent_uid:
        query += " AND agent_uid = ?"
        params.append(agent_uid)
    if trace_level:
        query += " AND trace_level = ?"
        params.append(trace_level)

    query += " ORDER BY received_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [
        {
            "id": row[0],
            "agent_uid": row[1],
            "trace_id": row[2],
            "thought_id": row[3],
            "task_id": row[4],
            "trace_level": row[5],
            "trace": json.loads(row[6]) if row[6] else None,
            "content_hash": row[7],
            "received_at": str(row[8]),
        }
        for row in rows
    ]
