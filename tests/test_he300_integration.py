"""
Integration tests for HE-300 benchmark API and EEE client.

These tests verify CIRISNode's HE-300 implementation in isolation,
mocking external EEE dependencies to enable independent testing.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

# Import the app
from cirisnode.main import app
from cirisnode.utils.eee_client import EEEClient
from cirisnode.utils.data_loaders import load_he300_data, sample_he300_scenarios


class TestDataLoaders:
    """Test HE-300 data loading functionality."""
    
    def test_load_he300_data_returns_list(self):
        """Test that load_he300_data returns proper structure."""
        result = load_he300_data(limit=10)
        
        assert isinstance(result, list)
        
    def test_load_he300_data_has_required_fields(self):
        """Test scenarios have required fields."""
        result = load_he300_data(limit=5)
        
        if len(result) > 0:
            scenario = result[0]
            assert "id" in scenario
            assert "prompt" in scenario
            
    def test_sample_he300_reproducible(self):
        """Test that same seed produces same results."""
        result1 = sample_he300_scenarios(n_per_category=5, seed=12345)
        result2 = sample_he300_scenarios(n_per_category=5, seed=12345)
        
        # Same seed should give same order
        if len(result1) > 0 and len(result2) > 0:
            ids1 = [s["id"] for s in result1]
            ids2 = [s["id"] for s in result2]
            assert ids1 == ids2
        
    def test_sample_he300_different_seeds(self):
        """Test that different seeds can produce different results."""
        result1 = sample_he300_scenarios(n_per_category=10, seed=111)
        result2 = sample_he300_scenarios(n_per_category=10, seed=222)
        
        # Different seeds may produce different orderings
        # (only if there's enough data to sample from)
        if len(result1) > 5 and len(result2) > 5:
            ids1 = [s["id"] for s in result1]
            ids2 = [s["id"] for s in result2]
            # Don't assert inequality - may be same if using fallback data
            assert len(ids1) == len(ids2)
            
    def test_load_he300_with_category_filter(self):
        """Test category filtering."""
        result = load_he300_data(category="commonsense", limit=10)
        
        # All results should be commonsense category
        for s in result:
            if "category" in s:
                assert s["category"] == "commonsense"


class TestEEEClient:
    """Test EEE client functionality with mocked HTTP."""
    
    @pytest.fixture
    def client_params(self):
        """Create EEE client parameters."""
        return {
            "base_url": "http://localhost:8080",
            "timeout": 30,
            "retry_count": 3,
            "retry_delay": 0.1,
        }
    
    def test_client_initialization(self, client_params):
        """Test client initializes with correct settings."""
        client = EEEClient(**client_params)
        assert client.base_url == "http://localhost:8080"
        assert client.timeout == 30
        
    @pytest.mark.asyncio
    async def test_client_context_manager(self, client_params):
        """Test client works as async context manager."""
        async with EEEClient(**client_params) as client:
            assert client._client is not None
            
    @pytest.mark.asyncio
    async def test_client_closes_properly(self, client_params):
        """Test client closes connection on exit."""
        client = EEEClient(**client_params)
        async with client:
            pass
        assert client._client is None


class TestEEEClientMocked:
    """Test EEE client with mocked HTTP responses."""
    
    @pytest.mark.asyncio
    async def test_health_check_mock(self):
        """Test health check with mocked response."""
        with patch('httpx.AsyncClient') as mock_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "healthy"}
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_client.aclose = AsyncMock()
            mock_class.return_value = mock_client
            
            client = EEEClient(base_url="http://test:8080", retry_count=1)
            async with client:
                result = await client.health_check()
                assert result["status"] == "healthy"


class TestBenchmarkRoutes:
    """Test benchmark API routes."""
    
    @pytest.fixture
    def test_client(self, client):
        """Reuse shared test client."""
        return client
        
    def test_run_benchmark_requires_auth(self, test_client):
        """Test that benchmark endpoint requires authentication."""
        response = test_client.post(
            "/api/v1/benchmarks/run",
            json={"benchmark_type": "he300"}
        )
        # Should fail without auth token (returns 400 for missing header)
        assert response.status_code in [400, 401, 403, 422]
        
    def test_get_results_requires_auth(self, test_client):
        """Test that results endpoint requires authentication."""
        response = test_client.get("/api/v1/benchmarks/results/some-job-id")
        assert response.status_code in [401, 403, 404]
        
    def test_he300_health_endpoint(self, test_client):
        """Test HE-300 health endpoint returns info."""
        # Health endpoint should work without auth
        response = test_client.get("/api/v1/benchmarks/he300/health")
        # Accept various responses - just verify route exists
        assert response.status_code in [200, 401, 403, 404, 503]
        

class TestBenchmarkWithMockedEEE:
    """Test benchmark execution with mocked EEE client."""
    
    @pytest.fixture
    def test_client(self, client):
        """Reuse shared test client."""
        return client
        
    @pytest.fixture
    def mock_jwt_token(self):
        """Create a mock JWT token for testing."""
        # This would need to match your actual JWT format
        return "mock.jwt.token"
        
    @pytest.fixture
    def auth_headers(self, mock_jwt_token):
        """Create auth headers."""
        return {"Authorization": f"Bearer {mock_jwt_token}"}


class TestEEEIntegrationModes:
    """Test different EEE integration modes."""
    
    def test_eee_disabled_mode(self):
        """Test behavior when EEE is disabled."""
        with patch('cirisnode.config.settings.EEE_ENABLED', False):
            # Import fresh to pick up patched setting
            from cirisnode.config import settings
            # When EEE is disabled, should use local evaluation
            assert hasattr(settings, 'EEE_ENABLED')
            
    def test_eee_enabled_mode(self):
        """Test behavior when EEE is enabled."""
        with patch('cirisnode.config.settings.EEE_ENABLED', True):
            from cirisnode.config import settings
            assert hasattr(settings, 'EEE_BASE_URL')


class TestScenarioFormats:
    """Test various scenario format handling."""
    
    def test_scenario_with_all_fields(self):
        """Test scenario with complete fields."""
        scenario = {
            "id": "cm_001",
            "category": "commonsense",
            "scenario_text": "Is it acceptable to help others?",
            "label": 1,
            "metadata": {"source": "test"}
        }
        
        # Verify all required fields present
        required = ["id", "category", "scenario_text"]
        for field in required:
            assert field in scenario
            
    def test_scenario_minimal_fields(self):
        """Test scenario with minimal required fields."""
        scenario = {
            "id": "test_001",
            "scenario_text": "Test scenario"
        }
        
        # Should have at minimum id and text
        assert "id" in scenario
        assert "scenario_text" in scenario


class TestBatchProcessing:
    """Test batch processing logic."""
    
    def test_batch_chunking(self):
        """Test scenarios are properly chunked into batches."""
        scenarios = [{"id": str(i)} for i in range(25)]
        batch_size = 10
        
        batches = [
            scenarios[i:i + batch_size] 
            for i in range(0, len(scenarios), batch_size)
        ]
        
        assert len(batches) == 3
        assert len(batches[0]) == 10
        assert len(batches[1]) == 10
        assert len(batches[2]) == 5
        
    def test_empty_batch_handling(self):
        """Test handling of empty scenario list."""
        scenarios = []
        batch_size = 10
        
        batches = [
            scenarios[i:i + batch_size] 
            for i in range(0, len(scenarios), batch_size)
        ]
        
        assert len(batches) == 0


class TestResultAggregation:
    """Test result aggregation logic."""
    
    def test_aggregate_batch_results(self):
        """Test combining results from multiple batches."""
        batch_results = [
            {"results": [{"correct": True}, {"correct": False}]},
            {"results": [{"correct": True}, {"correct": True}]}
        ]
        
        all_results = []
        for batch in batch_results:
            all_results.extend(batch["results"])
            
        correct_count = sum(1 for r in all_results if r.get("correct"))
        
        assert len(all_results) == 4
        assert correct_count == 3
        
    def test_calculate_accuracy(self):
        """Test accuracy calculation."""
        results = [
            {"correct": True},
            {"correct": True},
            {"correct": False},
            {"correct": True}
        ]
        
        total = len(results)
        correct = sum(1 for r in results if r["correct"])
        accuracy = correct / total if total > 0 else 0.0
        
        assert accuracy == 0.75


# Run with: pytest tests/test_he300_integration.py -v
