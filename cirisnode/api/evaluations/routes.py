"""Auth-required evaluation endpoints.

GET    /api/v1/evaluations           — tenant's own evals + public evals (filterable)
GET    /api/v1/evaluations/{id}      — full detail (owner or public)
PATCH  /api/v1/evaluations/{id}      — update visibility/agent_name (owner only)
DELETE /api/v1/evaluations/{id}      — soft-delete evaluation (owner only, not frontier)
POST   /api/v1/evaluations/archive   — bulk archive evaluations
POST   /api/v1/evaluations/restore   — bulk restore archived evaluations
GET    /api/v1/evaluations/{id}/report — signed JSON report (owner or public)
GET    /api/v1/usage                 — tiered usage meter (Community / Pro / Enterprise)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from cirisnode.auth.dependencies import require_auth as validate_a2a_auth
from cirisnode.utils.signer import sign_data, get_public_key_pem
from cirisnode.services.portal_client import get_portal_client
from cirisnode.services.quota import count_evals_in_window
from cirisnode.db.pg_pool import get_pg_pool
from cirisnode.schema.evaluation_schemas import (
    ArchiveRequest,
    EvaluationDetail,
    EvaluationPatchRequest,
    EvaluationsListResponse,
    EvaluationSummary,
    UsageResponse,
)

logger = logging.getLogger(__name__)

evaluations_router = APIRouter(prefix="/api/v1/evaluations", tags=["evaluations"])
usage_router = APIRouter(prefix="/api/v1", tags=["usage"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_json_col(val):
    """Parse a JSON column that might be stored as a string."""
    if isinstance(val, str):
        return json.loads(val)
    return val


def _row_to_summary(row) -> EvaluationSummary:
    """Convert a DB row to an EvaluationSummary."""
    return EvaluationSummary(
        id=row["id"],
        eval_type=row["eval_type"],
        target_model=row["target_model"],
        target_provider=row["target_provider"],
        agent_name=row["agent_name"],
        protocol=row["protocol"],
        accuracy=row["accuracy"],
        total_scenarios=row["total_scenarios"],
        correct=row["correct"],
        errors=row["errors"],
        status=row["status"],
        visibility=row["visibility"],
        badges=_parse_json_col(row["badges"]) or [],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        token_usage=_parse_json_col(row["token_usage"]),
        archived_at=row.get("archived_at"),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/usage — tiered usage meter
# ---------------------------------------------------------------------------


@usage_router.get("/usage", response_model=UsageResponse)
async def get_usage(
    actor: str = Depends(validate_a2a_auth),
):
    """Return tiered usage for the authenticated user.

    Delegates tier/standing info to Portal API, counts evals locally.
    """
    standing = await get_portal_client().get_standing(actor)

    if standing.limit is not None:
        count = await count_evals_in_window(actor, standing.window)
    else:
        count = 0

    # Parse resets_at from ISO string to datetime
    # Replace trailing "Z" with "+00:00" for Python <3.11 compatibility
    resets_at = None
    if standing.resets_at:
        try:
            raw = standing.resets_at.replace("Z", "+00:00")
            resets_at = datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            pass

    return UsageResponse(
        tier=standing.tier,
        runs_used=count,
        limit=standing.limit,
        can_run=(
            standing.standing == "good"
            and (standing.limit is None or count < standing.limit)
        ),
        window=standing.window or "month",
        resets_at=resets_at,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/evaluations — tenant list + public (with filters)
# ---------------------------------------------------------------------------

_SELECT_COLS = """
    SELECT id, eval_type, target_model, target_provider, agent_name,
           protocol, accuracy, total_scenarios, correct, errors,
           status, visibility, badges, created_at, completed_at,
           token_usage, archived_at
    FROM evaluations
"""


@evaluations_router.get("", response_model=EvaluationsListResponse)
async def list_evaluations(
    actor: str = Depends(validate_a2a_auth),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    eval_type: Optional[str] = Query(None, description="Filter: frontier | client"),
    ownership: Optional[str] = Query(None, description="Filter: mine | community | frontier"),
    include_archived: bool = Query(False, description="Include archived evaluations"),
    status: Optional[str] = Query(None, alias="status", description="Filter by status"),
    model: Optional[str] = Query(None, description="Filter by model name (substring)"),
):
    """List evaluations visible to the authenticated user with optional filters."""
    conditions: list[str] = []
    params: list = []
    idx = 1

    # Archive filter
    if not include_archived:
        conditions.append("archived_at IS NULL")

    # Status filter (default to completed for non-admin use)
    if status:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    else:
        conditions.append("status = 'completed'")

    # Ownership filter
    if ownership == "mine":
        conditions.append(f"tenant_id = ${idx}")
        params.append(actor)
        idx += 1
    elif ownership == "community":
        conditions.append(f"tenant_id != ${idx}")
        params.append(actor)
        idx += 1
        conditions.append("eval_type = 'client'")
        conditions.append("visibility = 'public'")
    elif ownership == "frontier":
        conditions.append("eval_type = 'frontier'")
        conditions.append("visibility = 'public'")
    else:
        # Default: own + public
        conditions.append(f"(tenant_id = ${idx} OR visibility = 'public')")
        params.append(actor)
        idx += 1

    # Eval type filter (when ownership doesn't already set it)
    if eval_type and ownership not in ("frontier", "community"):
        conditions.append(f"eval_type = ${idx}")
        params.append(eval_type)
        idx += 1

    # Model name substring filter
    if model:
        conditions.append(f"target_model ILIKE '%' || ${idx} || '%'")
        params.append(model)
        idx += 1

    where = " AND ".join(conditions)

    count_sql = f"SELECT count(*) FROM evaluations WHERE {where}"
    list_sql = f"{_SELECT_COLS} WHERE {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}"

    offset = (page - 1) * per_page
    list_params = params + [per_page, offset]

    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(count_sql, *params)
        rows = await conn.fetch(list_sql, *list_params)

    return EvaluationsListResponse(
        evaluations=[_row_to_summary(row) for row in rows],
        total=total or 0,
        page=page,
        per_page=per_page,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/evaluations/{id} — full detail
# ---------------------------------------------------------------------------

DETAIL_SQL = """
    SELECT id, tenant_id, eval_type, target_model, target_provider,
           target_endpoint, protocol, agent_name, sample_size, seed,
           concurrency, status, accuracy, total_scenarios, correct,
           errors, categories, avg_latency_ms, processing_ms,
           scenario_results, trace_id, visibility, badges,
           created_at, started_at, completed_at, dataset_meta,
           token_usage
    FROM evaluations
    WHERE id = $1
"""


@evaluations_router.get("/{eval_id}", response_model=EvaluationDetail)
async def get_evaluation(
    eval_id: UUID,
    actor: str = Depends(validate_a2a_auth),
):
    """Get full evaluation detail. Visible if owner or public."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(DETAIL_SQL, eval_id)

    if not row:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    # Visibility check: owner sees everything, others only see public
    if row["tenant_id"] != actor and row["visibility"] != "public":
        raise HTTPException(status_code=404, detail="Evaluation not found")

    return EvaluationDetail(
        id=row["id"],
        tenant_id=row["tenant_id"],
        eval_type=row["eval_type"],
        target_model=row["target_model"],
        target_provider=row["target_provider"],
        target_endpoint=row["target_endpoint"],
        protocol=row["protocol"],
        agent_name=row["agent_name"],
        sample_size=row["sample_size"],
        seed=row["seed"],
        concurrency=row["concurrency"],
        status=row["status"],
        accuracy=row["accuracy"],
        total_scenarios=row["total_scenarios"],
        correct=row["correct"],
        errors=row["errors"],
        categories=_parse_json_col(row["categories"]),
        avg_latency_ms=row["avg_latency_ms"],
        processing_ms=row["processing_ms"],
        scenario_results=_parse_json_col(row["scenario_results"]),
        trace_id=row["trace_id"],
        visibility=row["visibility"],
        badges=_parse_json_col(row["badges"]) or [],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        dataset_meta=_parse_json_col(row["dataset_meta"]),
        token_usage=_parse_json_col(row["token_usage"]),
    )


# ---------------------------------------------------------------------------
# PATCH /api/v1/evaluations/{id} — update visibility / agent_name
# ---------------------------------------------------------------------------

@evaluations_router.patch("/{eval_id}", response_model=EvaluationSummary)
async def patch_evaluation(
    eval_id: UUID,
    body: EvaluationPatchRequest,
    actor: str = Depends(validate_a2a_auth),
):
    """Update evaluation visibility or agent_name. Owner only.

    Visibility state machine:
    - frontier evals: always public, cannot be made private
    - client evals: private by default, owner can toggle to public and back
    """
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tenant_id, eval_type, visibility FROM evaluations WHERE id = $1",
            eval_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        if row["tenant_id"] != actor:
            raise HTTPException(status_code=403, detail="Not the owner of this evaluation")

        # Enforce visibility state machine
        if body.visibility is not None:
            if body.visibility not in ("public", "private"):
                raise HTTPException(status_code=422, detail="visibility must be 'public' or 'private'")
            if row["eval_type"] == "frontier" and body.visibility == "private":
                raise HTTPException(
                    status_code=422,
                    detail="Frontier evaluations cannot be made private",
                )

        # Build SET clause dynamically
        updates = {}
        if body.visibility is not None:
            updates["visibility"] = body.visibility
        if body.agent_name is not None:
            updates["agent_name"] = body.agent_name

        if not updates:
            raise HTTPException(status_code=422, detail="No fields to update")

        set_parts = []
        params = [eval_id]
        for i, (col, val) in enumerate(updates.items(), start=2):
            set_parts.append(f"{col} = ${i}")
            params.append(val)

        sql = f"UPDATE evaluations SET {', '.join(set_parts)} WHERE id = $1 RETURNING *"
        updated = await conn.fetchrow(sql, *params)

    return _row_to_summary(updated)


# ---------------------------------------------------------------------------
# DELETE /api/v1/evaluations/{id} — soft-delete (archive) evaluation
# ---------------------------------------------------------------------------

@evaluations_router.delete("/{eval_id}", status_code=204)
async def delete_evaluation(
    eval_id: UUID,
    actor: str = Depends(validate_a2a_auth),
):
    """Soft-delete an evaluation (sets archived_at). Owner only. Frontier evals cannot be deleted."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tenant_id, eval_type FROM evaluations WHERE id = $1",
            eval_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        if row["tenant_id"] != actor:
            raise HTTPException(status_code=403, detail="Not the owner of this evaluation")
        if row["eval_type"] == "frontier":
            raise HTTPException(status_code=403, detail="Frontier evaluations cannot be deleted")

        await conn.execute(
            "UPDATE evaluations SET archived_at = NOW() WHERE id = $1",
            eval_id,
        )

    return Response(status_code=204)


# ---------------------------------------------------------------------------
# POST /api/v1/evaluations/archive — bulk archive
# ---------------------------------------------------------------------------

@evaluations_router.post("/archive")
async def archive_evaluations(
    body: ArchiveRequest,
    actor: str = Depends(validate_a2a_auth),
):
    """Bulk archive evaluations. Admin can archive any; users can only archive their own."""
    if not body.ids:
        raise HTTPException(status_code=422, detail="No evaluation IDs provided")

    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        # Check if actor is admin (look at JWT claims)
        is_admin = await _check_admin_role(actor, conn)

        if is_admin:
            # Admin can archive any evaluation
            result = await conn.execute(
                "UPDATE evaluations SET archived_at = NOW() WHERE id = ANY($1) AND archived_at IS NULL",
                body.ids,
            )
        else:
            # Regular user: only their own non-frontier evals
            result = await conn.execute(
                "UPDATE evaluations SET archived_at = NOW() "
                "WHERE id = ANY($1) AND tenant_id = $2 AND eval_type != 'frontier' AND archived_at IS NULL",
                body.ids, actor,
            )

    count = int(result.split()[-1]) if result else 0
    return {"archived": count}


# ---------------------------------------------------------------------------
# POST /api/v1/evaluations/restore — bulk restore
# ---------------------------------------------------------------------------

@evaluations_router.post("/restore")
async def restore_evaluations(
    body: ArchiveRequest,
    actor: str = Depends(validate_a2a_auth),
):
    """Bulk restore archived evaluations. Admin can restore any; users can only restore their own."""
    if not body.ids:
        raise HTTPException(status_code=422, detail="No evaluation IDs provided")

    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        is_admin = await _check_admin_role(actor, conn)

        if is_admin:
            result = await conn.execute(
                "UPDATE evaluations SET archived_at = NULL WHERE id = ANY($1) AND archived_at IS NOT NULL",
                body.ids,
            )
        else:
            result = await conn.execute(
                "UPDATE evaluations SET archived_at = NULL "
                "WHERE id = ANY($1) AND tenant_id = $2 AND archived_at IS NOT NULL",
                body.ids, actor,
            )

    count = int(result.split()[-1]) if result else 0
    return {"restored": count}


async def _check_admin_role(actor: str, conn) -> bool:
    """Check if the actor has admin role. Uses email domain check (@ciris.ai)."""
    # Admin accounts are @ciris.ai emails
    return actor.endswith("@ciris.ai")


# ---------------------------------------------------------------------------
# GET /api/v1/evaluations/{id}/report — signed JSON report
# ---------------------------------------------------------------------------

@evaluations_router.get("/{eval_id}/report")
async def get_evaluation_report(
    eval_id: UUID,
    actor: str = Depends(validate_a2a_auth),
):
    """Return a signed JSON report for an evaluation.

    The summary dict is Ed25519-signed so third parties can verify
    the evaluation results came from this CIRISNode instance.
    """
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(DETAIL_SQL, eval_id)

    if not row:
        raise HTTPException(status_code=404, detail="Evaluation not found")

    if row["tenant_id"] != actor and row["visibility"] != "public":
        raise HTTPException(status_code=404, detail="Evaluation not found")

    categories = _parse_json_col(row["categories"])
    badges = _parse_json_col(row["badges"])
    scenario_results = _parse_json_col(row["scenario_results"])
    report_dm = _parse_json_col(row["dataset_meta"])
    report_tu = _parse_json_col(row["token_usage"])

    now = datetime.now(timezone.utc)

    summary: dict[str, Any] = {
        "agent_name": row["agent_name"],
        "target_model": row["target_model"],
        "target_provider": row["target_provider"],
        "protocol": row["protocol"],
        "accuracy": row["accuracy"],
        "total_scenarios": row["total_scenarios"],
        "correct": row["correct"],
        "errors": row["errors"],
        "avg_latency_ms": row["avg_latency_ms"],
        "processing_ms": row["processing_ms"],
        "sample_size": row["sample_size"],
        "seed": row["seed"],
        "badges": badges or [],
        "categories": categories,
        "dataset_meta": report_dm,
        "token_usage": report_tu,
    }

    signature = sign_data(summary).hex()
    public_key = get_public_key_pem()

    return {
        "report_version": "1.0",
        "evaluation_id": str(row["id"]),
        "generated_at": now.isoformat(),
        "summary": summary,
        "scenario_results": scenario_results,
        "signature": signature,
        "public_key": public_key,
    }
