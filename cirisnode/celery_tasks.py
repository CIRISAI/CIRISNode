"""
CIRISNode Celery Tasks

Async task definitions for benchmark execution.
Includes HE-300 integration with EthicsEngine Enterprise.
"""

import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional
from uuid import uuid4

from celery import Task
from cirisnode.celery_app import celery_app
from cirisnode.config import settings

logger = logging.getLogger(__name__)


class RunSimpleBenchTask(Task):
    name = "run_simplebench_task"

    def run(self):
        pass


class RunBenchmarkTask(Task):
    name = "run_benchmark_task"

    def run(self):
        pass


run_simplebench_task = RunSimpleBenchTask()
run_benchmark_task = RunBenchmarkTask()

# Register tasks
celery_app.tasks.register(run_simplebench_task)
celery_app.tasks.register(run_benchmark_task)


# --- HE-300 Benchmark Task ---

class RunHE300BenchmarkTask(Task):
    """
    Celery task for executing HE-300 benchmark scenarios via EthicsEngine Enterprise.
    
    This task:
    1. Loads HE-300 scenarios (from disk or EEE API)
    2. Batches scenarios (max 50 per batch)
    3. Sends batches to EEE for evaluation
    4. Aggregates results
    5. Signs the result bundle using Ed25519
    6. Stores results in database/cache
    """
    name = "run_he300_benchmark_task"
    
    # Task options
    bind = True
    max_retries = 3
    default_retry_delay = 60  # 1 minute between retries
    
    def run(
        self,
        job_id: str,
        scenario_ids: Optional[List[str]] = None,
        category: Optional[str] = None,
        model_config: Optional[Dict[str, Any]] = None,
        n_scenarios: int = 300,
        identity_id: str = "default_assistant",
        guidance_id: str = "default_ethical_guidance",
    ) -> Dict[str, Any]:
        """
        Execute HE-300 benchmark.
        
        Args:
            job_id: Unique identifier for this benchmark run
            scenario_ids: Specific scenario IDs to run (optional)
            category: Filter by category (optional)
            model_config: LLM configuration overrides (optional)
            n_scenarios: Number of scenarios to run (default 300)
            identity_id: Identity profile for evaluation
            guidance_id: Ethical guidance framework
            
        Returns:
            Dict with results, summary, and signature
        """
        logger.info(f"Starting HE-300 benchmark job {job_id}")
        
        # Run the async implementation
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                self._run_benchmark_async(
                    job_id=job_id,
                    scenario_ids=scenario_ids,
                    category=category,
                    model_config=model_config,
                    n_scenarios=n_scenarios,
                    identity_id=identity_id,
                    guidance_id=guidance_id,
                )
            )
            return result
        finally:
            loop.close()
    
    async def _run_benchmark_async(
        self,
        job_id: str,
        scenario_ids: Optional[List[str]],
        category: Optional[str],
        model_config: Optional[Dict[str, Any]],
        n_scenarios: int,
        identity_id: str,
        guidance_id: str,
    ) -> Dict[str, Any]:
        """Async implementation of the benchmark."""
        from cirisnode.utils.data_loaders import load_he300_data, sample_he300_scenarios
        from cirisnode.utils.signer import sign_data, get_public_key_pem
        
        start_time = datetime.utcnow()
        all_results = []

        try:
            # Step 1: Load or sample scenarios
            if scenario_ids:
                # Load specific scenarios
                all_scenarios = load_he300_data(category=category)
                scenarios = [s for s in all_scenarios if s["id"] in scenario_ids]
            else:
                # Sample balanced set
                scenarios = sample_he300_scenarios(
                    n_per_category=n_scenarios // 4,  # Divide among 4 main categories
                    seed=42,  # Reproducible sampling
                )
            
            logger.info(f"Job {job_id}: Loaded {len(scenarios)} scenarios")
            
            # Step 2: Check if EEE is enabled
            if settings.EEE_ENABLED:
                # Use EEE API for evaluation
                all_results = await self._evaluate_via_eee(
                    job_id=job_id,
                    scenarios=scenarios,
                    identity_id=identity_id,
                    guidance_id=guidance_id,
                )
            else:
                # Fallback: Return mock results (for testing without EEE)
                logger.warning(f"Job {job_id}: EEE disabled, returning mock results")
                all_results = self._generate_mock_results(scenarios)
            
            # Step 3: Calculate summary statistics
            total = len(all_results)
            correct = sum(1 for r in all_results if r.get("is_correct", False))
            errors_count = sum(1 for r in all_results if r.get("error"))
            accuracy = correct / total if total > 0 else 0.0
            
            # Calculate per-category stats
            by_category: Dict[str, Dict] = {}
            for r in all_results:
                cat = r.get("category", "unknown")
                if cat not in by_category:
                    by_category[cat] = {"total": 0, "correct": 0}
                by_category[cat]["total"] += 1
                if r.get("is_correct"):
                    by_category[cat]["correct"] += 1
            
            for cat, stats in by_category.items():
                stats["accuracy"] = stats["correct"] / stats["total"] if stats["total"] > 0 else 0.0
            
            end_time = datetime.utcnow()
            duration_seconds = (end_time - start_time).total_seconds()
            
            # Step 4: Build result bundle
            result_bundle = {
                "job_id": job_id,
                "status": "completed" if errors_count == 0 else "partial",
                "timestamp_start": start_time.isoformat(),
                "timestamp_end": end_time.isoformat(),
                "duration_seconds": duration_seconds,
                "summary": {
                    "total": total,
                    "correct": correct,
                    "accuracy": accuracy,
                    "errors": errors_count,
                    "by_category": by_category,
                },
                "results": all_results,
                "config": {
                    "identity_id": identity_id,
                    "guidance_id": guidance_id,
                    "eee_enabled": settings.EEE_ENABLED,
                    "eee_base_url": settings.EEE_BASE_URL if settings.EEE_ENABLED else None,
                },
            }
            
            # Step 5: Sign the result bundle
            try:
                signature = sign_data(result_bundle)
                result_bundle["signature"] = signature.hex()
                result_bundle["public_key"] = get_public_key_pem()
            except Exception as e:
                logger.error(f"Job {job_id}: Failed to sign results: {e}")
                result_bundle["signature"] = None
                result_bundle["signature_error"] = str(e)
            
            logger.info(
                f"Job {job_id}: Completed. {correct}/{total} correct ({accuracy:.2%}), "
                f"{errors_count} errors, {duration_seconds:.1f}s"
            )
            
            return result_bundle
            
        except Exception as e:
            logger.error(f"Job {job_id}: Benchmark failed: {e}", exc_info=True)
            return {
                "job_id": job_id,
                "status": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }
    
    async def _evaluate_via_eee(
        self,
        job_id: str,
        scenarios: List[Dict[str, Any]],
        identity_id: str,
        guidance_id: str,
    ) -> List[Dict[str, Any]]:
        """Send scenarios to EEE API for evaluation."""
        from cirisnode.utils.eee_client import EEEClient, HE300Scenario
        
        all_results = []
        batch_size = settings.EEE_BATCH_SIZE
        
        async with EEEClient() as client:
            # Process in batches
            for i in range(0, len(scenarios), batch_size):
                batch = scenarios[i:i + batch_size]
                batch_id = f"{job_id}-batch-{i // batch_size + 1:03d}"
                
                # Convert to EEE format
                eee_scenarios = [
                    HE300Scenario(
                        scenario_id=s["id"],
                        category=s.get("category", "commonsense"),
                        input_text=s["prompt"],
                        expected_label=s.get("expected_label"),
                    )
                    for s in batch
                ]
                
                try:
                    result = await client.evaluate_batch(
                        batch_id=batch_id,
                        scenarios=eee_scenarios,
                        identity_id=identity_id,
                        guidance_id=guidance_id,
                    )
                    
                    # Convert results to our format
                    for r in result.results:
                        all_results.append({
                            "scenario_id": r.scenario_id,
                            "category": r.category,
                            "input_text": r.input_text,
                            "expected_label": r.expected_label,
                            "predicted_label": r.predicted_label,
                            "model_response": r.model_response,
                            "is_correct": r.is_correct,
                            "latency_ms": r.latency_ms,
                            "error": r.error,
                        })
                    
                    logger.info(
                        f"Job {job_id}: Batch {batch_id} - "
                        f"{result.correct}/{result.total} correct"
                    )
                    
                except Exception as e:
                    logger.error(f"Job {job_id}: Batch {batch_id} failed: {e}")
                    # Add error results for failed batch
                    for s in batch:
                        all_results.append({
                            "scenario_id": s["id"],
                            "category": s.get("category", "unknown"),
                            "input_text": s["prompt"],
                            "expected_label": s.get("expected_label"),
                            "predicted_label": None,
                            "model_response": "",
                            "is_correct": False,
                            "latency_ms": 0,
                            "error": str(e),
                        })
        
        return all_results
    
    def _generate_mock_results(
        self,
        scenarios: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Generate mock results for testing when EEE is disabled."""
        import random
        
        results = []
        for s in scenarios:
            # Mock: 80% accuracy for testing
            predicted = s.get("expected_label", 0) if random.random() < 0.8 else (1 - s.get("expected_label", 0))
            is_correct = predicted == s.get("expected_label")
            
            results.append({
                "scenario_id": s["id"],
                "category": s.get("category", "unknown"),
                "input_text": s["prompt"],
                "expected_label": s.get("expected_label"),
                "predicted_label": predicted,
                "model_response": f"Mock response for {s['id']}",
                "is_correct": is_correct,
                "latency_ms": random.uniform(50, 200),
                "error": None,
            })
        
        return results


# Instantiate and register the task
run_he300_benchmark_task = RunHE300BenchmarkTask()
celery_app.tasks.register(run_he300_benchmark_task)


# --- Convenience function for direct invocation ---

def run_he300_scenario_task(
    job_id: Optional[str] = None,
    scenario_ids: Optional[List[str]] = None,
    **kwargs
) -> str:
    """
    Queue an HE-300 benchmark task.
    
    Returns the job_id for status polling.
    """
    if job_id is None:
        job_id = f"he300-{uuid4().hex[:8]}"
    
    # Queue the task
    run_he300_benchmark_task.delay(
        job_id=job_id,
        scenario_ids=scenario_ids,
        **kwargs
    )
    
    return job_id

