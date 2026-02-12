"""
Covenant trace ingestion endpoints with Ed25519 signature verification.

Auth model: agent signs payloads with its Ed25519 key, CIRISNode verifies
against registered public keys AND cross-validates against CIRISRegistry.
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
    org_id: str = ""


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


def _verify_registry_key(org_id: str, key_id: str, public_key_base64: str) -> tuple:
    """Cross-validate a public key against CIRISRegistry.

    Returns (registry_verified: bool, registry_status: str).
    """
    if not org_id:
        return False, "no org_id provided"

    try:
        from cirisnode.services.registry_client import get_registry_client
        client = get_registry_client()
        matches, reason = client.verify_key_matches(org_id, key_id, public_key_base64)
        return matches, reason
    except Exception as e:
        logger.warning(f"Registry validation failed for key_id={key_id}: {e}")
        return False, f"registry unavailable: {e}"


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


def _is_key_registry_verified(key_id: str, conn) -> bool:
    """Check if a key has been verified against the registry."""
    row = conn.execute(
        "SELECT registry_verified FROM covenant_public_keys WHERE key_id = ?",
        (key_id,)
    ).fetchone()
    return bool(row and row[0])


# =========================================================================
# Public Key Registration (with registry cross-validation)
# =========================================================================

@covenant_router.post("/public-keys")
async def register_public_key(
    request: PublicKeyRegistration,
    db=Depends(get_db),
    actor: str = Depends(_require_agent_token),
):
    """
    Register an agent's Ed25519 public key for signature verification.
    Cross-validates against CIRISRegistry if org_id is provided.
    Idempotent — returns 200 if key already registered.
    """
    conn = _get_conn(db)

    # Check if already registered
    existing = conn.execute(
        "SELECT key_id, registry_verified FROM covenant_public_keys WHERE key_id = ?",
        (request.key_id,)
    ).fetchone()
    if existing:
        return {
            "status": "already_registered",
            "key_id": request.key_id,
            "registry_verified": bool(existing[1]),
        }

    # Validate the key is valid Ed25519
    try:
        pubkey_bytes = base64.b64decode(request.public_key_base64)
        ed25519.Ed25519PublicKey.from_public_bytes(pubkey_bytes)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid Ed25519 public key: {e}")

    # Cross-validate against CIRISRegistry
    registry_verified = False
    registry_status = "not checked"
    if request.org_id:
        registry_verified, registry_status = _verify_registry_key(
            request.org_id, request.key_id, request.public_key_base64
        )
        logger.info(
            f"Registry validation for key_id={request.key_id} org_id={request.org_id}: "
            f"verified={registry_verified} reason={registry_status}"
        )

    conn.execute(
        """
        INSERT INTO covenant_public_keys
            (key_id, public_key_base64, algorithm, description, registered_by,
             org_id, registry_verified, registry_status, registered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request.key_id,
            request.public_key_base64,
            request.algorithm,
            request.description,
            actor,
            request.org_id or None,
            1 if registry_verified else 0,
            registry_status,
            datetime.datetime.utcnow(),
        ),
    )
    conn.commit()

    logger.info(
        f"Public key registered: key_id={request.key_id} by={actor} "
        f"registry_verified={registry_verified}"
    )
    return {
        "status": "registered",
        "key_id": request.key_id,
        "registry_verified": registry_verified,
        "registry_status": registry_status,
    }


@covenant_router.get("/public-keys")
async def list_public_keys(
    db=Depends(get_db),
    actor: str = Depends(_require_agent_token),
):
    """List registered public keys with registry verification status."""
    conn = _get_conn(db)
    rows = conn.execute(
        """SELECT key_id, algorithm, description, registered_by, org_id,
                  registry_verified, registry_status, registered_at
           FROM covenant_public_keys ORDER BY registered_at DESC"""
    ).fetchall()
    return [
        {
            "key_id": row[0],
            "algorithm": row[1],
            "description": row[2],
            "registered_by": row[3],
            "org_id": row[4],
            "registry_verified": bool(row[5]),
            "registry_status": row[6],
            "registered_at": str(row[7]),
        }
        for row in rows
    ]


@covenant_router.post("/public-keys/{key_id}/reverify")
async def reverify_public_key(
    key_id: str,
    db=Depends(get_db),
    actor: str = Depends(_require_agent_token),
):
    """Re-check a key against the registry (e.g. after registry key activation)."""
    conn = _get_conn(db)

    row = conn.execute(
        "SELECT public_key_base64, org_id FROM covenant_public_keys WHERE key_id = ?",
        (key_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Key not found")

    public_key_base64, org_id = row[0], row[1]
    if not org_id:
        return {"status": "no_org_id", "key_id": key_id, "registry_verified": False}

    registry_verified, registry_status = _verify_registry_key(org_id, key_id, public_key_base64)

    conn.execute(
        "UPDATE covenant_public_keys SET registry_verified = ?, registry_status = ? WHERE key_id = ?",
        (1 if registry_verified else 0, registry_status, key_id),
    )
    conn.commit()

    return {
        "status": "reverified",
        "key_id": key_id,
        "registry_verified": registry_verified,
        "registry_status": registry_status,
    }


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
    registry_verified_count = 0

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
            # Check if the signing key is also registry-verified
            if _is_key_registry_verified(verified_key_id, conn):
                registry_verified_count += 1

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
        "events_registry_verified": registry_verified_count,
    }


@covenant_router.get("/events")
async def list_covenant_events(
    agent_uid: Optional[str] = None,
    trace_level: Optional[str] = None,
    verified_only: bool = False,
    registry_verified_only: bool = False,
    limit: int = 100,
    db=Depends(get_db),
    actor: str = Depends(_require_agent_token),
):
    """List covenant trace events with optional filtering."""
    conn = _get_conn(db)
    query = """SELECT ct.id, ct.agent_uid, ct.trace_id, ct.thought_id, ct.task_id,
                      ct.trace_level, ct.trace_json, ct.content_hash,
                      ct.signature_verified, ct.signing_key_id, ct.received_at,
                      COALESCE(cpk.registry_verified, 0) as registry_verified
               FROM covenant_traces ct
               LEFT JOIN covenant_public_keys cpk ON ct.signing_key_id = cpk.key_id
               WHERE 1=1"""
    params: list = []

    if agent_uid:
        query += " AND ct.agent_uid = ?"
        params.append(agent_uid)
    if trace_level:
        query += " AND ct.trace_level = ?"
        params.append(trace_level)
    if verified_only:
        query += " AND ct.signature_verified = 1"
    if registry_verified_only:
        query += " AND cpk.registry_verified = 1"

    query += " ORDER BY ct.received_at DESC LIMIT ?"
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
            "registry_verified": bool(row[11]),
        }
        for row in rows
    ]
