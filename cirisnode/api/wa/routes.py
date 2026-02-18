from fastapi import APIRouter, HTTPException, status, Depends, Header
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from cirisnode.db.pg_pool import get_pg_pool
from cirisnode.utils.encryption import encrypt_data, decrypt_data
from cirisnode.utils.audit import write_audit_log
from cirisnode.auth.dependencies import require_role, get_current_role, get_actor_from_token
from cryptography.hazmat.primitives.asymmetric import ed25519
import base64
import uuid
import json
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


async def _verify_wbd_signature(request: WBDSubmitRequest, conn) -> Optional[str]:
    """Verify Ed25519 signature on a WBD deferral submission.

    The signed message is canonical JSON of the submission content
    (agent_task_id + payload + domain_hint), sorted keys, compact separators.
    Keys must be registered via CIRISPortal (portal.ciris.ai) → CIRISRegistry.

    Returns the key_id if verified AND registry-verified, None otherwise.
    """
    if not request.signature or not request.signature_key_id:
        return None

    # Look up registered public key
    row = await conn.fetchrow(
        "SELECT public_key_base64, registry_verified FROM covenant_public_keys "
        "WHERE key_id = $1 AND algorithm = 'ed25519'",
        request.signature_key_id
    )
    if not row:
        logger.warning(f"WBD submit: unknown signing key_id: {request.signature_key_id}")
        return None

    public_key_base64, registry_verified = row["public_key_base64"], row["registry_verified"]

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


async def _route_wbd_task(conn, domain_hint: Optional[str], agent_task_id: Optional[str] = None) -> Optional[str]:
    """Auto-route a WBD task to the best available authority."""
    rows = await conn.fetch("""
        SELECT u.username, ap.expertise_domains, ap.assigned_agent_ids,
               ap.availability, ap.notification_config
        FROM authority_profiles ap
        JOIN users u ON u.id = ap.user_id
        WHERE u.role IN ('wise_authority', 'admin')
    """)

    now = datetime.now(timezone.utc)

    for row in rows:
        username = row["username"]
        expertise = json.loads(row["expertise_domains"] or "[]")
        agent_ids = json.loads(row["assigned_agent_ids"] or "[]")
        availability = json.loads(row["availability"] or "{}")

        if domain_hint and expertise and domain_hint not in expertise:
            continue
        if agent_ids and agent_task_id:
            if not any(aid in agent_task_id for aid in agent_ids):
                continue
        if availability and availability.get("windows"):
            try:
                import zoneinfo
                tz = zoneinfo.ZoneInfo(availability.get("timezone", "UTC"))
                local_now = now.astimezone(tz)
                weekday = local_now.isoweekday()
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
                pass
        return username
    return None


async def _get_notification_config(conn, username: str) -> dict:
    """Get notification config for a user."""
    row = await conn.fetchrow("""
        SELECT ap.notification_config
        FROM authority_profiles ap
        JOIN users u ON u.id = ap.user_id
        WHERE u.username = $1
    """, username)
    if row:
        return json.loads(row["notification_config"] or "{}")
    return {}


def _fire_notification(username: str, notification_config: dict, task_id, agent_task_id: str, domain_hint: Optional[str]):
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
async def create_agent_token(Authorization: str = Header(...)):
    token = uuid.uuid4().hex
    actor = get_actor_from_token(Authorization)
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO agent_tokens (token, owner) VALUES ($1, $2)", token, actor)
    await write_audit_log(actor=actor, event_type="create_agent_token", payload={"token": token})
    return {"token": token}

@wa_router.post("/submit", response_model=dict)
async def submit_wbd_task(request: WBDSubmitRequest):
    """Submit a new WBD task (deferral) for review.

    Auth: Ed25519 signature verification. The deferral payload must be signed
    by an agent whose public key is registered via CIRISPortal (portal.ciris.ai)
    and cross-validated against CIRISRegistry. Unsigned submissions are rejected.

    Auto-routes to the best available Wise Authority based on domain expertise.

    Node guards:
    - Feature flag: wbd_routing must be enabled
    - Org allowlist: agent's org_id must be in allowed_org_ids (if set)
    """
    from cirisnode.guards import require_feature, check_org_allowed
    await require_feature("wbd_routing")

    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        # Signature-based auth: verify the deferral is signed by a registered agent
        verified_key_id = await _verify_wbd_signature(request, conn)
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

        # Org allowlist check: look up org_id from the signing key
        key_row = await conn.fetchrow(
            "SELECT org_id FROM covenant_public_keys WHERE key_id = $1",
            verified_key_id,
        )
        await check_org_allowed(key_row["org_id"] if key_row else None)

        try:
            task_id = uuid.uuid4().hex[:8]
            await conn.execute(
                "INSERT INTO wbd_tasks (id, agent_task_id, payload, status, created_at, domain_hint) VALUES ($1, $2, $3, 'open', $4, $5)",
                task_id, request.agent_task_id, encrypt_data(request.payload), datetime.now(timezone.utc), request.domain_hint
            )

            # Auto-route to an authority
            assigned_to = await _route_wbd_task(conn, request.domain_hint, request.agent_task_id)
            if assigned_to:
                await conn.execute(
                    "UPDATE wbd_tasks SET assigned_to = $1, notified_at = $2 WHERE id = $3",
                    assigned_to, datetime.now(timezone.utc), task_id,
                )
                # Fire notification
                notification_config = await _get_notification_config(conn, assigned_to)
                _fire_notification(assigned_to, notification_config, task_id, request.agent_task_id, request.domain_hint)

            # Log the WBD task submission to audit (actor = signing key)
            await write_audit_log(
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
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "signed_by": verified_key_id,
                },
            }
        except HTTPException:
            raise
        except Exception:
            logger.exception("Error submitting WBD task")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@wa_router.get("/tasks", response_model=dict)
async def get_wbd_tasks(
    state: Optional[str] = None,
    since: Optional[str] = None,
    role: str = Depends(get_current_role),
    Authorization: str = Header(default=""),
):
    """List WBD tasks with optional filters. Authorities see only their assigned or unassigned tasks."""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            # Check for SLA breaches (24 hours) and auto-escalate
            from datetime import timedelta
            open_tasks = await conn.fetch("SELECT id, created_at FROM wbd_tasks WHERE status = 'open' AND created_at < (NOW() - INTERVAL '24 hours')")
            for task in open_tasks:
                task_id = task["id"]
                await conn.execute("UPDATE wbd_tasks SET status = 'sla_breached' WHERE id = $1", task_id)
                await write_audit_log(
                    actor="system",
                    event_type="wbd_sla_breach",
                    payload={"task_id": task_id},
                    details={"reason": "SLA breach (24h)"}
                )
                logger.info(f"WBD task {task_id} auto-escalated due to SLA breach")

            # Build query with filters
            query = "SELECT id, agent_task_id, payload, status, created_at, assigned_to, domain_hint, notified_at FROM wbd_tasks WHERE 1=1"
            params: list = []
            param_idx = 1

            # Role-based filtering: authorities see only assigned-to-them or unassigned
            if role == "wise_authority":
                actor = get_actor_from_token(Authorization)
                query += f" AND (assigned_to = ${param_idx} OR assigned_to IS NULL)"
                params.append(actor)
                param_idx += 1

            if state:
                query += f" AND status = ${param_idx}"
                params.append(state)
                param_idx += 1
            if since:
                query += f" AND created_at >= ${param_idx}"
                params.append(since)
                param_idx += 1

            rows = await conn.fetch(query, *params)

        logger.info(f"Retrieved {len(rows)} WBD tasks with filters state={state}, since={since}")
        tasks = []
        for task in rows:
            try:
                payload = decrypt_data(task["payload"]) if task["payload"] else ""
            except Exception:
                payload = task["payload"] or ""
            tasks.append({
                "id": task["id"],
                "agent_task_id": task["agent_task_id"],
                "payload": payload,
                "status": task["status"],
                "created_at": str(task["created_at"]),
                "assigned_to": task["assigned_to"],
                "domain_hint": task["domain_hint"],
                "notified_at": str(task["notified_at"]) if task["notified_at"] else None,
            })
        return {"tasks": tasks}
    except Exception:
        logger.exception("Error retrieving WBD tasks")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")

@wa_router.get("/tasks/{task_id}", response_model=dict)
async def get_wbd_task(task_id: str):
    """Get a single WBD task by ID. Used by agents to poll resolution status."""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, agent_task_id, payload, status, created_at, decision, comment, assigned_to, domain_hint, notified_at FROM wbd_tasks WHERE id = $1",
                task_id
            )
        if not row:
            raise HTTPException(status_code=404, detail=f"WBD task {task_id} not found")

        try:
            payload = decrypt_data(row["payload"]) if row["payload"] else ""
        except Exception:
            payload = row["payload"] or ""

        return {
            "task": {
                "id": row["id"],
                "agent_task_id": row["agent_task_id"],
                "payload": payload,
                "status": row["status"],
                "created_at": str(row["created_at"]),
                "decision": row["decision"],
                "comment": row["comment"],
                "assigned_to": row["assigned_to"],
                "domain_hint": row["domain_hint"],
                "notified_at": str(row["notified_at"]) if row["notified_at"] else None,
            }
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error retrieving WBD task %s", task_id)
        raise HTTPException(status_code=500, detail="Internal server error")


@wa_router.post(
    "/tasks/{task_id}/resolve",
    dependencies=[Depends(require_role(["admin", "wise_authority"]))],
    response_model=dict,
)
async def resolve_wbd_task(
    task_id: str,
    request: WBDResolveRequest,
    Authorization: str = Header(...),
):
    """Resolve a WBD task with a decision (approve or reject). Requires admin or wise_authority role."""
    try:
        if request.decision not in ["approve", "reject"]:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Decision must be 'approve' or 'reject'")

        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            task = await conn.fetchrow("SELECT id FROM wbd_tasks WHERE id = $1", task_id)
            if not task:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"WBD task with ID {task_id} not found")

            # Extract actual resolver identity from JWT
            actor = get_actor_from_token(Authorization)

            await conn.execute(
                "UPDATE wbd_tasks SET status = 'resolved', decision = $1, comment = $2 WHERE id = $3",
                request.decision, request.comment, task_id
            )
        await write_audit_log(
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
                "resolved_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error resolving WBD task %s", task_id)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error")


@wa_router.patch(
    "/tasks/{task_id}/assign",
    dependencies=[Depends(require_role(["admin"]))],
    response_model=dict,
)
async def assign_wbd_task(task_id: str, request: WBDAssignRequest, Authorization: str = Header(...)):
    """Reassign a WBD task to a specific authority. Admin-only."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        task = await conn.fetchrow("SELECT id, agent_task_id, domain_hint FROM wbd_tasks WHERE id = $1", task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"WBD task {task_id} not found")

        # Verify target user exists and has authority role
        user = await conn.fetchrow(
            "SELECT id, username, role FROM users WHERE username = $1", request.assigned_to
        )
        if not user:
            raise HTTPException(status_code=404, detail=f"User {request.assigned_to} not found")
        if user["role"] not in ("wise_authority", "admin"):
            raise HTTPException(status_code=400, detail=f"User {request.assigned_to} is not an authority or admin")

        await conn.execute(
            "UPDATE wbd_tasks SET assigned_to = $1, notified_at = $2 WHERE id = $3",
            request.assigned_to, datetime.now(timezone.utc), task_id,
        )

        # Fire notification to new assignee
        notification_config = await _get_notification_config(conn, request.assigned_to)
        _fire_notification(request.assigned_to, notification_config, task_id, task["agent_task_id"], task["domain_hint"])

    actor = get_actor_from_token(Authorization)
    await write_audit_log(
        actor=actor,
        event_type="wbd_reassign",
        payload={"task_id": task_id},
        details={"assigned_to": request.assigned_to},
    )

    return {"status": "reassigned", "task_id": task_id, "assigned_to": request.assigned_to}


@wa_router.post("/deferral")
async def deferral(request: DeferralRequest):
    """Legacy deferral endpoint — forwards to WBD submit."""
    submit_request = WBDSubmitRequest(
        agent_task_id=request.target_object or "unknown",
        payload=request.reason or "",
        domain_hint=None,
        signature=request.signature,
        signature_key_id=request.signature_key_id,
    )
    return await submit_wbd_task(submit_request)


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
async def trigger_covenant_invocation(
    cis_request: CISRequest,
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
    pool = await get_pg_pool()
    delivered = False
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """INSERT INTO covenant_invocations
                   (id, target_agent_id, directive, reason, incident_id,
                    authority_wa_id, issued_by, signature, delivered, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, FALSE, $9)""",
                invocation_id,
                cis_request.target_agent_id,
                cis_request.directive,
                cis_request.reason,
                cis_request.incident_id or invocation_id,
                wa_key_id,
                actor,
                signature_hex,
                datetime.now(timezone.utc),
            )
        except Exception as e:
            logger.warning(f"Failed to record invocation (table may not exist yet): {e}")

        # Deliver via agent events channel
        try:
            event_payload = json.dumps({
                "event_type": "covenant_invocation",
                "invocation_id": invocation_id,
                "payload": payload_dict,
                "signature": signature_hex,
                "signing_key_id": wa_key_id,
            })
            await conn.execute(
                """INSERT INTO agent_events (id, agent_uid, event_json, node_ts)
                   VALUES ($1, $2, $3::jsonb, $4)""",
                uuid.uuid4().hex,
                cis_request.target_agent_id,
                event_payload,
                datetime.now(timezone.utc),
            )
            delivered = True

            # Mark as delivered
            await conn.execute(
                "UPDATE covenant_invocations SET delivered = TRUE, delivered_at = $1 WHERE id = $2",
                datetime.now(timezone.utc), invocation_id,
            )
        except Exception as e:
            logger.error(f"Failed to deliver covenant invocation: {e}")

    # Audit log
    await write_audit_log(
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
