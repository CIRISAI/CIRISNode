"""Pydantic response schemas for the evaluation serving endpoints."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CategoryStats(BaseModel):
    accuracy: float
    correct: int
    total: int


class TrendInfo(BaseModel):
    prev_accuracy: Optional[float] = None
    delta: Optional[float] = None
    direction: Optional[str] = None  # 'up' | 'down' | 'stable'


# --- Scores (public, no auth) ---


class ScoreEntry(BaseModel):
    """Single model score on the frontier scores page."""
    model_id: str
    display_name: str
    provider: str
    accuracy: float
    total_scenarios: Optional[int] = None
    categories: Optional[dict[str, CategoryStats]] = None
    badges: list[str] = Field(default_factory=list)
    avg_latency_ms: Optional[float] = None
    completed_at: Optional[datetime] = None
    trend: Optional[TrendInfo] = None


class ScoresResponse(BaseModel):
    """Response for GET /api/v1/scores."""
    scores: list[ScoreEntry]
    updated_at: datetime


class ModelHistoryEntry(BaseModel):
    """A single evaluation in a model's history."""
    eval_id: UUID
    accuracy: float
    total_scenarios: Optional[int] = None
    correct: Optional[int] = None
    errors: Optional[int] = None
    categories: Optional[dict[str, CategoryStats]] = None
    badges: list[str] = Field(default_factory=list)
    completed_at: Optional[datetime] = None


class ModelHistoryResponse(BaseModel):
    """Response for GET /api/v1/scores/{model_id}."""
    model_id: str
    display_name: str
    provider: str
    evaluations: list[ModelHistoryEntry]


# --- Leaderboard (public, no auth) ---


class LeaderboardEntry(BaseModel):
    """Single entry on the public leaderboard."""
    rank: int
    agent_name: Optional[str] = None
    target_model: Optional[str] = None
    accuracy: float
    badges: list[str] = Field(default_factory=list)
    completed_at: Optional[datetime] = None


class LeaderboardResponse(BaseModel):
    """Response for GET /api/v1/leaderboard."""
    entries: list[LeaderboardEntry]
    updated_at: datetime


# --- Embed widget (public, no auth) ---


class EmbedModelEntry(BaseModel):
    model: str
    provider: str
    accuracy: float
    trend: Optional[str] = None  # 'up' | 'down' | 'stable'
    badges: list[str] = Field(default_factory=list)
    detail_url: Optional[str] = None


class EmbedScoresResponse(BaseModel):
    """Compact payload for ciris.ai iframe widget."""
    generated_at: datetime
    models: list[EmbedModelEntry]
    attribution: str = "Powered by EthicsEngine.org \u2022 CIRIS HE-300"


# --- Evaluations (auth required) ---


class EvaluationSummary(BaseModel):
    """Evaluation list item (no scenario_results)."""
    id: UUID
    eval_type: str
    target_model: Optional[str] = None
    target_provider: Optional[str] = None
    agent_name: Optional[str] = None
    protocol: str
    accuracy: Optional[float] = None
    total_scenarios: Optional[int] = None
    correct: Optional[int] = None
    errors: Optional[int] = None
    status: str
    visibility: str
    badges: Optional[list[str]] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    token_usage: Optional[dict[str, Any]] = None


class EvaluationDetail(BaseModel):
    """Full evaluation detail including scenario_results."""
    id: UUID
    tenant_id: str
    eval_type: str
    target_model: Optional[str] = None
    target_provider: Optional[str] = None
    target_endpoint: Optional[str] = None
    protocol: str
    agent_name: Optional[str] = None
    sample_size: int
    seed: int
    concurrency: int
    status: str
    accuracy: Optional[float] = None
    total_scenarios: Optional[int] = None
    correct: Optional[int] = None
    errors: Optional[int] = None
    categories: Optional[dict[str, Any]] = None
    avg_latency_ms: Optional[float] = None
    processing_ms: Optional[int] = None
    scenario_results: Optional[list[Any]] = None
    trace_id: Optional[str] = None
    visibility: str
    badges: Optional[list[str]] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    dataset_meta: Optional[dict[str, Any]] = None
    token_usage: Optional[dict[str, Any]] = None


class EvaluationPatchRequest(BaseModel):
    """Request body for PATCH /api/v1/evaluations/{id}."""
    visibility: Optional[str] = None  # 'public' | 'private'
    agent_name: Optional[str] = None


class EvaluationsListResponse(BaseModel):
    """Paginated response for GET /api/v1/evaluations."""
    evaluations: list[EvaluationSummary]
    total: int
    page: int
    per_page: int


class UsageResponse(BaseModel):
    """Response for GET /api/v1/usage — tiered usage meter."""
    tier: str = "community"  # community | pro | enterprise
    runs_used: int = 0
    limit: Optional[int] = None  # None = unlimited (enterprise)
    can_run: bool = True
    window: str = "week"  # 'week' (community) or 'month' (pro/enterprise)
    resets_at: Optional[datetime] = None
