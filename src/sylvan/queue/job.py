"""Job definitions for the async queue."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncio


class JobStatus(Enum):
    """Lifecycle states for a queued job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    """A unit of work submitted to the queue.

    Attributes:
        id: Unique job identifier.
        job_type: Registered worker type name.
        kwargs: Arguments passed to the worker's handle method.
        priority: Lower values run first.
        key: Deduplication key. Jobs with the same key are not queued twice.
        future: Resolved when the job completes or fails.
        status: Current lifecycle state.
        progress: Optional progress dict (updated by workers).
    """

    job_type: str
    kwargs: dict = field(default_factory=dict)
    priority: int = 0
    key: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    future: asyncio.Future | None = field(default=None, repr=False)
    status: JobStatus = JobStatus.PENDING
    progress: dict | None = field(default=None, repr=False)
