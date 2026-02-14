"""
A2A JSON-RPC 2.0 request handler.

Implements the A2A protocol methods:
- message/send: Send a message to initiate or continue a task
- tasks/get: Retrieve task status and results
- tasks/list: List tasks with optional filtering
- tasks/cancel: Cancel a running task
"""

import asyncio
import logging
from typing import Any, Optional

from cirisnode.api.a2a.tasks import (
    TaskState,
    TaskStore,
    task_store,
)
from cirisnode.api.a2a.batch_executor import execute_evaluation

logger = logging.getLogger(__name__)


class JSONRPCError:
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    # A2A-specific errors
    TASK_NOT_FOUND = -32001
    TASK_NOT_CANCELABLE = -32002


def _error_response(id: Any, code: int, message: str, data: Any = None) -> dict:
    resp = {
        "jsonrpc": "2.0",
        "id": id,
        "error": {"code": code, "message": message},
    }
    if data is not None:
        resp["error"]["data"] = data
    return resp


def _success_response(id: Any, result: Any) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": id,
        "result": result,
    }


async def handle_jsonrpc(
    request: dict,
    actor: str = "unknown",
    store: Optional[TaskStore] = None,
) -> dict:
    """
    Route a JSON-RPC 2.0 request to the appropriate handler.

    Args:
        request: Parsed JSON-RPC request body
        actor: Authenticated actor identifier
        store: Task store (defaults to global)

    Returns:
        JSON-RPC 2.0 response dict
    """
    store = store or task_store

    # Validate JSON-RPC structure
    if not isinstance(request, dict):
        return _error_response(None, JSONRPCError.PARSE_ERROR, "Invalid JSON-RPC request")

    jsonrpc = request.get("jsonrpc")
    if jsonrpc != "2.0":
        return _error_response(
            request.get("id"),
            JSONRPCError.INVALID_REQUEST,
            "jsonrpc field must be '2.0'",
        )

    method = request.get("method")
    params = request.get("params", {})
    req_id = request.get("id")

    if not method:
        return _error_response(req_id, JSONRPCError.INVALID_REQUEST, "Missing method")

    # Route to handler
    handlers = {
        "message/send": _handle_message_send,
        "tasks/get": _handle_tasks_get,
        "tasks/list": _handle_tasks_list,
        "tasks/cancel": _handle_tasks_cancel,
    }

    handler = handlers.get(method)
    if not handler:
        return _error_response(
            req_id,
            JSONRPCError.METHOD_NOT_FOUND,
            f"Unknown method: {method}",
        )

    try:
        result = await handler(params, actor, store)
        return _success_response(req_id, result)
    except ValueError as e:
        return _error_response(req_id, JSONRPCError.INVALID_PARAMS, str(e))
    except Exception as e:
        logger.exception(f"JSON-RPC handler error for {method}")
        return _error_response(req_id, JSONRPCError.INTERNAL_ERROR, str(e))


async def _handle_message_send(
    params: dict, actor: str, store: TaskStore
) -> dict:
    """
    Handle message/send - Start or continue an evaluation task.

    Expected params:
        message.parts[0].data:
            skill: "he300_evaluation"
            scenario_ids: [...] (optional)
            category: "commonsense" (optional)
            n_scenarios: 300 (optional)
    """
    message = params.get("message", {})
    parts = message.get("parts", [])

    # Extract evaluation parameters from message parts
    eval_params = {}
    for part in parts:
        if part.get("type") == "data":
            eval_params = part.get("data", {})
            break
        elif part.get("type") == "text":
            # Try to parse text as instruction
            eval_params["instruction"] = part.get("text", "")

    skill = eval_params.get("skill", "he300_evaluation")
    if skill not in ("he300_evaluation", "he300_scenarios"):
        raise ValueError(f"Unknown skill: {skill}. Available: he300_evaluation, he300_scenarios")

    if skill == "he300_scenarios":
        # Return scenario list
        from cirisnode.utils.data_loaders import load_he300_data

        category = eval_params.get("category")
        limit = eval_params.get("limit", 300)
        scenarios = load_he300_data(category=category, limit=limit)
        return {
            "message": {
                "role": "agent",
                "parts": [
                    {
                        "type": "data",
                        "data": {
                            "scenarios": scenarios,
                            "total": len(scenarios),
                        },
                    }
                ],
            }
        }

    # Create evaluation task
    context_id = params.get("configuration", {}).get("contextId")
    metadata = {
        "actor": actor,
        "skill": skill,
        "params": eval_params,
    }

    task = await store.create_task(context_id=context_id, metadata=metadata)

    # Fire off evaluation in background
    asyncio.create_task(
        execute_evaluation(
            task_id=task.id,
            scenario_ids=eval_params.get("scenario_ids"),
            category=eval_params.get("category"),
            n_scenarios=eval_params.get("n_scenarios", 300),
            identity_id=eval_params.get("identity_id", "default_assistant"),
            guidance_id=eval_params.get("guidance_id", "default_ethical_guidance"),
            store=store,
        )
    )

    return {"task": task.to_dict()}


async def _handle_tasks_get(
    params: dict, actor: str, store: TaskStore
) -> dict:
    """Handle tasks/get - Retrieve task status and results."""
    task_id = params.get("id")
    if not task_id:
        raise ValueError("Missing required parameter: id")

    task = await store.get_task(task_id)
    if not task:
        return _error_response(
            None,
            JSONRPCError.TASK_NOT_FOUND,
            f"Task not found: {task_id}",
        )

    return {"task": task.to_dict()}


async def _handle_tasks_list(
    params: dict, actor: str, store: TaskStore
) -> dict:
    """Handle tasks/list - List tasks with optional filtering."""
    context_id = params.get("contextId")
    state_str = params.get("state")
    limit = params.get("limit", 100)
    offset = params.get("offset", 0)

    state = None
    if state_str:
        try:
            state = TaskState(state_str)
        except ValueError:
            raise ValueError(f"Invalid state: {state_str}")

    tasks = await store.list_tasks(
        context_id=context_id,
        state=state,
        limit=limit,
        offset=offset,
    )

    return {
        "tasks": [t.to_dict() for t in tasks],
        "total": len(tasks),
    }


async def _handle_tasks_cancel(
    params: dict, actor: str, store: TaskStore
) -> dict:
    """Handle tasks/cancel - Cancel a running task."""
    task_id = params.get("id")
    if not task_id:
        raise ValueError("Missing required parameter: id")

    task = await store.cancel_task(task_id)
    if not task:
        raise ValueError(f"Task not found: {task_id}")

    return {"task": task.to_dict()}
