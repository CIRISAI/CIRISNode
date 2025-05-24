import hashlib
import json
from datetime import datetime
from typing import Optional, Any, Dict

from cirisnode.database import get_db

def sha256_payload(payload: Any) -> str:
    if payload is None:
        return ""
    if isinstance(payload, (dict, list)):
        payload_str = json.dumps(payload, sort_keys=True)
    else:
        payload_str = str(payload)
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

def write_audit_log(
    db,
    actor: Optional[str],
    event_type: str,
    payload: Optional[Any] = None,
    details: Optional[Dict] = None
):
    payload_sha256 = sha256_payload(payload)
    details_json = json.dumps(details) if details else None
    try:
        db.execute(
            """
            INSERT INTO audit_logs (timestamp, actor, event_type, payload_sha256, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (datetime.utcnow(), actor, event_type, payload_sha256, details_json)
        )
        db.commit()
        print(f"Audit log written: event_type={event_type}, actor={actor}, payload_sha256={payload_sha256}")
    except Exception as e:
        print(f"ERROR: Failed to write audit log: {e}")

def fetch_audit_logs(db, limit=100, offset=0, actor: Optional[str] = None):
    query = (
        "SELECT id, timestamp, actor, event_type, payload_sha256, details FROM audit_logs"
    )
    params = []
    if actor is not None:
        query += " WHERE actor = ?"
        params.append(actor)
    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cur = db.execute(query, params)
    rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "timestamp": row[1],  # Already a string in SQLite
            "actor": row[2],
            "event_type": row[3],
            "payload_sha256": row[4],
            "details": row[5],
        }
        for row in rows
    ]
