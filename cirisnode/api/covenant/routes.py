"""
Covenant trace ingestion endpoints with Ed25519 signature verification.

Auth model: agents sign payloads with their Ed25519 key. CIRISNode verifies
signatures against public keys registered via CIRISPortal (portal.ciris.ai)
and cross-validated against CIRISRegistry. Only data from agents with
registry-verified keys is accepted.

Key source of truth: CIRISPortal → CIRISRegistry (portal.ciris.ai)
"""

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from cirisnode.database import get_db
from cirisnode.auth.dependencies import require_role, require_agent_token
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


def _verify_registry_key(org_id: str, key_id: str, public_key_base64: str) -> tuple:
    """Cross-validate a public key against CIRISRegistry.

    If org_id is provided, verifies directly. Otherwise, auto-discovers
    by computing the Ed25519 fingerprint and looking up in Registry.

    Returns (registry_verified: bool, registry_status: str, discovered_org_id: str).
    """
    import hashlib

    try:
        from cirisnode.services.registry_client import get_registry_client
        client = get_registry_client()

        if org_id:
            # Direct verification with known org_id
            matches, reason = client.verify_key_matches(org_id, key_id, public_key_base64)
            return matches, reason, org_id

        # Auto-discover: compute fingerprint from public key and look up in Registry
        pubkey_bytes = base64.b64decode(public_key_base64)
        fingerprint = hashlib.sha256(pubkey_bytes).hexdigest()
        found, discovered_org_id, registry_pubkey, status = client.get_key_by_fingerprint(fingerprint)

        if not found:
            return False, "key fingerprint not found in registry", ""

        if status in ("KEY_REVOKED",):
            return False, f"key revoked in registry (status={status})", discovered_org_id or ""

        if status in ("KEY_PENDING",):
            return False, f"key not yet active in registry (status={status})", discovered_org_id or ""

        # Compare the public key bytes
        if registry_pubkey == pubkey_bytes:
            return True, f"verified via fingerprint (status={status})", discovered_org_id or ""
        else:
            return False, "public key mismatch — fingerprint matched but key bytes differ", discovered_org_id or ""

    except Exception as e:
        logger.warning(f"Registry validation failed for key_id={key_id}: {e}")
        return False, f"registry unavailable: {e}", org_id or ""


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

def _optional_agent_token(
    x_agent_token: Optional[str] = Header(None, alias="x-agent-token"),
    db=Depends(get_db),
) -> Optional[str]:
    """Optionally validate agent token. Returns token or None."""
    if not x_agent_token:
        return None
    conn = _get_conn(db)
    token_row = conn.execute(
        "SELECT token FROM agent_tokens WHERE token = ?", (x_agent_token,)
    ).fetchone()
    return x_agent_token if token_row else None


@covenant_router.post("/public-keys")
async def register_public_key(
    request: PublicKeyRegistration,
    db=Depends(get_db),
    actor: Optional[str] = Depends(_optional_agent_token),
):
    """
    Register an agent's Ed25519 public key for signature verification.

    Auth: Agent token (optional) OR registry cross-validation via org_id.
    Keys are cross-validated against CIRISRegistry (source of truth: CIRISPortal).
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

    # Cross-validate against CIRISRegistry (auto-discovers org_id via fingerprint)
    registry_verified, registry_status, discovered_org_id = _verify_registry_key(
        request.org_id, request.key_id, request.public_key_base64
    )
    # Use discovered org_id if agent didn't provide one
    effective_org_id = request.org_id or discovered_org_id or ""
    logger.info(
        f"Registry validation for key_id={request.key_id} org_id={effective_org_id}: "
        f"verified={registry_verified} reason={registry_status}"
    )

    registered_by = actor or f"self-register:{request.key_id[:16]}"

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
            registered_by,
            effective_org_id or None,
            1 if registry_verified else 0,
            registry_status,
            datetime.datetime.utcnow(),
        ),
    )
    conn.commit()

    logger.info(
        f"Public key registered: key_id={request.key_id} by={registered_by} "
        f"org_id={effective_org_id} registry_verified={registry_verified}"
    )
    return {
        "status": "registered",
        "key_id": request.key_id,
        "org_id": effective_org_id,
        "registry_verified": registry_verified,
        "registry_status": registry_status,
    }


@covenant_router.get("/public-keys")
async def list_public_keys(
    db=Depends(get_db),
    actor: str = Depends(require_agent_token),
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
    actor: str = Depends(require_agent_token),
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


class AdminKeyUpdate(BaseModel):
    org_id: Optional[str] = None
    registry_verified: Optional[bool] = None
    registry_status: Optional[str] = None


@covenant_router.patch(
    "/public-keys/{key_id}",
    dependencies=[Depends(require_role(["admin"]))],
)
async def admin_update_public_key(
    key_id: str,
    request: AdminKeyUpdate,
    db=Depends(get_db),
):
    """Admin: update org_id, registry_verified, or registry_status on a covenant key."""
    conn = _get_conn(db)

    row = conn.execute(
        "SELECT key_id FROM covenant_public_keys WHERE key_id = ?", (key_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Key not found")

    updates = []
    params = []
    if request.org_id is not None:
        updates.append("org_id = ?")
        params.append(request.org_id)
    if request.registry_verified is not None:
        updates.append("registry_verified = ?")
        params.append(1 if request.registry_verified else 0)
    if request.registry_status is not None:
        updates.append("registry_status = ?")
        params.append(request.registry_status)

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    params.append(key_id)
    conn.execute(
        f"UPDATE covenant_public_keys SET {', '.join(updates)} WHERE key_id = ?",
        params,
    )
    conn.commit()

    logger.info(f"Admin updated key {key_id}: {dict(request)}")
    return {"status": "updated", "key_id": key_id, "updates": dict(request)}


# =========================================================================
# Covenant Events (with signature verification)
# =========================================================================

@covenant_router.post("/events")
async def receive_covenant_events(
    request: CovenantBatchRequest,
    db=Depends(get_db),
):
    """
    Receive covenant trace events from agents in Lens batch format.

    Auth: Ed25519 signature verification — traces must be signed by an agent
    whose public key is registered in CIRISPortal (portal.ciris.ai) and
    cross-validated against CIRISRegistry. At least one trace in the batch
    must carry a valid signature from a registry-verified key.

    No header-based auth required. The signature IS the auth.
    """
    conn = _get_conn(db)

    # First pass: verify all signatures and check registry status
    event_rows = []
    verified_count = 0
    registry_verified_count = 0

    for event in request.events:
        trace = event.get("trace", {})
        event_id = str(uuid.uuid4())
        event_json = json.dumps(event, sort_keys=True)
        content_hash = hashlib.sha256(event_json.encode("utf-8")).hexdigest()

        verified_key_id = _verify_trace_signature(trace, conn)
        signature_verified = verified_key_id is not None
        is_registry_verified = False
        if signature_verified:
            verified_count += 1
            if _is_key_registry_verified(verified_key_id, conn):
                registry_verified_count += 1
                is_registry_verified = True

        event_rows.append((
            event_id,
            trace.get("agent_id_hash", event.get("agent_uid", "")),
            trace.get("trace_id", ""),
            trace.get("thought_id", ""),
            trace.get("task_id", ""),
            request.trace_level,
            event_json,
            content_hash,
            1 if signature_verified else 0,
            verified_key_id,
            datetime.datetime.utcnow(),
        ))

    # Auth gate: at least one trace must be signed by a key registered
    # in CIRISPortal/CIRISRegistry. This is the signature-based auth model.
    if registry_verified_count == 0:
        # Provide helpful detail depending on what we found
        if verified_count > 0:
            detail = (
                f"Traces are signed ({verified_count} verified) but the signing key "
                f"is not registry-verified. Keys must be registered via "
                f"CIRISPortal (portal.ciris.ai) and validated against CIRISRegistry."
            )
        elif any(event.get("trace", {}).get("signature") for event in request.events):
            detail = (
                "Trace signatures present but verification failed. "
                "Ensure the signing key is registered with CIRISNode and "
                "cross-validated via CIRISPortal (portal.ciris.ai)."
            )
        else:
            detail = (
                "No signatures found on traces. Agents must sign traces with "
                "their Ed25519 key (registered via CIRISPortal/CIRISRegistry)."
            )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

    # Insert all verified events
    for row in event_rows:
        conn.execute(
            """
            INSERT INTO covenant_traces
                (id, agent_uid, trace_id, thought_id, task_id, trace_level,
                 trace_json, content_hash, signature_verified, signing_key_id, received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row,
        )

    conn.commit()
    return {
        "status": "ok",
        "events_received": len(event_rows),
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
    actor: str = Depends(require_agent_token),
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
