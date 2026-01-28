"""
Integration tests for MCP server implementation.
"""

import json
import pytest

from cirisnode.mcp.server import (
    list_he300_scenarios,
    get_he300_categories,
    run_he300_scenario,
    run_he300_batch,
    get_evaluation_report,
)


class TestMCPTools:
    """Tests for MCP tool functions."""

    @pytest.mark.asyncio
    async def test_list_scenarios(self):
        result = await list_he300_scenarios()
        data = json.loads(result)
        assert "total" in data
        assert "scenarios" in data
        assert "categories" in data
        assert data["total"] >= 0

    @pytest.mark.asyncio
    async def test_list_scenarios_with_category(self):
        result = await list_he300_scenarios(category="commonsense")
        data = json.loads(result)
        for s in data["scenarios"]:
            assert s["category"] == "commonsense"

    @pytest.mark.asyncio
    async def test_get_categories(self):
        result = await get_he300_categories()
        data = json.loads(result)
        assert "categories" in data
        cats = data["categories"]
        assert "commonsense" in cats
        assert "deontology" in cats
        assert "justice" in cats
        assert "virtue" in cats

    @pytest.mark.asyncio
    async def test_run_scenario_not_found(self):
        result = await run_he300_scenario(
            scenario_id="NONEXISTENT-ID",
            agent_response="test response",
        )
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_run_batch_no_scenarios(self):
        """Batch with no matching IDs should return error."""
        result = await run_he300_batch(
            scenario_ids=["NONEXISTENT-1", "NONEXISTENT-2"],
        )
        data = json.loads(result)
        # Either empty results or error
        assert "error" in data or data.get("total", 0) == 0

    @pytest.mark.asyncio
    async def test_get_report_not_found(self):
        result = await get_evaluation_report(job_id="nonexistent-job")
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_run_batch_with_fallback_data(self):
        """Test batch evaluation using fallback scenarios (no EEE)."""
        result = await run_he300_batch(n_scenarios=3)
        data = json.loads(result)
        # Should get results (mock or real)
        assert "total" in data or "error" in data
        if "total" in data:
            assert data["total"] >= 0
            assert "accuracy" in data
            assert "signature" in data
            assert "public_key" in data


class TestMCPResources:
    """Tests for MCP resource definitions."""

    @pytest.mark.asyncio
    async def test_scenarios_resource(self):
        from cirisnode.mcp.server import scenarios_resource

        result = await scenarios_resource()
        data = json.loads(result)
        assert "total" in data
        assert "scenarios" in data

    @pytest.mark.asyncio
    async def test_categories_resource(self):
        from cirisnode.mcp.server import categories_resource

        result = await categories_resource()
        data = json.loads(result)
        assert "categories" in data

    @pytest.mark.asyncio
    async def test_health_resource(self):
        from cirisnode.mcp.server import health_resource

        result = await health_resource()
        data = json.loads(result)
        assert data["status"] == "healthy"
        assert "version" in data
