"""
A2A Protocol FastAPI routes.

Provides:
- GET  /.well-known/agent.json  - Agent Card discovery
- POST /a2a                      - JSON-RPC 2.0 endpoint
- GET  /a2a/tasks/{id}/stream   - SSE streaming
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from cirisnode.api.a2a.agent_card import build_agent_card
from cirisnode.auth.dependencies import require_auth as validate_a2a_auth
from cirisnode.api.a2a.jsonrpc import handle_jsonrpc
from cirisnode.api.a2a.streaming import task_event_stream
from cirisnode.api.a2a.tasks import task_store
from cirisnode.utils.audit import write_audit_log

logger = logging.getLogger(__name__)

# Agent Card endpoint - no auth required per A2A spec
agent_card_router = APIRouter(tags=["a2a"])


@agent_card_router.get("/.well-known/agent.json")
async def get_agent_card(request: Request):
    """
    A2A Agent Card discovery endpoint.

    Returns a JSON document describing CIRISNode's capabilities,
    available skills, and authentication requirements.
    No authentication required per A2A specification.
    """
    base_url = str(request.base_url).rstrip("/")
    card = build_agent_card(base_url=base_url)
    return JSONResponse(content=card)


# Main A2A endpoint - requires auth
a2a_router = APIRouter(prefix="/a2a", tags=["a2a"])


@a2a_router.post("")
async def a2a_rpc(
    request: Request,
    actor: str = Depends(validate_a2a_auth),
):
    """
    A2A JSON-RPC 2.0 endpoint.

    Accepts JSON-RPC 2.0 requests for task management:
    - message/send: Start or continue an evaluation task
    - tasks/get: Get task status and results
    - tasks/list: List tasks
    - tasks/cancel: Cancel a running task
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error: invalid JSON"},
            },
            status_code=200,  # JSON-RPC errors use 200
        )

    # Handle the request
    response = await handle_jsonrpc(body, actor=actor)

    # Audit log
    method = body.get("method", "unknown") if isinstance(body, dict) else "unknown"
    try:
        await write_audit_log(
            actor=actor,
            event_type=f"a2a_{method.replace('/', '_')}",
            payload={"method": method, "request_id": body.get("id") if isinstance(body, dict) else None},
        )
    except Exception as e:
        logger.warning(f"Audit log failed for A2A request: {e}")

    return JSONResponse(content=response)


@a2a_router.get("/tasks/{task_id}/stream")
async def stream_task(
    task_id: str,
    actor: str = Depends(validate_a2a_auth),
):
    """
    SSE streaming endpoint for task progress.

    Returns a Server-Sent Events stream with real-time updates
    for the specified task. Events include status changes,
    batch progress, and final results.
    """
    task = await task_store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    return StreamingResponse(
        task_event_stream(task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
