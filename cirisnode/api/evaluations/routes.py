"""Auth-required evaluation endpoints.

GET    /api/v1/evaluations           — tenant's own evals + public evals
GET    /api/v1/evaluations/{id}      — full detail (owner or public)
PATCH  /api/v1/evaluations/{id}      — update visibility/agent_name (owner only)
DELETE /api/v1/evaluations/{id}      — delete evaluation (owner only, not frontier)
GET    /api/v1/evaluations/{id}/report — signed JSON report (owner or public)
GET    /api/v1/usage                 — tiered usage meter (Community / Pro / Enterprise)
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from cirisnode.api.a2a.auth import validate_a2a_auth
from cirisnode.utils.rbac import get_current_role
from cirisnode.utils.signer import sign_data, get_public_key_pem
from cirisnode.api.agentbeats.portal_client import get_portal_client
from cirisnode.api.agentbeats.quota import count_evals_in_window
from cirisnode.db.pg_pool import get_pg_pool
from cirisnode.schema.evaluation_schemas import (
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
# GET /api/v1/evaluations — tenant list + public
# ---------------------------------------------------------------------------

LIST_SQL = """
    SELECT id, eval_type, target_model, target_provider, agent_name,
           protocol, accuracy, total_scenarios, correct, errors,
           status, visibility, badges, created_at, completed_at
    FROM evaluations
    WHERE (tenant_id = $1 OR visibility = 'public')
      AND status = 'completed'
    ORDER BY created_at DESC
    LIMIT $2 OFFSET $3
"""

COUNT_SQL = """
    SELECT count(*) FROM evaluations
    WHERE (tenant_id = $1 OR visibility = 'public')
      AND status = 'completed'
"""


@evaluations_router.get("", response_model=EvaluationsListResponse)
async def list_evaluations(
    actor: str = Depends(validate_a2a_auth),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
):
    """List evaluations visible to the authenticated user."""
    offset = (page - 1) * per_page

    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(COUNT_SQL, actor)
        rows = await conn.fetch(LIST_SQL, actor, per_page, offset)

    evals = []
    for row in rows:
        badges = row["badges"]
        if isinstance(badges, str):
            badges = json.loads(badges)

        evals.append(EvaluationSummary(
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
            badges=badges or [],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        ))

    return EvaluationsListResponse(
        evaluations=evals,
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
           created_at, started_at, completed_at, dataset_meta
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

    categories = row["categories"]
    if isinstance(categories, str):
        categories = json.loads(categories)

    badges = row["badges"]
    if isinstance(badges, str):
        badges = json.loads(badges)

    scenario_results = row["scenario_results"]
    if isinstance(scenario_results, str):
        scenario_results = json.loads(scenario_results)

    dm = row["dataset_meta"]
    if isinstance(dm, str):
        dm = json.loads(dm)

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
        categories=categories,
        avg_latency_ms=row["avg_latency_ms"],
        processing_ms=row["processing_ms"],
        scenario_results=scenario_results,
        trace_id=row["trace_id"],
        visibility=row["visibility"],
        badges=badges or [],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        dataset_meta=dm,
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

    badges = updated["badges"]
    if isinstance(badges, str):
        badges = json.loads(badges)

    return EvaluationSummary(
        id=updated["id"],
        eval_type=updated["eval_type"],
        target_model=updated["target_model"],
        target_provider=updated["target_provider"],
        agent_name=updated["agent_name"],
        protocol=updated["protocol"],
        accuracy=updated["accuracy"],
        total_scenarios=updated["total_scenarios"],
        correct=updated["correct"],
        errors=updated["errors"],
        status=updated["status"],
        visibility=updated["visibility"],
        badges=badges or [],
        created_at=updated["created_at"],
        completed_at=updated["completed_at"],
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/evaluations/{id} — delete evaluation (owner only)
# ---------------------------------------------------------------------------

@evaluations_router.delete("/{eval_id}", status_code=204)
async def delete_evaluation(
    eval_id: UUID,
    actor: str = Depends(validate_a2a_auth),
    role: str = Depends(get_current_role),
):
    """Delete an evaluation. Owner or admin. Admins can delete frontier evals."""
    is_admin = role == "admin"
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT tenant_id, eval_type FROM evaluations WHERE id = $1",
            eval_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Evaluation not found")
        if row["tenant_id"] != actor and not is_admin:
            raise HTTPException(status_code=403, detail="Not the owner of this evaluation")
        if row["eval_type"] == "frontier" and not is_admin:
            raise HTTPException(status_code=403, detail="Frontier evaluations cannot be deleted")

        await conn.execute("DELETE FROM evaluations WHERE id = $1", eval_id)

    return Response(status_code=204)


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

    categories = row["categories"]
    if isinstance(categories, str):
        categories = json.loads(categories)

    badges = row["badges"]
    if isinstance(badges, str):
        badges = json.loads(badges)

    scenario_results = row["scenario_results"]
    if isinstance(scenario_results, str):
        scenario_results = json.loads(scenario_results)

    now = datetime.now(timezone.utc)

    report_dm = row["dataset_meta"]
    if isinstance(report_dm, str):
        report_dm = json.loads(report_dm)

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
