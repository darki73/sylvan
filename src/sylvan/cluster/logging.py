"""Cluster-aware logging -- ring buffer for followers, file sink for leader.

Followers buffer log entries in memory and flush them to the leader over
WebSocket. The leader writes all log entries (its own + followers') to
the single log file.
"""

from __future__ import annotations

import collections
import logging
from typing import Any


class ClusterLogBuffer:
    """In-memory ring buffer for log entries awaiting WebSocket flush.

    Used by followers to hold log lines until the leader connection
    is available. Thread-safe via deque's atomic append.

    Attributes:
        max_size: Maximum number of entries to buffer.
    """

    def __init__(self, max_size: int = 500) -> None:
        self._buffer: collections.deque[dict[str, Any]] = collections.deque(maxlen=max_size)

    def append(self, entry: dict[str, Any]) -> None:
        """Add a log entry to the buffer.

        Args:
            entry: Structured log entry dict.
        """
        self._buffer.append(entry)

    def flush(self) -> list[dict[str, Any]]:
        """Drain all buffered entries.

        Returns:
            List of log entry dicts, oldest first.
        """
        entries = list(self._buffer)
        self._buffer.clear()
        return entries

    def __len__(self) -> int:
        return len(self._buffer)


_log_buffer = ClusterLogBuffer()


class ClusterLogHandler(logging.Handler):
    """Logging handler that buffers entries for WebSocket transmission.

    Installed on followers. Captures structured log entries into the
    ring buffer instead of writing to a file.
    """

    def __init__(self, node_id: str, role: str) -> None:
        super().__init__()
        self.node_id = node_id
        self.role = role

    def emit(self, record: logging.LogRecord) -> None:
        """Buffer a log record for later flush to the leader.

        Args:
            record: The log record to buffer.
        """
        try:
            entry = {
                "timestamp": record.created,
                "level": record.levelname.lower(),
                "event": getattr(record, "event", record.getMessage()),
                "logger": record.name,
                "instance_id": self.node_id,
                "role": self.role,
            }
            _log_buffer.append(entry)
        except Exception:  # noqa: S110 -- logging handler must never raise
            pass


def get_buffer() -> ClusterLogBuffer:
    """Get the global log buffer.

    Returns:
        The singleton ClusterLogBuffer instance.
    """
    return _log_buffer
