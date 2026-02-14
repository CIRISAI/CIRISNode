from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from cirisnode.db.pg_pool import get_pg_pool
from cirisnode.auth.dependencies import require_role, require_agent_token, decode_jwt
from cirisnode.utils.audit import write_audit_log
import uuid
import datetime
import json
import hashlib

agent_router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


class AgentEventRequest(BaseModel):
    agent_uid: str
    event: dict


def _hash_event_json(event_json: str) -> str:
    """SHA-256 hash of event JSON content."""
    return hashlib.sha256(event_json.encode("utf-8")).hexdigest()


@agent_router.post("/events")
async def post_agent_event(
    request: AgentEventRequest,
    actor: str = Depends(require_agent_token),
):
    """
    Agents push Task / Thought / Action events for observability.
    Requires valid agent token via X-Agent-Token header.
    Events are write-once (immutable after creation).
    """
    event_id = str(uuid.uuid4())
    event_json = json.dumps(request.event, sort_keys=True)
    content_hash = _hash_event_json(event_json)
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO agent_events (id, node_ts, agent_uid, event_json, original_content_hash)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            """,
            event_id, datetime.datetime.now(datetime.timezone.utc), request.agent_uid, event_json, content_hash
        )
    try:
        await write_audit_log(
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
    x_agent_token: Optional[str] = Header(None, alias="x-agent-token"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    List agent events. Requires valid agent token or admin JWT.
    Soft-deleted events are excluded.
    """
    # Accept admin JWT OR agent token
    authed = False
    if authorization and authorization.startswith("Bearer "):
        try:
            payload = decode_jwt(authorization.split(" ", 1)[1])
            if payload and payload.get("role") in ("admin", "wise_authority"):
                authed = True
        except (ValueError, Exception):
            pass
    if not authed and x_agent_token:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT token FROM agent_tokens WHERE token = $1", x_agent_token
            )
        if row:
            authed = True
    if not authed:
        raise HTTPException(status_code=401, detail="Valid agent token or admin JWT required")
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, node_ts, agent_uid, event_json, original_content_hash "
            "FROM agent_events WHERE deleted = 0 ORDER BY node_ts DESC"
        )
    return [
        {
            "id": row["id"],
            "node_ts": str(row["node_ts"]),
            "agent_uid": row["agent_uid"],
            "event": json.loads(row["event_json"]) if isinstance(row["event_json"], str) else row["event_json"],
            "content_hash": row["original_content_hash"],
        }
        for row in rows
    ]


@agent_router.delete(
    "/events/{event_id}",
    dependencies=[Depends(require_role(["admin"]))],
)
async def delete_agent_event(event_id: str):
    """
    Soft-delete an agent event. Admin only.
    The original content hash is preserved for audit trail.
    Events are never physically deleted — only marked deleted.
    """
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT event_json, original_content_hash FROM agent_events WHERE id = $1",
            event_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Event not found")
        event_json_val = row["event_json"]
        if isinstance(event_json_val, dict):
            event_json_val = json.dumps(event_json_val)
        content_hash = row["original_content_hash"] or (_hash_event_json(event_json_val) if event_json_val else None)
        await conn.execute(
            """
            UPDATE agent_events
            SET deleted = 1, deleted_by = 'admin', deleted_at = $1,
                original_content_hash = COALESCE(original_content_hash, $2)
            WHERE id = $3
            """,
            datetime.datetime.now(datetime.timezone.utc), content_hash, event_id
        )
    try:
        await write_audit_log(
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
async def archive_agent_event(event_id: str, archived: bool):
    """
    Archive or unarchive an agent event. Admin only.
    The original content hash is preserved — this is a metadata-only update.
    """
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT event_json, original_content_hash FROM agent_events WHERE id = $1",
            event_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Event not found")
        event_json_val = row["event_json"]
        if isinstance(event_json_val, dict):
            event_json_val = json.dumps(event_json_val)
        content_hash = row["original_content_hash"] or (_hash_event_json(event_json_val) if event_json_val else None)
        await conn.execute(
            """
            UPDATE agent_events
            SET archived = $1, archived_by = 'admin', archived_at = $2,
                original_content_hash = COALESCE(original_content_hash, $3)
            WHERE id = $4
            """,
            archived, datetime.datetime.now(datetime.timezone.utc), content_hash, event_id
        )
    try:
        await write_audit_log(
            actor="admin",
            event_type="agent_event_archive",
            payload={"event_id": event_id, "archived": archived, "original_content_hash": content_hash},
        )
    except Exception as e:
        print(f"WARNING: Failed to write audit log for agent_event_archive: {e}")
    return {"id": event_id, "archived": archived, "original_content_hash": content_hash}
