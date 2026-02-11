"""In-memory ring buffer log handler for admin log viewing.

Attaches to the root logger and captures the last N log records.
Exposed via admin API so operators can troubleshoot without SSH.
"""

import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class LogBufferHandler(logging.Handler):
    """Captures log records into a bounded deque."""

    def __init__(self, capacity: int = 2000):
        super().__init__()
        self._buffer: deque[Dict[str, Any]] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
            }
            self._buffer.append(entry)
        except Exception:
            self.handleError(record)

    def get_logs(
        self,
        limit: int = 200,
        level: Optional[str] = None,
        pattern: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return recent logs, newest first, with optional filtering."""
        entries = list(self._buffer)
        if level:
            min_level = getattr(logging, level.upper(), logging.DEBUG)
            entries = [
                e for e in entries
                if getattr(logging, e["level"], 0) >= min_level
            ]
        if pattern:
            pattern_lower = pattern.lower()
            entries = [
                e for e in entries
                if pattern_lower in e["message"].lower()
                or pattern_lower in e["logger"].lower()
            ]
        # Return newest first, limited
        return list(reversed(entries))[:limit]


# Singleton instance
_handler: Optional[LogBufferHandler] = None


def install_log_buffer(capacity: int = 2000) -> LogBufferHandler:
    """Install the log buffer handler on the root logger. Idempotent."""
    global _handler
    if _handler is not None:
        return _handler
    _handler = LogBufferHandler(capacity=capacity)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(_handler)
    # Root default is WARNING — lower to DEBUG so our INFO/WARNING logs reach the handler.
    # Suppress noisy third-party loggers to keep the buffer useful.
    if root.level > logging.DEBUG:
        root.setLevel(logging.DEBUG)
    for noisy in ("httpx", "httpcore", "asyncio", "urllib3", "watchfiles", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return _handler


def get_log_buffer() -> Optional[LogBufferHandler]:
    """Get the installed log buffer handler."""
    return _handler
