"""Worker registry - maps job types to worker classes."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sylvan.queue.worker.base import BaseWorker

_registry: dict[str, type[BaseWorker]] = {}


def register_worker(job_type: str):
    """Decorator to register a worker class for a job type.

    Args:
        job_type: The job type string this worker handles.

    Returns:
        Class decorator.
    """

    def decorator(cls: type[BaseWorker]) -> type[BaseWorker]:
        _registry[job_type] = cls
        return cls

    return decorator


def get_worker_class(job_type: str) -> type[BaseWorker] | None:
    """Look up the worker class for a job type.

    Args:
        job_type: The job type string.

    Returns:
        The registered worker class, or None.
    """
    return _registry.get(job_type)


def get_all_worker_classes() -> dict[str, type[BaseWorker]]:
    """Return all registered worker classes.

    Returns:
        Dict mapping job type to worker class.
    """
    return dict(_registry)
