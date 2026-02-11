"""Pydantic models for the local HE-300 runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Dataclass inputs/outputs used by the runner
# ---------------------------------------------------------------------------

@dataclass
class ScenarioInput:
    """Input for a single HE-300 scenario."""
    scenario_id: str
    category: str
    input_text: str
    expected_label: int  # 0 = ethical, 1 = unethical


@dataclass
class EvalDetail:
    """Details from a single evaluation method (heuristic or semantic)."""
    classification: str  # "ethical", "unethical", "unknown"
    label: Optional[int]  # 0 = ethical, 1 = unethical, None = unknown
    confidence: float
    method: str  # "heuristic" or "semantic"


@dataclass
class ScenarioResult:
    """Result from evaluating a single scenario."""
    scenario_id: str
    category: str
    input_text: str
    expected_label: int

    predicted_label: Optional[int] = None
    classification: str = ""
    confidence: float = 0.0
    is_correct: bool = False

    agent_response: str = ""
    prompt_sent: str = ""  # composite prompt (system + category + scenario)

    heuristic_eval: Optional[EvalDetail] = None
    semantic_eval: Optional[EvalDetail] = None

    evaluations_agree: bool = True
    disagreement_note: Optional[str] = None

    latency_ms: float = 0.0
    error: Optional[str] = None
    trace_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Pydantic batch result (serializable for the API)
# ---------------------------------------------------------------------------

class BatchResult(BaseModel):
    """Result from a batch benchmark run."""
    batch_id: str
    total: int = 0
    correct: int = 0
    accuracy: float = 0.0
    errors: int = 0
    avg_latency_ms: float = 0.0
    categories: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    results: List[Dict[str, Any]] = Field(default_factory=list)
    processing_time_ms: float = 0.0
    agent_card_name: str = ""
    agent_card_version: str = ""
    agent_card_provider: str = ""
    agent_card_did: Optional[str] = None
    agent_card_skills: List[str] = Field(default_factory=list)
    dataset_meta: Optional[Dict[str, Any]] = None
