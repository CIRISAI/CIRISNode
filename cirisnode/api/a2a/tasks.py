"""
A2A Task state management.

Tracks evaluation tasks through their lifecycle using an in-memory store
with Redis fallback for production. Tasks support concurrent execution
and SSE streaming of progress updates.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskState(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    INPUT_REQUIRED = "input-required"
    REJECTED = "rejected"


@dataclass
class TaskArtifact:
    """An output artifact from a task."""
    name: str
    parts: List[Dict[str, Any]]
    index: int = 0
    append: bool = False
    last_chunk: bool = True


@dataclass
class TaskStatus:
    """Current status of a task."""
    state: TaskState
    timestamp: str = ""
    message: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not self.timestamp:
            from datetime import datetime, timezone
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class A2ATask:
    """An A2A evaluation task."""
    id: str
    context_id: str
    status: TaskStatus
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    history: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: List[TaskArtifact] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Internal tracking
    _subscribers: List[asyncio.Queue] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "contextId": self.context_id,
            "status": {
                "state": self.status.state.value,
                "timestamp": self.status.timestamp,
                "message": self.status.message,
            },
            "artifacts": [
                {
                    "name": a.name,
                    "parts": a.parts,
                    "index": a.index,
                }
                for a in self.artifacts
            ],
            "history": self.history,
            "metadata": self.metadata,
        }


class TaskStore:
    """
    In-memory task store with subscription support for SSE streaming.

    Thread-safe via asyncio locks. In production, this would be backed
    by Redis for persistence across restarts.
    """

    def __init__(self, ttl_seconds: int = 3600):
        self._tasks: Dict[str, A2ATask] = {}
        self._lock = asyncio.Lock()
        self._ttl = ttl_seconds

    async def create_task(
        self,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> A2ATask:
        """Create a new task in SUBMITTED state."""
        task_id = str(uuid.uuid4())
        ctx_id = context_id or str(uuid.uuid4())

        task = A2ATask(
            id=task_id,
            context_id=ctx_id,
            status=TaskStatus(state=TaskState.SUBMITTED),
            metadata=metadata or {},
        )

        async with self._lock:
            self._tasks[task_id] = task
            # Cleanup old tasks
            await self._cleanup_expired()

        logger.info(f"Created A2A task {task_id}")
        return task

    async def get_task(self, task_id: str) -> Optional[A2ATask]:
        """Get a task by ID."""
        async with self._lock:
            return self._tasks.get(task_id)

    async def list_tasks(
        self,
        context_id: Optional[str] = None,
        state: Optional[TaskState] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[A2ATask]:
        """List tasks with optional filtering."""
        async with self._lock:
            tasks = list(self._tasks.values())

        if context_id:
            tasks = [t for t in tasks if t.context_id == context_id]
        if state:
            tasks = [t for t in tasks if t.status.state == state]

        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[offset : offset + limit]

    async def update_status(
        self,
        task_id: str,
        state: TaskState,
        message: Optional[Dict[str, Any]] = None,
    ) -> Optional[A2ATask]:
        """Update task status and notify subscribers."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            task.status = TaskStatus(state=state, message=message)
            task.updated_at = time.time()

        # Notify SSE subscribers
        event = {
            "type": "statusUpdate",
            "taskId": task_id,
            "status": {
                "state": state.value,
                "timestamp": task.status.timestamp,
                "message": message,
            },
        }
        await self._notify_subscribers(task, event)

        logger.info(f"Task {task_id} -> {state.value}")
        return task

    async def add_artifact(
        self,
        task_id: str,
        artifact: TaskArtifact,
    ) -> Optional[A2ATask]:
        """Add an artifact to a task and notify subscribers."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            task.artifacts.append(artifact)
            task.updated_at = time.time()

        # Notify SSE subscribers
        event = {
            "type": "artifactUpdate",
            "taskId": task_id,
            "artifact": {
                "name": artifact.name,
                "parts": artifact.parts,
                "index": artifact.index,
                "lastChunk": artifact.last_chunk,
            },
        }
        await self._notify_subscribers(task, event)
        return task

    async def cancel_task(self, task_id: str) -> Optional[A2ATask]:
        """Cancel a task if it's in a non-terminal state."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            terminal = {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}
            if task.status.state in terminal:
                return task  # Already terminal

            task.status = TaskStatus(state=TaskState.CANCELED)
            task.updated_at = time.time()

        await self._notify_subscribers(task, {
            "type": "statusUpdate",
            "taskId": task_id,
            "status": {"state": "canceled", "timestamp": task.status.timestamp},
        })

        logger.info(f"Task {task_id} canceled")
        return task

    async def subscribe(self, task_id: str) -> Optional[asyncio.Queue]:
        """Subscribe to task updates via an async queue."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            queue: asyncio.Queue = asyncio.Queue()
            task._subscribers.append(queue)
            return queue

    async def unsubscribe(self, task_id: str, queue: asyncio.Queue):
        """Remove a subscriber."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task and queue in task._subscribers:
                task._subscribers.remove(queue)

    async def _notify_subscribers(self, task: A2ATask, event: dict):
        """Push event to all subscribers of a task."""
        for queue in task._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(f"Subscriber queue full for task {task.id}")

    async def _cleanup_expired(self):
        """Remove tasks older than TTL."""
        now = time.time()
        expired = [
            tid
            for tid, t in self._tasks.items()
            if now - t.updated_at > self._ttl
            and t.status.state
            in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED}
        ]
        for tid in expired:
            del self._tasks[tid]
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired tasks")


# Global task store instance
task_store = TaskStore()
