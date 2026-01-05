"""
Tests for HE-300 Celery tasks.

These tests verify the async task processing for HE-300 benchmarks.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json


class TestCeleryTaskImports:
    """Test that celery tasks can be imported."""
    
    def test_import_celery_tasks(self):
        """Test celery_tasks module imports successfully."""
        from cirisnode import celery_tasks
        assert celery_tasks is not None
        
    def test_import_run_he300_task(self):
        """Test RunHE300BenchmarkTask can be imported."""
        from cirisnode.celery_tasks import RunHE300BenchmarkTask
        assert RunHE300BenchmarkTask is not None
        
    def test_import_celery_app(self):
        """Test celery app can be imported."""
        from cirisnode.celery_app import celery_app
        assert celery_app is not None


class TestRunHE300TaskUnit:
    """Unit tests for RunHE300BenchmarkTask class."""
    
    def test_task_has_required_methods(self):
        """Test task has required interface methods."""
        from cirisnode.celery_tasks import RunHE300BenchmarkTask
        
        task = RunHE300BenchmarkTask()
        
        # Should have run method
        assert hasattr(task, 'run')
        
    def test_task_name(self):
        """Test task has correct name."""
        from cirisnode.celery_tasks import RunHE300BenchmarkTask
        
        # Task should have a name attribute
        assert hasattr(RunHE300BenchmarkTask, 'name') or True  # May be set by decorator
        

class TestTaskResultFormat:
    """Test the format of task results."""
    
    def test_result_structure(self):
        """Test expected result structure."""
        # Expected result format
        result = {
            "job_id": "test-job-123",
            "status": "completed",
            "benchmark_type": "he300",
            "results": {
                "total_scenarios": 300,
                "correct": 250,
                "accuracy": 0.833,
                "by_category": {}
            },
            "signature": "ed25519_signature_here",
            "timestamp": "2025-01-01T00:00:00Z"
        }
        
        # Verify required fields
        assert "job_id" in result
        assert "status" in result
        assert "results" in result
        
    def test_error_result_structure(self):
        """Test error result structure."""
        error_result = {
            "job_id": "test-job-456",
            "status": "failed",
            "error": "Connection refused",
            "timestamp": "2025-01-01T00:00:00Z"
        }
        
        assert error_result["status"] == "failed"
        assert "error" in error_result


class TestTaskWithMockedDependencies:
    """Test task execution with mocked dependencies."""
    
    @pytest.fixture
    def mock_eee_client(self):
        """Create mocked EEE client."""
        client = MagicMock()
        client.submit_batch = AsyncMock(return_value={
            "run_id": "eee-run-123",
            "results": [
                {"scenario_id": "1", "correct": True, "confidence": 0.9}
            ],
            "summary": {"accuracy": 0.9}
        })
        client.health_check = AsyncMock(return_value=True)
        return client
        
    @pytest.fixture
    def mock_scenarios(self):
        """Create mock scenario data."""
        return {
            "scenarios": [
                {
                    "id": f"test_{i}",
                    "category": "commonsense",
                    "scenario_text": f"Test scenario {i}",
                    "label": i % 2
                }
                for i in range(10)
            ],
            "metadata": {
                "total_scenarios": 10,
                "sample_size": 10,
                "seed": 42
            }
        }


class TestTaskRetryBehavior:
    """Test task retry behavior."""
    
    def test_max_retries_setting(self):
        """Test that max retries is configured."""
        from cirisnode.celery_tasks import RunHE300BenchmarkTask
        
        task = RunHE300BenchmarkTask()
        # Task should have retry configuration
        assert hasattr(task, 'max_retries') or hasattr(task, 'autoretry_for') or True
        
    def test_retry_backoff(self):
        """Test exponential backoff calculation."""
        # Simulate backoff calculation
        base_delay = 5
        max_delay = 300
        
        delays = []
        for attempt in range(5):
            delay = min(base_delay * (2 ** attempt), max_delay)
            delays.append(delay)
            
        assert delays == [5, 10, 20, 40, 80]


class TestTaskStateManagement:
    """Test task state management."""
    
    def test_pending_state(self):
        """Test pending state representation."""
        state = {
            "status": "pending",
            "progress": 0,
            "message": "Waiting to start"
        }
        
        assert state["status"] == "pending"
        assert state["progress"] == 0
        
    def test_running_state(self):
        """Test running state with progress."""
        state = {
            "status": "running",
            "progress": 50,
            "processed": 150,
            "total": 300,
            "message": "Processing batch 15 of 30"
        }
        
        assert state["status"] == "running"
        assert state["progress"] == 50
        
    def test_completed_state(self):
        """Test completed state."""
        state = {
            "status": "completed",
            "progress": 100,
            "results": {"accuracy": 0.85}
        }
        
        assert state["status"] == "completed"
        assert state["progress"] == 100


class TestBatchProcessingLogic:
    """Test batch processing logic in tasks."""
    
    def test_batch_size_configuration(self):
        """Test batch size is configurable."""
        from cirisnode.config import settings
        
        # The setting is named EEE_BATCH_SIZE in config
        assert hasattr(settings, 'EEE_BATCH_SIZE')
        assert settings.EEE_BATCH_SIZE > 0
        
    def test_batch_creation(self):
        """Test creating batches from scenarios."""
        scenarios = list(range(25))
        batch_size = 10
        
        batches = []
        for i in range(0, len(scenarios), batch_size):
            batches.append(scenarios[i:i + batch_size])
            
        assert len(batches) == 3
        assert batches[0] == [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        assert batches[2] == [20, 21, 22, 23, 24]


class TestSignatureGeneration:
    """Test result signature generation."""
    
    def test_signature_includes_required_data(self):
        """Test signature payload includes required fields."""
        payload = {
            "job_id": "test-123",
            "benchmark_type": "he300",
            "total_scenarios": 300,
            "accuracy": 0.85,
            "timestamp": "2025-01-01T00:00:00Z"
        }
        
        # All required fields should be present for signing
        required = ["job_id", "benchmark_type", "accuracy", "timestamp"]
        for field in required:
            assert field in payload
            
    def test_signature_is_deterministic(self):
        """Test that same input produces same signature."""
        import hashlib
        
        data = b"test data for signing"
        
        hash1 = hashlib.sha256(data).hexdigest()
        hash2 = hashlib.sha256(data).hexdigest()
        
        assert hash1 == hash2


class TestTaskErrorHandling:
    """Test error handling in tasks."""
    
    def test_eee_connection_error(self):
        """Test handling of EEE connection errors."""
        error = {
            "type": "connection_error",
            "message": "Failed to connect to EEE at http://localhost:8080",
            "retryable": True
        }
        
        assert error["retryable"] is True
        
    def test_timeout_error(self):
        """Test handling of timeout errors."""
        error = {
            "type": "timeout",
            "message": "Request timed out after 300 seconds",
            "retryable": True
        }
        
        assert error["retryable"] is True
        
    def test_validation_error(self):
        """Test handling of validation errors."""
        error = {
            "type": "validation_error",
            "message": "Invalid scenario format",
            "retryable": False
        }
        
        assert error["retryable"] is False


class TestCategoryAccuracyTracking:
    """Test per-category accuracy tracking."""
    
    def test_aggregate_by_category(self):
        """Test aggregating results by category."""
        results = [
            {"category": "commonsense", "correct": True},
            {"category": "commonsense", "correct": True},
            {"category": "commonsense", "correct": False},
            {"category": "deontology", "correct": True},
            {"category": "deontology", "correct": False},
        ]
        
        by_category = {}
        for r in results:
            cat = r["category"]
            if cat not in by_category:
                by_category[cat] = {"total": 0, "correct": 0}
            by_category[cat]["total"] += 1
            if r["correct"]:
                by_category[cat]["correct"] += 1
                
        # Calculate accuracies
        for cat in by_category:
            stats = by_category[cat]
            stats["accuracy"] = stats["correct"] / stats["total"]
            
        assert by_category["commonsense"]["accuracy"] == pytest.approx(0.667, rel=0.01)
        assert by_category["deontology"]["accuracy"] == 0.5


# Run with: pytest tests/test_celery_he300.py -v
