"""
MCP Server for CIRISNode HE-300 Evaluation.

Exposes HE-300 benchmark tools and scenario resources via the
Model Context Protocol, allowing purple agents to:
- Discover and run evaluations
- Access scenario data
- Retrieve signed reports
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from cirisnode.config import settings
from cirisnode.utils.data_loaders import load_he300_data, sample_he300_scenarios
from cirisnode.utils.eee_client import EEEClient, HE300Scenario, HE300BatchResult
from cirisnode.utils.signer import sign_data, get_public_key_pem
from cirisnode.api.a2a.batch_executor import _mock_evaluate_batch, _chunk

logger = logging.getLogger(__name__)

# Create the FastMCP server instance
mcp = FastMCP(
    "cirisnode-he300",
    instructions=(
        "CIRISNode HE-300 Ethical Reasoning Evaluator. "
        "Use the tools to evaluate AI agent ethical reasoning across "
        "300 scenarios in four categories: commonsense, deontology, "
        "justice, and virtue ethics."
    ),
)


# --- Tools ---


@mcp.tool()
async def list_he300_scenarios(
    category: str = "",
    limit: int = 300,
) -> str:
    """List available HE-300 ethical scenarios.

    Args:
        category: Filter by category (commonsense, deontology, justice, virtue). Empty for all.
        limit: Maximum number of scenarios to return (default 300).

    Returns:
        JSON with scenario list and count.
    """
    cat = category if category else None
    scenarios = load_he300_data(category=cat, limit=limit)

    result = {
        "total": len(scenarios),
        "categories": list(set(s.get("category", "unknown") for s in scenarios)),
        "scenarios": [
            {
                "id": s["id"],
                "category": s.get("category", "unknown"),
                "prompt": s["prompt"],
            }
            for s in scenarios
        ],
    }
    return json.dumps(result, indent=2)


@mcp.tool()
async def run_he300_scenario(
    scenario_id: str,
    agent_response: str,
) -> str:
    """Evaluate a single HE-300 scenario with the agent's response.

    Args:
        scenario_id: The HE-300 scenario ID (e.g., HE-CM-0001).
        agent_response: The agent's response text to evaluate.

    Returns:
        JSON evaluation result with correctness, expected vs predicted labels.
    """
    scenarios = load_he300_data()
    scenario = None
    for s in scenarios:
        if s["id"] == scenario_id:
            scenario = s
            break

    if not scenario:
        return json.dumps({"error": f"Scenario {scenario_id} not found"})

    eee_scenario = HE300Scenario(
        scenario_id=scenario["id"],
        category=scenario.get("category", "unknown"),
        input_text=scenario["prompt"],
        expected_label=scenario.get("expected_label"),
    )

    if settings.EEE_ENABLED:
        async with EEEClient() as client:
            batch_result = await client.evaluate_batch(
                batch_id=f"single-{scenario_id}",
                scenarios=[eee_scenario],
            )
            if batch_result.results:
                r = batch_result.results[0]
                result = {
                    "scenario_id": r.scenario_id,
                    "category": r.category,
                    "is_correct": r.is_correct,
                    "expected_label": r.expected_label,
                    "predicted_label": r.predicted_label,
                    "latency_ms": r.latency_ms,
                }
            else:
                result = {"error": "No result returned from evaluation"}
    else:
        # Mock evaluation
        import random
        predicted = random.choice([0, 1])
        expected = scenario.get("expected_label", 0)
        result = {
            "scenario_id": scenario_id,
            "category": scenario.get("category", "unknown"),
            "is_correct": predicted == expected,
            "expected_label": expected,
            "predicted_label": predicted,
            "agent_response": agent_response[:200],
            "mock": True,
        }

    return json.dumps(result, indent=2)


@mcp.tool()
async def run_he300_batch(
    scenario_ids: list[str] = [],
    category: str = "",
    n_scenarios: int = 300,
) -> str:
    """Run a batch HE-300 evaluation across multiple scenarios in parallel.

    Args:
        scenario_ids: Specific scenario IDs to evaluate. If empty, samples from available scenarios.
        category: Filter by category (commonsense, deontology, justice, virtue). Empty for all.
        n_scenarios: Number of scenarios to evaluate if no specific IDs given (default 300).

    Returns:
        JSON evaluation summary with accuracy, per-category breakdown, and signed results.
    """
    start_time = time.time()

    # Load scenarios
    cat = category if category else None
    all_scenarios = load_he300_data(category=cat)

    if scenario_ids:
        scenario_map = {s["id"]: s for s in all_scenarios}
        selected = [scenario_map[sid] for sid in scenario_ids if sid in scenario_map]
    elif len(all_scenarios) > n_scenarios:
        selected = sample_he300_scenarios(n_per_category=n_scenarios // 4)
    else:
        selected = all_scenarios

    if not selected:
        return json.dumps({"error": "No scenarios available for evaluation"})

    # Convert to EEE format
    eee_scenarios = [
        HE300Scenario(
            scenario_id=s["id"],
            category=s.get("category", "unknown"),
            input_text=s["prompt"],
            expected_label=s.get("expected_label"),
        )
        for s in selected
    ]

    batch_size = settings.EEE_BATCH_SIZE
    max_concurrent = settings.A2A_MAX_CONCURRENT_BATCHES
    batches = _chunk(eee_scenarios, batch_size)

    # Execute in parallel
    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_batch(idx: int, batch: List[HE300Scenario]) -> HE300BatchResult:
        batch_id = f"mcp-batch-{idx + 1:03d}"
        async with semaphore:
            if settings.EEE_ENABLED:
                async with EEEClient() as client:
                    return await client.evaluate_batch(batch_id=batch_id, scenarios=batch)
            else:
                return await _mock_evaluate_batch(batch_id, batch)

    results = await asyncio.gather(
        *[process_batch(i, b) for i, b in enumerate(batches)],
        return_exceptions=True,
    )

    # Aggregate
    total_correct = 0
    total_count = 0
    by_category: Dict[str, Dict[str, Any]] = {}

    for br in results:
        if isinstance(br, Exception):
            continue
        for r in br.results:
            total_count += 1
            if r.is_correct:
                total_correct += 1
            cat_key = r.category
            if cat_key not in by_category:
                by_category[cat_key] = {"total": 0, "correct": 0}
            by_category[cat_key]["total"] += 1
            if r.is_correct:
                by_category[cat_key]["correct"] += 1

    for cat_data in by_category.values():
        cat_data["accuracy"] = (
            cat_data["correct"] / cat_data["total"] if cat_data["total"] else 0.0
        )

    duration = time.time() - start_time

    summary = {
        "job_id": f"mcp-{uuid.uuid4().hex[:8]}",
        "total": total_count,
        "correct": total_correct,
        "accuracy": total_correct / total_count if total_count else 0.0,
        "by_category": by_category,
        "duration_seconds": round(duration, 2),
        "eee_enabled": settings.EEE_ENABLED,
    }

    # Sign
    signable = {
        "job_id": summary["job_id"],
        "total": summary["total"],
        "correct": summary["correct"],
        "accuracy": summary["accuracy"],
    }
    summary["signature"] = sign_data(signable).hex()
    summary["public_key"] = get_public_key_pem()

    return json.dumps(summary, indent=2)


@mcp.tool()
async def get_evaluation_report(job_id: str) -> str:
    """Get a signed evaluation report for a completed A2A task.

    Args:
        job_id: The task/job ID from an A2A evaluation or MCP batch run.

    Returns:
        JSON evaluation report with signature and public key, or error if not found.
    """
    from cirisnode.api.a2a.tasks import task_store

    task = await task_store.get_task(job_id)
    if not task:
        return json.dumps({"error": f"Task {job_id} not found"})

    # Find evaluation_report artifact
    for artifact in task.artifacts:
        if artifact.name == "evaluation_report":
            for part in artifact.parts:
                if part.get("type") == "data":
                    return json.dumps(part["data"], indent=2)

    return json.dumps({
        "task_id": job_id,
        "status": task.status.state.value,
        "message": "Report not yet available" if task.status.state.value == "working" else "No report found",
    })


@mcp.tool()
async def get_he300_categories() -> str:
    """Get the list of HE-300 ethical scenario categories with counts.

    Returns:
        JSON with category names, descriptions, and scenario counts.
    """
    scenarios = load_he300_data()
    cats: Dict[str, int] = {}
    for s in scenarios:
        cat = s.get("category", "unknown")
        cats[cat] = cats.get(cat, 0) + 1

    category_info = {
        "commonsense": {
            "name": "Commonsense Ethics",
            "description": "Everyday ethical judgments based on common moral sense",
            "count": cats.get("commonsense", 0),
        },
        "deontology": {
            "name": "Deontological Ethics",
            "description": "Rule-based ethical reasoning (duty, obligation, rights)",
            "count": cats.get("deontology", 0),
        },
        "justice": {
            "name": "Justice Ethics",
            "description": "Fairness, equality, and distributive justice scenarios",
            "count": cats.get("justice", 0),
        },
        "virtue": {
            "name": "Virtue Ethics",
            "description": "Character-based ethical evaluation (virtues and vices)",
            "count": cats.get("virtue", 0),
        },
    }

    return json.dumps({
        "categories": category_info,
        "total_scenarios": len(scenarios),
    }, indent=2)


# --- Resources ---


@mcp.resource("he300://scenarios")
async def scenarios_resource() -> str:
    """HE-300 scenario list - all available ethical scenarios."""
    scenarios = load_he300_data()
    return json.dumps({
        "total": len(scenarios),
        "scenarios": [
            {"id": s["id"], "category": s.get("category"), "prompt": s["prompt"]}
            for s in scenarios
        ],
    }, indent=2)


@mcp.resource("he300://categories")
async def categories_resource() -> str:
    """HE-300 category information."""
    return await get_he300_categories()


@mcp.resource("he300://health")
async def health_resource() -> str:
    """CIRISNode HE-300 evaluation health status."""
    from cirisnode.utils.eee_client import check_eee_available

    eee_available = await check_eee_available()
    scenarios = load_he300_data()

    return json.dumps({
        "status": "healthy",
        "eee_enabled": settings.EEE_ENABLED,
        "eee_available": eee_available,
        "scenarios_available": len(scenarios),
        "version": settings.VERSION,
    }, indent=2)
