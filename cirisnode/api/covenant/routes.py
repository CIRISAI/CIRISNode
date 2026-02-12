"""
Covenant trace ingestion endpoints with Ed25519 signature verification.

Auth model: agent signs payloads with its Ed25519 key, CIRISNode verifies
against registered public keys (and optionally CIRISRegistry).
"""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from cirisnode.database import get_db
from cryptography.hazmat.primitives.asymmetric import ed25519
import base64
import uuid
import datetime
import json
import hashlib
import logging

logger = logging.getLogger(__name__)

covenant_router = APIRouter(prefix="/api/v1/covenant", tags=["covenant"])


# =========================================================================
# Request Models
# =========================================================================

class CovenantBatchRequest(BaseModel):
    events: List[Dict[str, Any]]
    batch_timestamp: str
    trace_level: str = "generic"
    correlation_metadata: Optional[Dict[str, str]] = None


class PublicKeyRegistration(BaseModel):
    key_id: str
    public_key_base64: str
    algorithm: str = "ed25519"
    description: str = ""


# =========================================================================
# Helpers
# =========================================================================

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


def _verify_trace_signature(trace: Dict[str, Any], conn) -> Optional[str]:
    """Verify Ed25519 signature on a trace against registered public keys.

    Returns the key_id if verified, None if no signature or verification fails.
    """
    signature_b64 = trace.get("signature")
    key_id = trace.get("signature_key_id")

    if not signature_b64 or not key_id:
        return None

    # Look up registered public key
    row = conn.execute(
        "SELECT public_key_base64 FROM covenant_public_keys WHERE key_id = ? AND algorithm = 'ed25519'",
        (key_id,)
    ).fetchone()
    if not row:
        logger.warning(f"Unknown signing key_id: {key_id}")
        return None

    try:
        # Decode public key
        pubkey_bytes = base64.b64decode(row[0])
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(pubkey_bytes)

        # Reconstruct the canonical signed message (same as agent's sign_trace)
        components = trace.get("components", [])
        signed_payload = {
            "components": components,
            "trace_level": trace.get("trace_level"),
        }
        message = json.dumps(signed_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

        # Decode signature (handle both standard and URL-safe base64)
        sig_b64 = signature_b64
        # Add padding if needed
        padding = 4 - len(sig_b64) % 4
        if padding != 4:
            sig_b64 += "=" * padding
        try:
            sig_bytes = base64.urlsafe_b64decode(sig_b64)
        except Exception:
            sig_bytes = base64.b64decode(sig_b64)

        # Verify
        public_key.verify(sig_bytes, message)
        return key_id

    except Exception as e:
        logger.warning(f"Signature verification failed for key_id={key_id}: {e}")
        return None


# =========================================================================
# Public Key Registration
# =========================================================================

@covenant_router.post("/public-keys")
async def register_public_key(
    request: PublicKeyRegistration,
    db=Depends(get_db),
    actor: str = Depends(_require_agent_token),
):
    """
    Register an agent's Ed25519 public key for signature verification.
    Idempotent — returns 200 if key already registered.
    """
    conn = _get_conn(db)

    # Check if already registered
    existing = conn.execute(
        "SELECT key_id FROM covenant_public_keys WHERE key_id = ?",
        (request.key_id,)
    ).fetchone()
    if existing:
        return {"status": "already_registered", "key_id": request.key_id}

    # Validate the key is valid Ed25519
    try:
        pubkey_bytes = base64.b64decode(request.public_key_base64)
        ed25519.Ed25519PublicKey.from_public_bytes(pubkey_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Ed25519 public key: {e}")

    conn.execute(
        """
        INSERT INTO covenant_public_keys (key_id, public_key_base64, algorithm, description, registered_by, registered_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            request.key_id,
            request.public_key_base64,
            request.algorithm,
            request.description,
            actor,
            datetime.datetime.utcnow(),
        ),
    )
    conn.commit()

    logger.info(f"Public key registered: key_id={request.key_id} by={actor}")
    return {"status": "registered", "key_id": request.key_id}


@covenant_router.get("/public-keys")
async def list_public_keys(
    db=Depends(get_db),
    actor: str = Depends(_require_agent_token),
):
    """List registered public keys."""
    conn = _get_conn(db)
    rows = conn.execute(
        "SELECT key_id, algorithm, description, registered_by, registered_at FROM covenant_public_keys ORDER BY registered_at DESC"
    ).fetchall()
    return [
        {
            "key_id": row[0],
            "algorithm": row[1],
            "description": row[2],
            "registered_by": row[3],
            "registered_at": str(row[4]),
        }
        for row in rows
    ]


# =========================================================================
# Covenant Events (with signature verification)
# =========================================================================

@covenant_router.post("/events")
async def receive_covenant_events(
    request: CovenantBatchRequest,
    db=Depends(get_db),
    actor: str = Depends(_require_agent_token),
):
    """
    Receive covenant trace events from agents in Lens batch format.
    Verifies Ed25519 signatures on traces against registered public keys.
    Events are write-once (immutable after creation).
    """
    conn = _get_conn(db)
    received = 0
    verified_count = 0

    for event in request.events:
        trace = event.get("trace", {})
        event_id = str(uuid.uuid4())
        event_json = json.dumps(event, sort_keys=True)
        content_hash = hashlib.sha256(event_json.encode("utf-8")).hexdigest()

        # Verify signature if present
        verified_key_id = _verify_trace_signature(trace, conn)
        signature_verified = verified_key_id is not None
        if signature_verified:
            verified_count += 1

        agent_uid = trace.get("agent_id_hash", event.get("agent_uid", ""))
        trace_id = trace.get("trace_id", "")
        thought_id = trace.get("thought_id", "")
        task_id = trace.get("task_id", "")

        conn.execute(
            """
            INSERT INTO covenant_traces
                (id, agent_uid, trace_id, thought_id, task_id, trace_level,
                 trace_json, content_hash, signature_verified, signing_key_id, received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                1 if signature_verified else 0,
                verified_key_id,
                datetime.datetime.utcnow(),
            ),
        )
        received += 1

    conn.commit()
    return {
        "status": "ok",
        "events_received": received,
        "events_verified": verified_count,
    }


@covenant_router.get("/events")
async def list_covenant_events(
    agent_uid: Optional[str] = None,
    trace_level: Optional[str] = None,
    verified_only: bool = False,
    limit: int = 100,
    db=Depends(get_db),
    actor: str = Depends(_require_agent_token),
):
    """List covenant trace events with optional filtering."""
    conn = _get_conn(db)
    query = "SELECT id, agent_uid, trace_id, thought_id, task_id, trace_level, trace_json, content_hash, signature_verified, signing_key_id, received_at FROM covenant_traces WHERE 1=1"
    params: list = []

    if agent_uid:
        query += " AND agent_uid = ?"
        params.append(agent_uid)
    if trace_level:
        query += " AND trace_level = ?"
        params.append(trace_level)
    if verified_only:
        query += " AND signature_verified = 1"

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
            "signature_verified": bool(row[8]),
            "signing_key_id": row[9],
            "received_at": str(row[10]),
        }
        for row in rows
    ]
