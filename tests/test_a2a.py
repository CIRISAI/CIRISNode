"""
Integration tests for A2A protocol implementation.
"""

import pytest

import jwt

from cirisnode.config import settings
from cirisnode.api.a2a.tasks import TaskState, TaskStore
from cirisnode.api.a2a.jsonrpc import handle_jsonrpc

# Test JWT token — use the actual settings JWT_SECRET so auth validation passes
TEST_SECRET = settings.JWT_SECRET
TEST_TOKEN = jwt.encode(
    {"sub": "test_agent", "role": "admin"},
    TEST_SECRET,
    algorithm="HS256",
)
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_TOKEN}"}


class TestAgentCard:
    """Tests for /.well-known/agent.json endpoint."""

    def test_agent_card_returns_200(self, client):
        resp = client.get("/.well-known/agent.json")
        assert resp.status_code == 200

    def test_agent_card_has_required_fields(self, client):
        resp = client.get("/.well-known/agent.json")
        card = resp.json()
        assert "name" in card
        assert "description" in card
        assert "version" in card
        assert "protocolVersions" in card
        assert "skills" in card
        assert "capabilities" in card

    def test_agent_card_has_skills(self, client):
        resp = client.get("/.well-known/agent.json")
        card = resp.json()
        skills = card["skills"]
        assert len(skills) >= 1
        skill_ids = [s["id"] for s in skills]
        assert "he300_evaluation" in skill_ids

    def test_agent_card_has_security_schemes(self, client):
        resp = client.get("/.well-known/agent.json")
        card = resp.json()
        assert "securitySchemes" in card
        assert "bearer" in card["securitySchemes"]
        assert "apiKey" in card["securitySchemes"]

    def test_agent_card_no_auth_required(self, client):
        """Agent card must be accessible without authentication."""
        resp = client.get("/.well-known/agent.json")
        assert resp.status_code == 200


class TestA2AJSONRPC:
    """Tests for /a2a JSON-RPC endpoint."""

    def test_requires_auth(self, client):
        resp = client.post(
            "/a2a",
            json={"jsonrpc": "2.0", "method": "tasks/list", "id": "1"},
        )
        assert resp.status_code == 401

    def test_invalid_jsonrpc_version(self, client):
        resp = client.post(
            "/a2a",
            json={"jsonrpc": "1.0", "method": "test", "id": "1"},
            headers=AUTH_HEADERS,
        )
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == -32600

    def test_unknown_method(self, client):
        resp = client.post(
            "/a2a",
            json={"jsonrpc": "2.0", "method": "unknown/method", "id": "1"},
            headers=AUTH_HEADERS,
        )
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == -32601

    def test_tasks_list_empty(self, client):
        resp = client.post(
            "/a2a",
            json={"jsonrpc": "2.0", "method": "tasks/list", "params": {}, "id": "1"},
            headers=AUTH_HEADERS,
        )
        data = resp.json()
        assert "result" in data
        assert "tasks" in data["result"]

    def test_message_send_creates_task(self, client):
        resp = client.post(
            "/a2a",
            json={
                "jsonrpc": "2.0",
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [
                            {
                                "type": "data",
                                "data": {
                                    "skill": "he300_evaluation",
                                    "n_scenarios": 3,
                                },
                            }
                        ],
                    }
                },
                "id": "2",
            },
            headers=AUTH_HEADERS,
        )
        data = resp.json()
        assert "result" in data
        assert "task" in data["result"]
        task = data["result"]["task"]
        assert "id" in task
        assert task["status"]["state"] in ("submitted", "working")

    def test_message_send_scenarios_skill(self, client):
        resp = client.post(
            "/a2a",
            json={
                "jsonrpc": "2.0",
                "method": "message/send",
                "params": {
                    "message": {
                        "role": "user",
                        "parts": [
                            {
                                "type": "data",
                                "data": {
                                    "skill": "he300_scenarios",
                                    "limit": 5,
                                },
                            }
                        ],
                    }
                },
                "id": "3",
            },
            headers=AUTH_HEADERS,
        )
        data = resp.json()
        assert "result" in data
        result = data["result"]
        assert "message" in result

    def test_tasks_get_not_found(self, client):
        resp = client.post(
            "/a2a",
            json={
                "jsonrpc": "2.0",
                "method": "tasks/get",
                "params": {"id": "nonexistent-id"},
                "id": "4",
            },
            headers=AUTH_HEADERS,
        )
        data = resp.json()
        assert "result" in data or "error" in data


class TestTaskStore:
    """Tests for the in-memory task store."""

    @pytest.fixture
    def store(self):
        return TaskStore(ttl_seconds=60)

    @pytest.mark.asyncio
    async def test_create_task(self, store):
        task = await store.create_task(metadata={"test": True})
        assert task.id
        assert task.status.state == TaskState.SUBMITTED

    @pytest.mark.asyncio
    async def test_get_task(self, store):
        task = await store.create_task()
        retrieved = await store.get_task(task.id)
        assert retrieved is not None
        assert retrieved.id == task.id

    @pytest.mark.asyncio
    async def test_update_status(self, store):
        task = await store.create_task()
        updated = await store.update_status(task.id, TaskState.WORKING)
        assert updated.status.state == TaskState.WORKING

    @pytest.mark.asyncio
    async def test_cancel_task(self, store):
        task = await store.create_task()
        await store.update_status(task.id, TaskState.WORKING)
        canceled = await store.cancel_task(task.id)
        assert canceled.status.state == TaskState.CANCELED

    @pytest.mark.asyncio
    async def test_cancel_completed_task_noop(self, store):
        task = await store.create_task()
        await store.update_status(task.id, TaskState.COMPLETED)
        result = await store.cancel_task(task.id)
        assert result.status.state == TaskState.COMPLETED

    @pytest.mark.asyncio
    async def test_list_tasks_filter_by_state(self, store):
        t1 = await store.create_task()
        await store.create_task()
        await store.update_status(t1.id, TaskState.WORKING)

        working = await store.list_tasks(state=TaskState.WORKING)
        assert len(working) == 1
        assert working[0].id == t1.id

    @pytest.mark.asyncio
    async def test_subscribe_receives_updates(self, store):
        task = await store.create_task()
        queue = await store.subscribe(task.id)

        await store.update_status(task.id, TaskState.WORKING)
        event = queue.get_nowait()
        assert event["type"] == "statusUpdate"
        assert event["status"]["state"] == "working"


class TestJSONRPCHandler:
    """Tests for the JSON-RPC handler logic."""

    @pytest.mark.asyncio
    async def test_handle_valid_request(self):
        store = TaskStore()
        result = await handle_jsonrpc(
            {
                "jsonrpc": "2.0",
                "method": "tasks/list",
                "params": {},
                "id": "test-1",
            },
            actor="test",
            store=store,
        )
        assert result["jsonrpc"] == "2.0"
        assert "result" in result

    @pytest.mark.asyncio
    async def test_handle_invalid_jsonrpc(self):
        result = await handle_jsonrpc({"jsonrpc": "1.0", "method": "test", "id": "1"})
        assert "error" in result
        assert result["error"]["code"] == -32600

    @pytest.mark.asyncio
    async def test_handle_missing_method(self):
        result = await handle_jsonrpc({"jsonrpc": "2.0", "id": "1"})
        assert "error" in result
        assert result["error"]["code"] == -32600
