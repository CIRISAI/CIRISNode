"""
SSE streaming for A2A task updates.

Provides real-time task progress via Server-Sent Events,
allowing purple agents to monitor evaluation progress
without polling.
"""

import asyncio
import json
import logging
from typing import AsyncGenerator

from cirisnode.api.a2a.tasks import TaskState, task_store

logger = logging.getLogger(__name__)


async def task_event_stream(task_id: str) -> AsyncGenerator[str, None]:
    """
    Generate SSE events for a task.

    Yields events in the format:
        data: {"type": "statusUpdate", "taskId": "...", ...}

    Terminates when the task reaches a terminal state.
    """
    queue = await task_store.subscribe(task_id)
    if queue is None:
        yield f"data: {json.dumps({'error': 'Task not found', 'taskId': task_id})}\n\n"
        return

    # Send current state first
    task = await task_store.get_task(task_id)
    if task:
        yield f"data: {json.dumps({'type': 'task', 'task': task.to_dict()})}\n\n"

    terminal_states = {
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELED,
        TaskState.REJECTED,
    }

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {json.dumps(event)}\n\n"

                # Check if terminal
                if event.get("type") == "statusUpdate":
                    state_str = event.get("status", {}).get("state", "")
                    try:
                        state = TaskState(state_str)
                        if state in terminal_states:
                            # Send final task state
                            task = await task_store.get_task(task_id)
                            if task:
                                yield f"data: {json.dumps({'type': 'task', 'task': task.to_dict()})}\n\n"
                            break
                    except ValueError:
                        pass

            except asyncio.TimeoutError:
                # Send keepalive
                yield f": keepalive\n\n"

                # Check if task still exists and isn't terminal
                task = await task_store.get_task(task_id)
                if not task or task.status.state in terminal_states:
                    break

    finally:
        await task_store.unsubscribe(task_id, queue)
        logger.info(f"SSE stream closed for task {task_id}")
