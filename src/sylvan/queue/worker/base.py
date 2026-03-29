"""Base worker - common queue mechanics for all worker types."""

from __future__ import annotations

import asyncio
from typing import Any

from sylvan.logging import get_logger
from sylvan.queue.job import Job, JobStatus

logger = get_logger(__name__)


class BaseWorker:
    """Base class for queue workers.

    Subclasses implement ``handle()`` with the actual work.
    The base class manages the internal queue and provides
    progress reporting.

    Attributes:
        job_type: The job type string this worker handles.
        priority: Lower values = higher priority in the runner.
        concurrency: Max concurrent jobs (default 1).
    """

    job_type: str = ""
    priority: int = 0
    concurrency: int = 1

    def __init__(self) -> None:
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self._current_job: Job | None = None

    async def handle(self, job: Job) -> Any:
        """Process a job. Subclasses must implement this.

        Args:
            job: The job to process.

        Returns:
            The result value to set on the job's future.
        """
        raise NotImplementedError

    def report_progress(self, job: Job, **kwargs: Any) -> None:
        """Emit a progress event for the current job.

        Args:
            job: The job in progress.
            **kwargs: Progress data (e.g. current=47, total=404).
        """
        from sylvan.events import emit

        job.progress = kwargs
        emit(
            "job_progress",
            {
                "job_id": job.id,
                "job_type": job.job_type,
                "key": job.key,
                **kwargs,
            },
        )

    @property
    def current_job(self) -> Job | None:
        """The currently running job, or None."""
        return self._current_job

    @property
    def pending_count(self) -> int:
        """Number of jobs waiting in the queue."""
        return self.queue.qsize()

    def has_pending(self) -> bool:
        """Check if there are jobs waiting."""
        return not self.queue.empty()

    def cancel_by_key(self, key: str) -> int:
        """Remove all pending jobs with the given key.

        Args:
            key: The deduplication key to cancel.

        Returns:
            Number of jobs cancelled.
        """
        cancelled = 0
        remaining: list[Job] = []
        while not self.queue.empty():
            try:
                job = self.queue.get_nowait()
                if job.key == key:
                    job.status = JobStatus.CANCELLED
                    if job.future and not job.future.done():
                        job.future.cancel()
                    cancelled += 1
                else:
                    remaining.append(job)
            except asyncio.QueueEmpty:
                break
        for job in remaining:
            self.queue.put_nowait(job)
        return cancelled

    def is_duplicate(self, key: str) -> bool:
        """Check if a job with this key is already queued or running.

        Args:
            key: The deduplication key.

        Returns:
            True if a job with this key exists.
        """
        if self._current_job and self._current_job.key == key:
            return True
        return any(job.key == key for job in list(self.queue._queue))
