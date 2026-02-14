import hashlib
import json
from datetime import datetime, timezone
from typing import Optional, Any, Dict

from cirisnode.db.pg_pool import get_pg_pool


def sha256_payload(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, (dict, list)):
        payload_str = json.dumps(payload, sort_keys=True)
    else:
        payload_str = str(payload)
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

async def write_audit_log(
    actor: Optional[str],
    event_type: str,
    payload: Optional[Any] = None,
    details: Optional[Dict] = None
):
    payload_sha256 = sha256_payload(payload)
    details_json = json.dumps(details) if details else None
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_logs (timestamp, actor, event_type, payload_sha256, details)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                """,
                datetime.now(timezone.utc), actor, event_type, payload_sha256, details_json
            )
        print(f"Audit log written: event_type={event_type}, actor={actor}, payload_sha256={payload_sha256}")
    except Exception as e:
        print(f"ERROR: Failed to write audit log: {e}")

async def fetch_audit_logs(limit=100, offset=0, actor: Optional[str] = None):
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        if actor is not None:
            rows = await conn.fetch(
                "SELECT id, timestamp, actor, event_type, payload_sha256, details "
                "FROM audit_logs WHERE actor = $1 ORDER BY timestamp DESC LIMIT $2 OFFSET $3",
                actor, limit, offset
            )
        else:
            rows = await conn.fetch(
                "SELECT id, timestamp, actor, event_type, payload_sha256, details "
                "FROM audit_logs ORDER BY timestamp DESC LIMIT $1 OFFSET $2",
                limit, offset
            )
    return [
        {
            "id": row["id"],
            "timestamp": str(row["timestamp"]),
            "actor": row["actor"],
            "event_type": row["event_type"],
            "payload_sha256": row["payload_sha256"],
            "details": row["details"],
        }
        for row in rows
    ]
