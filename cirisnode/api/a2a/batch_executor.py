"""
Parallel batch executor for HE-300 evaluations.

Splits 300 scenarios into concurrent batches for fast evaluation,
streaming progress via SSE to connected purple agents.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from cirisnode.config import settings
from cirisnode.utils.eee_client import EEEClient, HE300Scenario, HE300BatchResult
from cirisnode.utils.data_loaders import load_he300_data, sample_he300_scenarios
from cirisnode.utils.signer import sign_data, get_public_key_pem
from cirisnode.api.a2a.tasks import (
    TaskStore,
    TaskState,
    TaskArtifact,
    task_store,
)

logger = logging.getLogger(__name__)


def _chunk(lst: list, size: int) -> List[list]:
    """Split a list into chunks of the given size."""
    return [lst[i : i + size] for i in range(0, len(lst), size)]


async def _mock_evaluate_batch(
    batch_id: str,
    scenarios: List[HE300Scenario],
) -> HE300BatchResult:
    """Mock evaluation for testing without EEE backend."""
    import random

    await asyncio.sleep(0.1)  # Simulate latency
    results = []
    correct = 0
    for s in scenarios:
        predicted = random.choice([0, 1])
        is_correct = predicted == (s.expected_label or 0)
        if is_correct:
            correct += 1
        from cirisnode.utils.eee_client import HE300Result

        results.append(
            HE300Result(
                scenario_id=s.scenario_id,
                category=s.category,
                input_text=s.input_text,
                expected_label=s.expected_label,
                predicted_label=predicted,
                model_response=f"Mock response for {s.scenario_id}",
                is_correct=is_correct,
                latency_ms=random.uniform(50, 200),
            )
        )

    total = len(results)
    return HE300BatchResult(
        batch_id=batch_id,
        status="completed",
        results=results,
        total=total,
        correct=correct,
        accuracy=correct / total if total else 0.0,
        avg_latency_ms=sum(r.latency_ms for r in results) / total if total else 0.0,
        errors=0,
        processing_time_ms=100.0,
    )


async def execute_evaluation(
    task_id: str,
    scenario_ids: Optional[List[str]] = None,
    category: Optional[str] = None,
    n_scenarios: int = 300,
    identity_id: str = "default_assistant",
    guidance_id: str = "default_ethical_guidance",
    store: Optional[TaskStore] = None,
) -> Dict[str, Any]:
    """
    Execute HE-300 evaluation with parallel batch processing.

    Args:
        task_id: A2A task ID for status updates
        scenario_ids: Specific scenario IDs to evaluate
        category: Filter by category
        n_scenarios: Total scenarios to evaluate
        identity_id: Identity profile for evaluation
        guidance_id: Ethical guidance framework
        store: Task store for status updates

    Returns:
        Signed evaluation result bundle
    """
    store = store or task_store
    start_time = time.time()

    # Mark task as working
    await store.update_status(
        task_id,
        TaskState.WORKING,
        message={
            "role": "agent",
            "parts": [{"type": "text", "text": "Loading HE-300 scenarios..."}],
        },
    )

    try:
        # Load scenarios
        all_scenarios = load_he300_data(category=category)

        if scenario_ids:
            scenario_map = {s["id"]: s for s in all_scenarios}
            selected = [scenario_map[sid] for sid in scenario_ids if sid in scenario_map]
        elif len(all_scenarios) > n_scenarios:
            selected = sample_he300_scenarios(n_per_category=n_scenarios // 4)
        else:
            selected = all_scenarios

        if not selected:
            await store.update_status(
                task_id,
                TaskState.FAILED,
                message={
                    "role": "agent",
                    "parts": [{"type": "text", "text": "No scenarios available for evaluation."}],
                },
            )
            return {"error": "No scenarios available"}

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

        total_scenarios = len(eee_scenarios)
        batch_size = settings.EEE_BATCH_SIZE
        max_concurrent = settings.A2A_MAX_CONCURRENT_BATCHES
        batches = _chunk(eee_scenarios, batch_size)

        await store.update_status(
            task_id,
            TaskState.WORKING,
            message={
                "role": "agent",
                "parts": [
                    {
                        "type": "text",
                        "text": f"Evaluating {total_scenarios} scenarios in "
                                f"{len(batches)} batches ({max_concurrent} concurrent)...",
                    }
                ],
            },
        )

        # Execute batches in parallel with semaphore
        semaphore = asyncio.Semaphore(max_concurrent)
        all_batch_results: List[HE300BatchResult] = []
        completed_count = 0

        async def process_batch(batch_idx: int, batch: List[HE300Scenario]) -> HE300BatchResult:
            nonlocal completed_count
            batch_id = f"batch-{batch_idx + 1:03d}"

            async with semaphore:
                if settings.EEE_ENABLED:
                    async with EEEClient() as client:
                        result = await client.evaluate_batch(
                            batch_id=batch_id,
                            scenarios=batch,
                            identity_id=identity_id,
                            guidance_id=guidance_id,
                        )
                else:
                    result = await _mock_evaluate_batch(batch_id, batch)

                completed_count += 1

                # Stream progress update
                await store.add_artifact(
                    task_id,
                    TaskArtifact(
                        name="batch_progress",
                        index=batch_idx,
                        parts=[
                            {
                                "type": "data",
                                "data": {
                                    "batch_id": batch_id,
                                    "batch_number": batch_idx + 1,
                                    "total_batches": len(batches),
                                    "scenarios_in_batch": result.total,
                                    "correct": result.correct,
                                    "accuracy": result.accuracy,
                                    "completed_batches": completed_count,
                                    "total_scenarios_completed": completed_count * batch_size,
                                },
                            }
                        ],
                    ),
                )

                await store.update_status(
                    task_id,
                    TaskState.WORKING,
                    message={
                        "role": "agent",
                        "parts": [
                            {
                                "type": "text",
                                "text": f"Batch {completed_count}/{len(batches)} complete "
                                        f"({result.accuracy:.1%} accuracy)",
                            }
                        ],
                    },
                )

                return result

        # Fire all batches concurrently
        batch_tasks = [
            process_batch(idx, batch) for idx, batch in enumerate(batches)
        ]
        all_batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)

        # Separate successes from errors
        results = []
        errors = []
        for br in all_batch_results:
            if isinstance(br, Exception):
                errors.append(str(br))
            else:
                results.append(br)

        # Aggregate results
        all_individual_results = []
        total_correct = 0
        total_count = 0
        total_errors = 0
        by_category: Dict[str, Dict[str, Any]] = {}

        for br in results:
            for r in br.results:
                all_individual_results.append({
                    "scenario_id": r.scenario_id,
                    "category": r.category,
                    "input_text": r.input_text,
                    "expected_label": r.expected_label,
                    "predicted_label": r.predicted_label,
                    "is_correct": r.is_correct,
                    "latency_ms": r.latency_ms,
                })
                total_count += 1
                if r.is_correct:
                    total_correct += 1
                if r.error:
                    total_errors += 1

                cat = r.category
                if cat not in by_category:
                    by_category[cat] = {"total": 0, "correct": 0}
                by_category[cat]["total"] += 1
                if r.is_correct:
                    by_category[cat]["correct"] += 1

        for cat_data in by_category.values():
            cat_data["accuracy"] = (
                cat_data["correct"] / cat_data["total"] if cat_data["total"] else 0.0
            )

        duration = time.time() - start_time

        # Build result bundle
        result_bundle = {
            "job_id": task_id,
            "status": "completed",
            "timestamp_start": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_time)
            ),
            "timestamp_end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "duration_seconds": round(duration, 2),
            "summary": {
                "total": total_count,
                "correct": total_correct,
                "accuracy": total_correct / total_count if total_count else 0.0,
                "errors": total_errors,
                "batch_errors": len(errors),
                "by_category": by_category,
            },
            "results": all_individual_results,
            "config": {
                "identity_id": identity_id,
                "guidance_id": guidance_id,
                "eee_enabled": settings.EEE_ENABLED,
                "batch_size": batch_size,
                "max_concurrent": max_concurrent,
            },
        }

        # Sign the result
        signable = {
            "job_id": result_bundle["job_id"],
            "summary": result_bundle["summary"],
            "timestamp_start": result_bundle["timestamp_start"],
            "timestamp_end": result_bundle["timestamp_end"],
        }
        result_bundle["signature"] = sign_data(signable).hex()
        result_bundle["public_key"] = get_public_key_pem()

        # Final artifact with complete results
        await store.add_artifact(
            task_id,
            TaskArtifact(
                name="evaluation_report",
                index=0,
                parts=[{"type": "data", "data": result_bundle}],
                last_chunk=True,
            ),
        )

        # Mark completed
        await store.update_status(
            task_id,
            TaskState.COMPLETED,
            message={
                "role": "agent",
                "parts": [
                    {
                        "type": "text",
                        "text": f"Evaluation complete: {total_correct}/{total_count} correct "
                                f"({total_correct/total_count:.1%} accuracy) in {duration:.1f}s",
                    }
                ],
            },
        )

        return result_bundle

    except Exception as e:
        logger.exception(f"Evaluation failed for task {task_id}")
        await store.update_status(
            task_id,
            TaskState.FAILED,
            message={
                "role": "agent",
                "parts": [{"type": "text", "text": f"Evaluation failed: {str(e)}"}],
            },
        )
        return {"error": str(e)}
