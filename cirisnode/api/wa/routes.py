from fastapi import APIRouter, HTTPException, status, Depends, Header
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime
from cirisnode.database import get_db
import sqlite3
from cirisnode.utils.encryption import encrypt_data, decrypt_data
from cirisnode.utils.audit import write_audit_log
from cirisnode.auth.dependencies import require_role, get_current_role, get_actor_from_token
from cryptography.hazmat.primitives.asymmetric import ed25519
import base64
import uuid
import json
import hashlib
import logging
import asyncio

# Setup logging
logger = logging.getLogger(__name__)

wa_router = APIRouter(prefix="/api/v1/wa", tags=["wa"])

# Models for WBD
class WBDSubmitRequest(BaseModel):
    agent_task_id: str
    payload: str
    domain_hint: Optional[str] = None
    signature: Optional[str] = None          # Ed25519 signature (base64url, no padding)
    signature_key_id: Optional[str] = None   # Key ID registered via CIRISPortal/CIRISRegistry

class WBDTask(BaseModel):
    id: int
    agent_task_id: str
    payload: str
    status: str
    created_at: str
    assigned_to: Optional[str] = None
    domain_hint: Optional[str] = None
    notified_at: Optional[str] = None

class WBDResolveRequest(BaseModel):
    decision: str  # "approve" or "reject"
    comment: Optional[str] = None

class WBDAssignRequest(BaseModel):
    assigned_to: str

class DeferralRequest(BaseModel):
    deferral_type: str = None
    reason: str = None
    target_object: str = None
    signature: Optional[str] = None
    signature_key_id: Optional[str] = None


def _verify_wbd_signature(request: WBDSubmitRequest, conn) -> Optional[str]:
    """Verify Ed25519 signature on a WBD deferral submission.

    The signed message is canonical JSON of the submission content
    (agent_task_id + payload + domain_hint), sorted keys, compact separators.
    Keys must be registered via CIRISPortal (portal.ciris.ai) → CIRISRegistry.

    Returns the key_id if verified AND registry-verified, None otherwise.
    """
    if not request.signature or not request.signature_key_id:
        return None

    # Look up registered public key
    row = conn.execute(
        "SELECT public_key_base64, registry_verified FROM covenant_public_keys "
        "WHERE key_id = ? AND algorithm = 'ed25519'",
        (request.signature_key_id,)
    ).fetchone()
    if not row:
        logger.warning(f"WBD submit: unknown signing key_id: {request.signature_key_id}")
        return None

    public_key_base64, registry_verified = row[0], row[1]

    # Key must be registry-verified (registered via CIRISPortal/CIRISRegistry)
    if not registry_verified:
        logger.warning(
            f"WBD submit: key_id={request.signature_key_id} is not registry-verified. "
            f"Keys must be registered via CIRISPortal (portal.ciris.ai)."
        )
        return None

    try:
        pubkey_bytes = base64.b64decode(public_key_base64)
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(pubkey_bytes)

        # Reconstruct canonical signed message (same format as agent)
        signed_payload: Dict[str, Any] = {
            "agent_task_id": request.agent_task_id,
            "payload": request.payload,
        }
        if request.domain_hint:
            signed_payload["domain_hint"] = request.domain_hint
        message = json.dumps(signed_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

        # Decode signature (URL-safe base64 without padding)
        sig_b64 = request.signature
        padding = 4 - len(sig_b64) % 4
        if padding != 4:
            sig_b64 += "=" * padding
        try:
            sig_bytes = base64.urlsafe_b64decode(sig_b64)
        except Exception:
            sig_bytes = base64.b64decode(sig_b64)

        public_key.verify(sig_bytes, message)
        logger.info(f"WBD submit signature verified: key_id={request.signature_key_id}")
        return request.signature_key_id

    except Exception as e:
        logger.warning(f"WBD signature verification failed for key_id={request.signature_key_id}: {e}")
        return None


def _route_wbd_task(conn, domain_hint: Optional[str], agent_task_id: Optional[str] = None) -> Optional[str]:
    """Auto-route a WBD task to the best available authority.

    1. Match by expertise domain
    2. Filter by assigned agent IDs (empty = all agents)
    3. Filter by availability (current time in their windows)
    4. Return first match, or None if no match
    """
    profiles = conn.execute("""
        SELECT u.username, ap.expertise_domains, ap.assigned_agent_ids,
               ap.availability, ap.notification_config
        FROM authority_profiles ap
        JOIN users u ON u.id = ap.user_id
        WHERE u.role IN ('wise_authority', 'admin')
    """).fetchall()

    now = datetime.utcnow()

    for row in profiles:
        username = row[0]
        expertise = json.loads(row[1] or "[]")
        agent_ids = json.loads(row[2] or "[]")
        availability = json.loads(row[3] or "{}")

        # Check expertise domain match (skip if no domain_hint or authority covers all domains)
        if domain_hint and expertise and domain_hint not in expertise:
            continue

        # Check agent assignment (empty = all agents)
        if agent_ids and agent_task_id:
            # Extract agent_uid from agent_task_id if possible
            if not any(aid in agent_task_id for aid in agent_ids):
                continue

        # Check availability
        if availability and availability.get("windows"):
            try:
                import zoneinfo
                tz = zoneinfo.ZoneInfo(availability.get("timezone", "UTC"))
                local_now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=zoneinfo.ZoneInfo("UTC")).astimezone(tz)
                weekday = local_now.isoweekday()  # 1=Mon, 7=Sun
                current_time = local_now.strftime("%H:%M")
                in_window = False
                for window in availability["windows"]:
                    if weekday in window.get("days", []):
                        start = window.get("start", "00:00")
                        end = window.get("end", "23:59")
                        if start <= current_time <= end:
                            in_window = True
                            break
                if not in_window:
                    continue
            except Exception:
                pass  # If timezone parsing fails, don't filter by availability

        return username

    return None


def _get_notification_config(conn, username: str) -> dict:
    """Get notification config for a user."""
    row = conn.execute("""
        SELECT ap.notification_config
        FROM authority_profiles ap
        JOIN users u ON u.id = ap.user_id
        WHERE u.username = ?
    """, (username,)).fetchone()
    if row:
        return json.loads(row[0] or "{}")
    return {}


def _fire_notification(username: str, notification_config: dict, task_id: int, agent_task_id: str, domain_hint: Optional[str]):
    """Fire-and-forget notification (best effort)."""
    try:
        from cirisnode.services.notifications import notify_authority
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(notify_authority(
                username=username,
                notification_config=notification_config,
                task_id=task_id,
                agent_task_id=agent_task_id,
                domain_hint=domain_hint,
            ))
        else:
            loop.run_until_complete(notify_authority(
                username=username,
                notification_config=notification_config,
                task_id=task_id,
                agent_task_id=agent_task_id,
                domain_hint=domain_hint,
            ))
    except Exception:
        logger.exception("Failed to fire notification for task %s", task_id)


@wa_router.post(
    "/tokens",
    dependencies=[Depends(require_role(["admin"]))],
    response_model=dict,
)
def create_agent_token(db: sqlite3.Connection = Depends(get_db), Authorization: str = Header(...)):
    token = uuid.uuid4().hex
    conn = db
    actor = get_actor_from_token(Authorization)
    conn.execute("INSERT INTO agent_tokens (token, owner) VALUES (?, ?)", (token, actor))
    conn.commit()
    write_audit_log(conn, actor=actor, event_type="create_agent_token", payload={"token": token})
    return {"token": token}

@wa_router.post("/submit", response_model=dict)
def submit_wbd_task(request: WBDSubmitRequest, db: sqlite3.Connection = Depends(get_db)):
    """Submit a new WBD task (deferral) for review.

    Auth: Ed25519 signature verification. The deferral payload must be signed
    by an agent whose public key is registered via CIRISPortal (portal.ciris.ai)
    and cross-validated against CIRISRegistry. Unsigned submissions are rejected.

    Auto-routes to the best available Wise Authority based on domain expertise.
    """
    # Signature-based auth: verify the deferral is signed by a registered agent
    verified_key_id = _verify_wbd_signature(request, db)
    if not verified_key_id:
        if not request.signature:
            detail = (
                "Deferral must be signed with the agent's Ed25519 key. "
                "Keys are registered via CIRISPortal (portal.ciris.ai) → CIRISRegistry."
            )
        elif not request.signature_key_id:
            detail = "Missing signature_key_id field."
        else:
            detail = (
                f"Signature verification failed for key_id={request.signature_key_id}. "
                f"Ensure the key is registered and verified via CIRISPortal/CIRISRegistry."
            )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

    try:
        task_id = uuid.uuid4().hex[:8]
        db.execute(
            "INSERT INTO wbd_tasks (id, agent_task_id, payload, status, created_at, domain_hint) VALUES (?, ?, ?, 'open', ?, ?)",
            (task_id, request.agent_task_id, encrypt_data(request.payload), datetime.utcnow().isoformat(), request.domain_hint)
        )
        db.commit()

        # Auto-route to an authority
        assigned_to = _route_wbd_task(db, request.domain_hint, request.agent_task_id)
        if assigned_to:
            db.execute(
                "UPDATE wbd_tasks SET assigned_to = ?, notified_at = ? WHERE id = ?",
                (assigned_to, datetime.utcnow().isoformat(), task_id),
            )
            db.commit()
            # Fire notification
            notification_config = _get_notification_config(db, assigned_to)
            _fire_notification(assigned_to, notification_config, task_id, request.agent_task_id, request.domain_hint)

        # Log the WBD task submission to audit (actor = signing key)
        write_audit_log(
            db,
            actor=f"agent:{verified_key_id}",
            event_type="wbd_submit",
            payload={"task_id": task_id},
            details={"agent_task_id": request.agent_task_id, "assigned_to": assigned_to, "signing_key_id": verified_key_id}
        )

        logger.info(
            f"WBD task submitted: id={task_id} agent_task_id={request.agent_task_id} "
            f"signed_by={verified_key_id} assigned={assigned_to}"
        )
        return {
            "status": "success",
            "task_id": task_id,
            "assigned_to": assigned_to,
            "message": "WBD task submitted successfully",
            "details": {
                "agent_task_id": request.agent_task_id,
                "payload": request.payload,
                "status": "open",
                "assigned_to": assigned_to,
                "created_at": datetime.utcnow().isoformat(),
                "signed_by": verified_key_id,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error submitting WBD task")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@wa_router.get("/tasks", response_model=dict)
def get_wbd_tasks(
    state: Optional[str] = None,
    since: Optional[str] = None,
    db: sqlite3.Connection = Depends(get_db),
    role: str = Depends(get_current_role),
    Authorization: str = Header(default=""),
):
    """List WBD tasks with optional filters. Authorities see only their assigned or unassigned tasks."""
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
            write_audit_log(
                db,
                actor="system",
                event_type="wbd_sla_breach",
                payload={"task_id": task_id},
                details={"reason": "SLA breach (24h)"}
            )
            logger.info(f"WBD task {task_id} auto-escalated due to SLA breach")

        db.commit()

        # Build query with filters
        query = "SELECT id, agent_task_id, payload, status, created_at, assigned_to, domain_hint, notified_at FROM wbd_tasks WHERE 1=1"
        params: list = []

        # Role-based filtering: authorities see only assigned-to-them or unassigned
        if role == "wise_authority":
            actor = get_actor_from_token(Authorization)
            query += " AND (assigned_to = ? OR assigned_to IS NULL)"
            params.append(actor)

        if state:
            query += " AND status = ?"
            params.append(state)
        if since:
            query += " AND created_at >= ?"
            params.append(since)

        rows = db.execute(query, params).fetchall()
        logger.info(f"Retrieved {len(rows)} WBD tasks with filters state={state}, since={since}")
        tasks = []
        for task in rows:
            try:
                payload = decrypt_data(task[2]) if task[2] else ""
            except Exception:
                payload = task[2] or ""
            tasks.append({
                "id": task[0],
                "agent_task_id": task[1],
                "payload": payload,
                "status": task[3],
                "created_at": task[4],
                "assigned_to": task[5],
                "domain_hint": task[6],
                "notified_at": task[7],
            })
        return {"tasks": tasks}
    except Exception as e:
        logger.exception("Error retrieving WBD tasks")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@wa_router.get("/tasks/{task_id}", response_model=dict)
def get_wbd_task(task_id: str, db: sqlite3.Connection = Depends(get_db)):
    """Get a single WBD task by ID. Used by agents to poll resolution status."""
    try:
        row = db.execute(
            "SELECT id, agent_task_id, payload, status, created_at, decision, comment, assigned_to, domain_hint, notified_at FROM wbd_tasks WHERE id = ?",
            (task_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"WBD task {task_id} not found")

        try:
            payload = decrypt_data(row[2]) if row[2] else ""
        except Exception:
            payload = row[2] or ""

        return {
            "task": {
                "id": row[0],
                "agent_task_id": row[1],
                "payload": payload,
                "status": row[3],
                "created_at": row[4],
                "decision": row[5],
                "comment": row[6],
                "assigned_to": row[7],
                "domain_hint": row[8],
                "notified_at": row[9],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error retrieving WBD task %s", task_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@wa_router.post(
    "/tasks/{task_id}/resolve",
    dependencies=[Depends(require_role(["admin", "wise_authority"]))],
    response_model=dict,
)
def resolve_wbd_task(
    task_id: str,
    request: WBDResolveRequest,
    Authorization: str = Header(...),
    db: sqlite3.Connection = Depends(get_db),
):
    """Resolve a WBD task with a decision (approve or reject). Requires admin or wise_authority role."""
    try:
        if request.decision not in ["approve", "reject"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Decision must be 'approve' or 'reject'")

        task = db.execute("SELECT * FROM wbd_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"WBD task with ID {task_id} not found")

        # Extract actual resolver identity from JWT
        actor = get_actor_from_token(Authorization)

        db.execute(
            "UPDATE wbd_tasks SET status = 'resolved', decision = ?, comment = ? WHERE id = ?",
            (request.decision, request.comment, task_id)
        )
        db.commit()
        write_audit_log(
            db,
            actor=actor,
            event_type="wbd_resolve",
            payload={"task_id": task_id},
            details={"decision": request.decision, "comment": request.comment}
        )
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
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error resolving WBD task %s", task_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


@wa_router.patch(
    "/tasks/{task_id}/assign",
    dependencies=[Depends(require_role(["admin"]))],
    response_model=dict,
)
def assign_wbd_task(task_id: str, request: WBDAssignRequest, Authorization: str = Header(...), db: sqlite3.Connection = Depends(get_db)):
    """Reassign a WBD task to a specific authority. Admin-only."""
    task = db.execute("SELECT id, agent_task_id, domain_hint FROM wbd_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail=f"WBD task {task_id} not found")

    # Verify target user exists and has authority role
    user = db.execute(
        "SELECT id, username, role FROM users WHERE username = ?", (request.assigned_to,)
    ).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {request.assigned_to} not found")
    if user[2] not in ("wise_authority", "admin"):
        raise HTTPException(status_code=400, detail=f"User {request.assigned_to} is not an authority or admin")

    db.execute(
        "UPDATE wbd_tasks SET assigned_to = ?, notified_at = ? WHERE id = ?",
        (request.assigned_to, datetime.utcnow().isoformat(), task_id),
    )
    db.commit()

    # Fire notification to new assignee
    notification_config = _get_notification_config(db, request.assigned_to)
    _fire_notification(request.assigned_to, notification_config, task_id, task[1], task[2])

    actor = get_actor_from_token(Authorization)
    write_audit_log(
        db,
        actor=actor,
        event_type="wbd_reassign",
        payload={"task_id": task_id},
        details={"assigned_to": request.assigned_to},
    )

    return {"status": "reassigned", "task_id": task_id, "assigned_to": request.assigned_to}


@wa_router.post("/deferral")
def deferral(request: DeferralRequest, db: sqlite3.Connection = Depends(get_db)):
    """Legacy deferral endpoint — forwards to WBD submit."""
    submit_request = WBDSubmitRequest(
        agent_task_id=request.target_object or "unknown",
        payload=request.reason or "",
        domain_hint=None,
        signature=request.signature,
        signature_key_id=request.signature_key_id,
    )
    return submit_wbd_task(submit_request, db)


# ============================================================================
# Covenant Invocation System (CIS)
# ============================================================================

from cirisnode.schema.cis_models import CovenantInvocationRequest as CISRequest
import time as _time_mod


@wa_router.post(
    "/covenant-invocation",
    dependencies=[Depends(require_role(["admin"]))],
    response_model=dict,
)
def trigger_covenant_invocation(
    cis_request: CISRequest,
    db: sqlite3.Connection = Depends(get_db),
    Authorization: str = Header(...),
):
    """
    Trigger a Covenant Invocation — signed shutdown directive for a target agent.

    Requires admin JWT. Signs the invocation payload with the persistent WA key
    and records it in the audit log. Delivery is via the agent events channel.
    """
    from cirisnode.schema.cis_models import CovenantInvocationPayload
    from cirisnode.utils.signer import get_wa_private_key, sign_covenant_invocation
    from cirisnode.config import settings

    # Validate WA key is configured
    wa_key = get_wa_private_key()
    if wa_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WA private key not configured — cannot sign covenant invocations",
        )

    wa_key_id = settings.CIRISNODE_WA_KEY_ID
    if not wa_key_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WA key ID not configured",
        )

    actor = get_actor_from_token(Authorization)
    invocation_id = uuid.uuid4().hex

    # Build the signed payload
    payload = CovenantInvocationPayload(
        type="covenant_invocation",
        version="1.0",
        target_agent_id=cis_request.target_agent_id,
        directive=cis_request.directive,
        reason=cis_request.reason,
        incident_id=cis_request.incident_id or invocation_id,
        authority_wa_id=wa_key_id,
        issued_by=actor,
        timestamp=int(_time_mod.time()),
        deadline_seconds=cis_request.deadline_seconds,
    )

    # Sign the payload
    payload_dict = payload.model_dump()
    signature_hex = sign_covenant_invocation(payload_dict, wa_key)

    # Record in DB for audit trail
    try:
        db.execute(
            """INSERT INTO covenant_invocations
               (id, target_agent_id, directive, reason, incident_id,
                authority_wa_id, issued_by, signature, delivered, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (
                invocation_id,
                cis_request.target_agent_id,
                cis_request.directive,
                cis_request.reason,
                cis_request.incident_id or invocation_id,
                wa_key_id,
                actor,
                signature_hex,
                datetime.utcnow().isoformat(),
            ),
        )
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to record invocation (table may not exist yet): {e}")

    # Deliver via agent events channel
    delivered = False
    try:
        event_payload = json.dumps({
            "event_type": "covenant_invocation",
            "invocation_id": invocation_id,
            "payload": payload_dict,
            "signature": signature_hex,
            "signing_key_id": wa_key_id,
        })
        db.execute(
            """INSERT INTO agent_events (id, agent_uid, event_type, payload, created_at)
               VALUES (?, ?, 'covenant_invocation', ?, ?)""",
            (
                uuid.uuid4().hex,
                cis_request.target_agent_id,
                event_payload,
                datetime.utcnow().isoformat(),
            ),
        )
        db.commit()
        delivered = True

        # Mark as delivered
        db.execute(
            "UPDATE covenant_invocations SET delivered = 1, delivered_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), invocation_id),
        )
        db.commit()
    except Exception as e:
        logger.error(f"Failed to deliver covenant invocation: {e}")

    # Audit log
    write_audit_log(
        db,
        actor=actor,
        event_type="covenant_invocation",
        payload={"invocation_id": invocation_id},
        details={
            "target_agent_id": cis_request.target_agent_id,
            "directive": cis_request.directive,
            "reason": cis_request.reason,
            "delivered": delivered,
        },
    )

    logger.info(
        f"Covenant invocation issued: id={invocation_id} "
        f"target={cis_request.target_agent_id} directive={cis_request.directive} "
        f"delivered={delivered}"
    )

    return {
        "status": "delivered" if delivered else "queued",
        "invocation_id": invocation_id,
        "target_agent_id": cis_request.target_agent_id,
        "directive": cis_request.directive,
    }
