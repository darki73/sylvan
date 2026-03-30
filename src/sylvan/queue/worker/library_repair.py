"""Library repair worker - re-indexes a library from its source on disk."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sylvan.logging import get_logger
from sylvan.queue.registry import register_worker
from sylvan.queue.worker.base import BaseWorker

if TYPE_CHECKING:
    from sylvan.queue.job import Job

logger = get_logger(__name__)


@register_worker("repair_library")
class RepairLibraryWorker(BaseWorker):
    """Re-indexes a library from existing source files on disk.

    Runs index_folder, tags the repo as a library with package metadata,
    and queues embedding + summary generation.
    """

    job_type = "repair_library"
    priority = 5
    concurrency = 1

    async def handle(self, job: Job) -> Any:
        """Re-index a library and restore its metadata.

        Args:
            job: Job with kwargs: path, name, manager, package, version.

        Returns:
            Dict with indexing results.
        """
        path = job.kwargs["path"]
        name = job.kwargs["name"]
        manager = job.kwargs.get("manager", "")
        package = job.kwargs.get("package", "")
        version = job.kwargs.get("version", "")

        from sylvan.indexing.pipeline.orchestrator import index_folder as _orchestrate

        self.report_progress(job, stage="indexing", library=name)

        result = await _orchestrate(path, name=name, force=True)

        self.report_progress(
            job,
            stage="tagging",
            library=name,
            files_indexed=result.files_indexed,
            symbols_extracted=result.symbols_extracted,
        )

        if result.repo_id:
            from sylvan.database.orm import Repo
            from sylvan.database.orm.runtime.connection_manager import get_backend

            repo = await Repo.where(id=result.repo_id).first()
            if repo:
                await repo.update(
                    repo_type="library",
                    package_manager=manager,
                    package_name=package,
                    version=version,
                )
                await get_backend().commit()

            from sylvan.context import get_context

            get_context().cache.clear()

            from sylvan.queue import submit

            await submit(
                "generate_embeddings",
                key=f"embed:{name}",
                repo_id=result.repo_id,
                repo_name=result.repo_name,
            )
            await submit(
                "generate_summaries",
                key=f"summarize:{name}",
                repo_id=result.repo_id,
                repo_name=result.repo_name,
            )

        self.report_progress(job, stage="complete", library=name)

        return result.to_dict()
