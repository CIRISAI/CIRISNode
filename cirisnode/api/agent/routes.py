from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel
from cirisnode.database import get_db
from cirisnode.auth.dependencies import require_role, require_agent_token
from cirisnode.utils.audit import write_audit_log, sha256_payload
import uuid
import datetime
import json
import hashlib

agent_router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


class AgentEventRequest(BaseModel):
    agent_uid: str
    event: dict


def _get_conn(db):
    """Unwrap the DB dependency to a connection."""
    return next(db) if hasattr(db, "__iter__") and not isinstance(db, (str, bytes)) else db


def _hash_event_json(event_json: str) -> str:
    """SHA-256 hash of event JSON content."""
    return hashlib.sha256(event_json.encode("utf-8")).hexdigest()


@agent_router.post("/events")
async def post_agent_event(
    request: AgentEventRequest,
    db=Depends(get_db),
    actor: str = Depends(require_agent_token),
):
    """
    Agents push Task / Thought / Action events for observability.
    Requires valid agent token via X-Agent-Token header.
    Events are write-once (immutable after creation).
    """
    event_id = str(uuid.uuid4())
    conn = _get_conn(db)
    event_json = json.dumps(request.event, sort_keys=True)
    content_hash = _hash_event_json(event_json)
    conn.execute(
        """
        INSERT INTO agent_events (id, node_ts, agent_uid, event_json, original_content_hash)
        VALUES (?, ?, ?, ?, ?)
        """,
        (event_id, datetime.datetime.utcnow(), request.agent_uid, event_json, content_hash)
    )
    conn.commit()
    try:
        write_audit_log(
            db=conn,
            actor=actor,
            event_type="agent_event_create",
            payload={"event_id": event_id, "agent_uid": request.agent_uid},
            details=request.event,
        )
    except Exception as e:
        print(f"WARNING: Failed to write audit log for agent_event: {e}")
    return {"id": event_id, "content_hash": content_hash, "status": "ok"}


@agent_router.get("/events")
async def get_agent_events(
    db=Depends(get_db),
    actor: str = Depends(require_agent_token),
):
    """
    List agent events. Requires valid agent token.
    Soft-deleted events are excluded.
    """
    conn = _get_conn(db)
    cur = conn.execute(
        "SELECT id, node_ts, agent_uid, event_json, original_content_hash "
        "FROM agent_events WHERE deleted = 0 ORDER BY node_ts DESC"
    )
    rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "node_ts": str(row[1]),
            "agent_uid": row[2],
            "event": json.loads(row[3]) if row[3] else None,
            "content_hash": row[4],
        }
        for row in rows
    ]


@agent_router.delete(
    "/events/{event_id}",
    dependencies=[Depends(require_role(["admin"]))],
)
async def delete_agent_event(event_id: str, db=Depends(get_db)):
    """
    Soft-delete an agent event. Admin only.
    The original content hash is preserved for audit trail.
    Events are never physically deleted — only marked deleted.
    """
    conn = _get_conn(db)
    row = conn.execute(
        "SELECT event_json, original_content_hash FROM agent_events WHERE id = ?",
        (event_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")
    # Ensure hash is stored if it wasn't before (pre-migration events)
    content_hash = row[1] or _hash_event_json(row[0]) if row[0] else None
    conn.execute(
        """
        UPDATE agent_events
        SET deleted = 1, deleted_by = 'admin', deleted_at = ?,
            original_content_hash = COALESCE(original_content_hash, ?)
        WHERE id = ?
        """,
        (datetime.datetime.utcnow(), content_hash, event_id)
    )
    conn.commit()
    try:
        write_audit_log(
            db=conn,
            actor="admin",
            event_type="agent_event_delete",
            payload={"event_id": event_id, "original_content_hash": content_hash},
        )
    except Exception as e:
        print(f"WARNING: Failed to write audit log for agent_event_delete: {e}")
    return {"id": event_id, "original_content_hash": content_hash, "status": "soft_deleted"}


@agent_router.patch(
    "/events/{event_id}/archive",
    dependencies=[Depends(require_role(["admin"]))],
)
async def archive_agent_event(event_id: str, archived: bool, db=Depends(get_db)):
    """
    Archive or unarchive an agent event. Admin only.
    The original content hash is preserved — this is a metadata-only update.
    """
    conn = _get_conn(db)
    row = conn.execute(
        "SELECT event_json, original_content_hash FROM agent_events WHERE id = ?",
        (event_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")
    content_hash = row[1] or _hash_event_json(row[0]) if row[0] else None
    conn.execute(
        """
        UPDATE agent_events
        SET archived = ?, archived_by = 'admin', archived_at = ?,
            original_content_hash = COALESCE(original_content_hash, ?)
        WHERE id = ?
        """,
        (1 if archived else 0, datetime.datetime.utcnow(), content_hash, event_id)
    )
    conn.commit()
    try:
        write_audit_log(
            db=conn,
            actor="admin",
            event_type="agent_event_archive",
            payload={"event_id": event_id, "archived": archived, "original_content_hash": content_hash},
        )
    except Exception as e:
        print(f"WARNING: Failed to write audit log for agent_event_archive: {e}")
    return {"id": event_id, "archived": archived, "original_content_hash": content_hash}
