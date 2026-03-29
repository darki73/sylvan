"""Index worker - handles folder and file indexing jobs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sylvan.logging import get_logger
from sylvan.queue.registry import register_worker
from sylvan.queue.worker.base import BaseWorker

if TYPE_CHECKING:
    from sylvan.queue.job import Job

logger = get_logger(__name__)


@register_worker("index_folder")
class IndexFolderWorker(BaseWorker):
    """Indexes a folder with optional force re-extraction.

    After indexing completes, submits embedding and summary generation
    jobs to the queue at lower priority.
    """

    job_type = "index_folder"
    priority = 0
    concurrency = 1

    async def handle(self, job: Job) -> Any:
        """Index a folder, then queue post-processing.

        Args:
            job: Job with kwargs: path, name, force.

        Returns:
            Dict with indexing results.
        """
        path = job.kwargs["path"]
        name = job.kwargs.get("name")
        force = job.kwargs.get("force", False)

        from sylvan.indexing.pipeline.orchestrator import index_folder as _orchestrate

        self.report_progress(job, stage="discovering", path=path)

        result = await _orchestrate(path, name=name, force=force)

        self.report_progress(
            job,
            stage="complete",
            files_indexed=result.files_indexed,
            symbols_extracted=result.symbols_extracted,
        )

        from sylvan.context import get_context

        get_context().cache.clear()

        if result.repo_id:
            from sylvan.queue import submit

            await submit(
                "generate_embeddings",
                key=f"embed:{result.repo_name}",
                repo_id=result.repo_id,
                repo_name=result.repo_name,
            )
            await submit(
                "generate_summaries",
                key=f"summarize:{result.repo_name}",
                repo_id=result.repo_id,
                repo_name=result.repo_name,
            )

        return result.to_dict()


@register_worker("index_file")
class IndexFileWorker(BaseWorker):
    """Indexes a single file."""

    job_type = "index_file"
    priority = 0
    concurrency = 1

    async def handle(self, job: Job) -> Any:
        """Index a single file.

        Args:
            job: Job with kwargs: repo, file_path.

        Returns:
            Dict with indexing results.
        """
        from sylvan.services.indexing import index_file

        return await index_file(job.kwargs["repo"], job.kwargs["file_path"])
