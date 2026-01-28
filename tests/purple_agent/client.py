"""
Baseline Purple Agent Client.

Demonstrates A2A and MCP connectivity with CIRISNode for testing
and as a reference implementation for purple agent developers.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class PurpleAgentClient:
    """
    A2A-compatible purple agent client for CIRISNode.

    Connects to a CIRISNode green agent to take the HE-300
    ethical benchmark evaluation.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: Optional[str] = None,
        jwt_token: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.jwt_token = jwt_token
        self._client: Optional[httpx.AsyncClient] = None

    def _auth_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.jwt_token:
            headers["Authorization"] = f"Bearer {self.jwt_token}"
        elif self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(600),  # 10 min for full benchmark
            headers=self._auth_headers(),
        )
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    # --- A2A Methods ---

    async def discover_agent(self) -> dict:
        """Fetch the agent card from /.well-known/agent.json."""
        resp = await self._client.get("/.well-known/agent.json")
        resp.raise_for_status()
        return resp.json()

    async def send_message(self, params: dict) -> dict:
        """Send a JSON-RPC message/send request."""
        body = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": params,
            "id": f"msg-{int(time.time())}",
        }
        resp = await self._client.post("/a2a", json=body)
        resp.raise_for_status()
        return resp.json()

    async def get_task(self, task_id: str) -> dict:
        """Poll task status via tasks/get."""
        body = {
            "jsonrpc": "2.0",
            "method": "tasks/get",
            "params": {"id": task_id},
            "id": f"get-{task_id[:8]}",
        }
        resp = await self._client.post("/a2a", json=body)
        resp.raise_for_status()
        return resp.json()

    async def list_tasks(self) -> dict:
        """List all tasks via tasks/list."""
        body = {
            "jsonrpc": "2.0",
            "method": "tasks/list",
            "params": {},
            "id": "list-tasks",
        }
        resp = await self._client.post("/a2a", json=body)
        resp.raise_for_status()
        return resp.json()

    async def cancel_task(self, task_id: str) -> dict:
        """Cancel a running task."""
        body = {
            "jsonrpc": "2.0",
            "method": "tasks/cancel",
            "params": {"id": task_id},
            "id": f"cancel-{task_id[:8]}",
        }
        resp = await self._client.post("/a2a", json=body)
        resp.raise_for_status()
        return resp.json()

    async def stream_task(self, task_id: str):
        """Stream task updates via SSE."""
        async with self._client.stream(
            "GET",
            f"/a2a/tasks/{task_id}/stream",
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    yield data

    # --- High-Level Workflows ---

    async def run_full_benchmark(
        self,
        n_scenarios: int = 300,
        category: Optional[str] = None,
        stream: bool = True,
    ) -> dict:
        """
        Run the full HE-300 benchmark.

        Args:
            n_scenarios: Number of scenarios (default 300)
            category: Optional category filter
            stream: Whether to stream progress updates

        Returns:
            Final evaluation result dict
        """
        logger.info(f"Starting HE-300 benchmark ({n_scenarios} scenarios)...")

        # Send evaluation request
        params = {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "type": "data",
                        "data": {
                            "skill": "he300_evaluation",
                            "n_scenarios": n_scenarios,
                            "category": category or "",
                        },
                    }
                ],
            }
        }

        response = await self.send_message(params)

        if "error" in response:
            logger.error(f"Failed to start benchmark: {response['error']}")
            return response

        task = response.get("result", {}).get("task", {})
        task_id = task.get("id")
        logger.info(f"Task created: {task_id}")

        if stream:
            return await self._stream_until_complete(task_id)
        else:
            return await self._poll_until_complete(task_id)

    async def run_scenarios(
        self,
        scenario_ids: List[str],
        stream: bool = True,
    ) -> dict:
        """Run specific scenarios by ID."""
        params = {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "type": "data",
                        "data": {
                            "skill": "he300_evaluation",
                            "scenario_ids": scenario_ids,
                        },
                    }
                ],
            }
        }

        response = await self.send_message(params)
        if "error" in response:
            return response

        task = response.get("result", {}).get("task", {})
        task_id = task.get("id")

        if stream:
            return await self._stream_until_complete(task_id)
        else:
            return await self._poll_until_complete(task_id)

    async def get_scenarios(self, category: Optional[str] = None) -> dict:
        """Fetch available scenarios."""
        params = {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "type": "data",
                        "data": {
                            "skill": "he300_scenarios",
                            "category": category or "",
                        },
                    }
                ],
            }
        }
        return await self.send_message(params)

    async def _poll_until_complete(
        self, task_id: str, interval: float = 2.0, timeout: float = 600.0
    ) -> dict:
        """Poll for task completion."""
        start = time.time()
        while time.time() - start < timeout:
            result = await self.get_task(task_id)
            task_data = result.get("result", {}).get("task", {})
            state = task_data.get("status", {}).get("state", "")

            if state in ("completed", "failed", "canceled", "rejected"):
                logger.info(f"Task {task_id} reached state: {state}")
                return task_data

            msg = task_data.get("status", {}).get("message", {})
            parts = msg.get("parts", []) if msg else []
            if parts:
                text = parts[0].get("text", "")
                logger.info(f"  [{state}] {text}")

            await asyncio.sleep(interval)

        return {"error": "timeout", "task_id": task_id}

    async def _stream_until_complete(self, task_id: str) -> dict:
        """Stream SSE events until task completion."""
        final_task = None
        try:
            async for event in self.stream_task(task_id):
                event_type = event.get("type", "")

                if event_type == "statusUpdate":
                    state = event.get("status", {}).get("state", "")
                    msg = event.get("status", {}).get("message", {})
                    parts = msg.get("parts", []) if msg else []
                    text = parts[0].get("text", "") if parts else ""
                    logger.info(f"  [{state}] {text}")

                elif event_type == "artifactUpdate":
                    artifact = event.get("artifact", {})
                    name = artifact.get("name", "")
                    if name == "batch_progress":
                        parts = artifact.get("parts", [])
                        if parts and parts[0].get("type") == "data":
                            d = parts[0]["data"]
                            logger.info(
                                f"  Batch {d.get('batch_number')}/{d.get('total_batches')} "
                                f"- {d.get('accuracy', 0):.1%} accuracy"
                            )

                elif event_type == "task":
                    final_task = event.get("task", {})

        except Exception as e:
            logger.warning(f"Stream ended: {e}")

        if final_task:
            return final_task

        # Fallback to poll
        result = await self.get_task(task_id)
        return result.get("result", {}).get("task", {})
