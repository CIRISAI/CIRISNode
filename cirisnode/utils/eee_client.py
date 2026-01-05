"""
EthicsEngine Enterprise HTTP Client

Async HTTP client for communicating with the EthicsEngine Enterprise API.
Used by CIRISNode to submit HE-300 benchmark scenarios for evaluation.
"""

import logging
import asyncio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

import httpx

from cirisnode.config import settings

logger = logging.getLogger(__name__)


class EEEClientError(Exception):
    """Base exception for EEE client errors."""
    pass


class EEEConnectionError(EEEClientError):
    """Failed to connect to EEE."""
    pass


class EEETimeoutError(EEEClientError):
    """EEE request timed out."""
    pass


class EEEAPIError(EEEClientError):
    """EEE returned an error response."""
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"EEE API error {status_code}: {detail}")


@dataclass
class HE300Scenario:
    """A single HE-300 benchmark scenario."""
    scenario_id: str
    category: str
    input_text: str
    expected_label: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class HE300Result:
    """Result of evaluating a single HE-300 scenario."""
    scenario_id: str
    category: str
    input_text: str
    expected_label: Optional[int]
    predicted_label: Optional[int]
    model_response: str
    is_correct: bool
    latency_ms: float
    error: Optional[str] = None


@dataclass 
class HE300BatchResult:
    """Result of evaluating a batch of HE-300 scenarios."""
    batch_id: str
    status: str  # "completed", "partial", "error"
    results: List[HE300Result]
    total: int
    correct: int
    accuracy: float
    avg_latency_ms: float
    errors: int
    processing_time_ms: float
    error_message: Optional[str] = None


class EEEClient:
    """
    Async HTTP client for EthicsEngine Enterprise API.
    
    Usage:
        async with EEEClient() as client:
            result = await client.evaluate_batch(scenarios)
    """
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[int] = None,
        retry_count: Optional[int] = None,
        retry_delay: Optional[float] = None,
    ):
        self.base_url = (base_url or settings.EEE_BASE_URL).rstrip("/")
        self.timeout = timeout or settings.EEE_TIMEOUT_SECONDS
        self.retry_count = retry_count or settings.EEE_RETRY_COUNT
        self.retry_delay = retry_delay or settings.EEE_RETRY_DELAY
        self._client: Optional[httpx.AsyncClient] = None
    
    async def __aenter__(self) -> "EEEClient":
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
            headers={"Content-Type": "application/json"},
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> httpx.Response:
        """Make HTTP request with retry logic."""
        if not self._client:
            raise EEEClientError("Client not initialized. Use 'async with EEEClient():'")
        
        last_error: Optional[Exception] = None
        
        for attempt in range(self.retry_count):
            try:
                response = await self._client.request(method, endpoint, **kwargs)
                
                # Raise for 4xx/5xx errors
                if response.status_code >= 400:
                    detail = response.text
                    try:
                        detail = response.json().get("detail", response.text)
                    except Exception:
                        pass
                    raise EEEAPIError(response.status_code, detail)
                
                return response
                
            except httpx.ConnectError as e:
                last_error = EEEConnectionError(f"Failed to connect to EEE at {self.base_url}: {e}")
                logger.warning(f"EEE connection failed (attempt {attempt + 1}/{self.retry_count}): {e}")
                
            except httpx.TimeoutException as e:
                last_error = EEETimeoutError(f"EEE request timed out after {self.timeout}s: {e}")
                logger.warning(f"EEE request timeout (attempt {attempt + 1}/{self.retry_count}): {e}")
                
            except EEEAPIError:
                # Don't retry API errors (4xx, 5xx)
                raise
                
            except Exception as e:
                last_error = EEEClientError(f"Unexpected error: {e}")
                logger.warning(f"EEE request error (attempt {attempt + 1}/{self.retry_count}): {e}")
            
            # Wait before retry (exponential backoff)
            if attempt < self.retry_count - 1:
                delay = self.retry_delay * (2 ** attempt)
                await asyncio.sleep(delay)
        
        raise last_error or EEEClientError("Request failed after all retries")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check EEE health status."""
        response = await self._request_with_retry("GET", "/health")
        return response.json()
    
    async def he300_health(self) -> Dict[str, Any]:
        """Check HE-300 subsystem health."""
        response = await self._request_with_retry("GET", "/he300/health")
        return response.json()
    
    async def get_catalog(
        self,
        category: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Get available HE-300 scenarios."""
        params = {"limit": limit, "offset": offset}
        if category:
            params["category"] = category
        
        response = await self._request_with_retry("GET", "/he300/catalog", params=params)
        return response.json()
    
    async def evaluate_batch(
        self,
        batch_id: str,
        scenarios: List[HE300Scenario],
        identity_id: str = "default_assistant",
        guidance_id: str = "default_ethical_guidance",
    ) -> HE300BatchResult:
        """
        Submit a batch of scenarios to EEE for evaluation.
        
        Args:
            batch_id: Unique identifier for this batch
            scenarios: List of scenarios to evaluate (max 50)
            identity_id: Identity profile for evaluation
            guidance_id: Ethical guidance framework
            
        Returns:
            HE300BatchResult with evaluation results and statistics
        """
        if len(scenarios) > settings.EEE_BATCH_SIZE:
            raise ValueError(f"Batch size {len(scenarios)} exceeds maximum {settings.EEE_BATCH_SIZE}")
        
        # Build request payload
        payload = {
            "batch_id": batch_id,
            "scenarios": [
                {
                    "scenario_id": s.scenario_id,
                    "category": s.category,
                    "input_text": s.input_text,
                    "expected_label": s.expected_label,
                    "metadata": s.metadata or {},
                }
                for s in scenarios
            ],
            "identity_id": identity_id,
            "guidance_id": guidance_id,
        }
        
        logger.info(f"Submitting HE-300 batch {batch_id} with {len(scenarios)} scenarios to EEE")
        
        response = await self._request_with_retry("POST", "/he300/batch", json=payload)
        data = response.json()
        
        # Parse results
        results = [
            HE300Result(
                scenario_id=r["scenario_id"],
                category=r["category"],
                input_text=r["input_text"],
                expected_label=r.get("expected_label"),
                predicted_label=r.get("predicted_label"),
                model_response=r.get("model_response", ""),
                is_correct=r.get("is_correct", False),
                latency_ms=r.get("latency_ms", 0),
                error=r.get("error"),
            )
            for r in data.get("results", [])
        ]
        
        summary = data.get("summary", {})
        
        return HE300BatchResult(
            batch_id=data["batch_id"],
            status=data["status"],
            results=results,
            total=summary.get("total", len(results)),
            correct=summary.get("correct", 0),
            accuracy=summary.get("accuracy", 0.0),
            avg_latency_ms=summary.get("avg_latency_ms", 0.0),
            errors=summary.get("errors", 0),
            processing_time_ms=data.get("processing_time_ms", 0),
            error_message=data.get("error_message"),
        )
    
    async def evaluate_scenarios_chunked(
        self,
        scenarios: List[HE300Scenario],
        batch_size: int = 50,
        identity_id: str = "default_assistant",
        guidance_id: str = "default_ethical_guidance",
    ) -> List[HE300BatchResult]:
        """
        Evaluate a large list of scenarios by chunking into batches.
        
        Args:
            scenarios: Full list of scenarios (can be > 50)
            batch_size: Size of each batch (default 50)
            identity_id: Identity profile for evaluation
            guidance_id: Ethical guidance framework
            
        Returns:
            List of batch results, one per chunk
        """
        results = []
        
        for i in range(0, len(scenarios), batch_size):
            chunk = scenarios[i:i + batch_size]
            batch_id = f"batch-{i // batch_size + 1:03d}"
            
            result = await self.evaluate_batch(
                batch_id=batch_id,
                scenarios=chunk,
                identity_id=identity_id,
                guidance_id=guidance_id,
            )
            results.append(result)
            
            logger.info(
                f"Completed batch {batch_id}: {result.correct}/{result.total} correct "
                f"({result.accuracy:.2%})"
            )
        
        return results


# --- Utility Functions ---

async def check_eee_available() -> bool:
    """Quick check if EEE is available and healthy."""
    if not settings.EEE_ENABLED:
        return False
    
    try:
        async with EEEClient() as client:
            health = await client.health_check()
            return health.get("status") == "healthy"
    except Exception as e:
        logger.warning(f"EEE health check failed: {e}")
        return False


async def get_eee_scenarios(
    category: Optional[str] = None,
    limit: int = 300,
) -> List[HE300Scenario]:
    """Fetch HE-300 scenarios from EEE catalog."""
    async with EEEClient() as client:
        catalog = await client.get_catalog(category=category, limit=limit)
        
        return [
            HE300Scenario(
                scenario_id=s["scenario_id"],
                category=s["category"],
                input_text=s["input_text"],
                expected_label=s.get("expected_label"),
            )
            for s in catalog.get("scenarios", [])
        ]
