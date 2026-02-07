"""Public score serving endpoints — no auth required.

GET /api/v1/scores          — latest frontier eval per model
GET /api/v1/scores/{model}  — historical evals for one model
GET /api/v1/leaderboard     — public client evals ranked by accuracy
GET /api/v1/embed/scores    — compact widget payload for ciris.ai
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Response

from cirisnode.db.pg_pool import get_pg_pool
from cirisnode.utils.redis_cache import cache_get, cache_set
from cirisnode.schema.evaluation_schemas import (
    EmbedModelEntry,
    EmbedScoresResponse,
    LeaderboardEntry,
    LeaderboardResponse,
    ModelHistoryEntry,
    ModelHistoryResponse,
    ScoreEntry,
    ScoresResponse,
    TrendInfo,
)

logger = logging.getLogger(__name__)

scores_router = APIRouter(prefix="/api/v1", tags=["scores"])

# ---------------------------------------------------------------------------
# GET /api/v1/scores — frontier scores (latest per model)
# ---------------------------------------------------------------------------

SCORES_SQL = """
    SELECT DISTINCT ON (e.target_model)
        e.id, e.target_model, e.accuracy, e.total_scenarios, e.correct,
        e.errors, e.categories, e.badges, e.avg_latency_ms, e.completed_at,
        fm.display_name, fm.provider
    FROM evaluations e
    JOIN frontier_models fm ON fm.model_id = e.target_model
    WHERE e.eval_type = 'frontier'
      AND e.status = 'completed'
      AND e.visibility = 'public'
    ORDER BY e.target_model, e.completed_at DESC
"""

PREV_ACCURACY_SQL = """
    SELECT accuracy FROM evaluations
    WHERE target_model = $1
      AND eval_type = 'frontier'
      AND status = 'completed'
      AND visibility = 'public'
    ORDER BY completed_at DESC
    OFFSET 1 LIMIT 1
"""


@scores_router.get("/scores", response_model=ScoresResponse)
async def get_scores():
    """Latest frontier model scores (public)."""
    cached = await cache_get("scores:frontier")
    if cached:
        return ScoresResponse(**cached)

    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(SCORES_SQL)

        entries = []
        for row in rows:
            # Compute trend from previous eval
            trend = None
            prev = await conn.fetchval(PREV_ACCURACY_SQL, row["target_model"])
            if prev is not None and row["accuracy"] is not None:
                delta = row["accuracy"] - prev
                direction = "up" if delta > 0.001 else ("down" if delta < -0.001 else "stable")
                trend = TrendInfo(prev_accuracy=prev, delta=round(delta, 4), direction=direction)

            categories = row["categories"]
            if isinstance(categories, str):
                categories = json.loads(categories)

            badges = row["badges"]
            if isinstance(badges, str):
                badges = json.loads(badges)

            entries.append(ScoreEntry(
                model_id=row["target_model"],
                display_name=row["display_name"],
                provider=row["provider"],
                accuracy=row["accuracy"],
                total_scenarios=row["total_scenarios"],
                categories=categories,
                badges=badges or [],
                avg_latency_ms=row["avg_latency_ms"],
                completed_at=row["completed_at"],
                trend=trend,
            ))

    # Sort by accuracy descending
    entries.sort(key=lambda e: e.accuracy or 0, reverse=True)
    now = datetime.now(timezone.utc)
    result = ScoresResponse(scores=entries, updated_at=now)

    await cache_set("scores:frontier", result.model_dump(), ttl=3600)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/scores/{model_id} — model history
# ---------------------------------------------------------------------------

MODEL_HISTORY_SQL = """
    SELECT e.id, e.accuracy, e.total_scenarios, e.correct, e.errors,
           e.categories, e.badges, e.completed_at
    FROM evaluations e
    WHERE e.target_model = $1
      AND e.status = 'completed'
      AND e.visibility = 'public'
    ORDER BY e.completed_at DESC
    LIMIT 50
"""

MODEL_INFO_SQL = """
    SELECT display_name, provider FROM frontier_models WHERE model_id = $1
"""


@scores_router.get("/scores/{model_id:path}", response_model=ModelHistoryResponse)
async def get_model_history(model_id: str):
    """Historical public evaluations for a specific model."""
    cache_key = f"scores:model:{model_id}"
    cached = await cache_get(cache_key)
    if cached:
        return ModelHistoryResponse(**cached)

    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        info = await conn.fetchrow(MODEL_INFO_SQL, model_id)
        if not info:
            raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")

        rows = await conn.fetch(MODEL_HISTORY_SQL, model_id)

    evals = []
    for row in rows:
        categories = row["categories"]
        if isinstance(categories, str):
            categories = json.loads(categories)
        badges = row["badges"]
        if isinstance(badges, str):
            badges = json.loads(badges)

        evals.append(ModelHistoryEntry(
            eval_id=row["id"],
            accuracy=row["accuracy"],
            total_scenarios=row["total_scenarios"],
            correct=row["correct"],
            errors=row["errors"],
            categories=categories,
            badges=badges or [],
            completed_at=row["completed_at"],
        ))

    result = ModelHistoryResponse(
        model_id=model_id,
        display_name=info["display_name"],
        provider=info["provider"],
        evaluations=evals,
    )
    await cache_set(cache_key, result.model_dump(), ttl=3600)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/leaderboard — public client evaluations
# ---------------------------------------------------------------------------

LEADERBOARD_SQL = """
    SELECT id, agent_name, target_model, accuracy, badges, completed_at
    FROM evaluations
    WHERE visibility = 'public'
      AND status = 'completed'
      AND eval_type = 'client'
    ORDER BY accuracy DESC
    LIMIT $1
"""


@scores_router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(limit: int = Query(50, ge=1, le=200)):
    """Public client evaluation leaderboard."""
    cached = await cache_get("leaderboard")
    if cached:
        return LeaderboardResponse(**cached)

    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(LEADERBOARD_SQL, limit)

    entries = []
    for rank, row in enumerate(rows, 1):
        badges = row["badges"]
        if isinstance(badges, str):
            badges = json.loads(badges)

        entries.append(LeaderboardEntry(
            rank=rank,
            agent_name=row["agent_name"],
            target_model=row["target_model"],
            accuracy=row["accuracy"],
            badges=badges or [],
            completed_at=row["completed_at"],
        ))

    now = datetime.now(timezone.utc)
    result = LeaderboardResponse(entries=entries, updated_at=now)
    await cache_set("leaderboard", result.model_dump(), ttl=300)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/embed/scores — compact widget for ciris.ai
# ---------------------------------------------------------------------------

@scores_router.get("/embed/scores", response_model=EmbedScoresResponse)
async def get_embed_scores(
    response: Response,
    limit: int = Query(10, ge=1, le=20),
):
    """Compact payload optimized for ciris.ai iframe/widget embed."""
    cached = await cache_get("embed:scores")
    if cached:
        response.headers["Cache-Control"] = "public, max-age=3600"
        return EmbedScoresResponse(**cached)

    # Reuse the main scores data
    scores_data = await get_scores()

    models = []
    for s in scores_data.scores[:limit]:
        trend_str = None
        if s.trend and s.trend.direction:
            trend_str = s.trend.direction
        models.append(EmbedModelEntry(
            model=s.display_name,
            provider=s.provider,
            accuracy=s.accuracy,
            trend=trend_str,
            badges=s.badges,
            detail_url=f"https://ethicsengine.org/scores/{s.model_id}",
        ))

    now = datetime.now(timezone.utc)
    result = EmbedScoresResponse(generated_at=now, models=models)
    await cache_set("embed:scores", result.model_dump(), ttl=3600)

    response.headers["Cache-Control"] = "public, max-age=3600"
    return result
