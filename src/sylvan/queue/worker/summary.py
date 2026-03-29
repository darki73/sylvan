"""Summary worker - generates AI summaries for symbols and sections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sylvan.logging import get_logger
from sylvan.queue.registry import register_worker
from sylvan.queue.worker.base import BaseWorker

if TYPE_CHECKING:
    from sylvan.queue.job import Job

logger = get_logger(__name__)


@register_worker("generate_summaries")
class SummaryWorker(BaseWorker):
    """Generates heuristic summaries for symbols and sections.

    Runs at lower priority than indexing and embeddings.
    """

    job_type = "generate_summaries"
    priority = 20
    concurrency = 1

    async def handle(self, job: Job) -> Any:
        """Generate summaries for a repo's symbols and sections.

        Args:
            job: Job with kwargs: repo_id, repo_name.

        Returns:
            Dict with summary generation stats.
        """
        repo_id = job.kwargs["repo_id"]
        repo_name = job.kwargs.get("repo_name", "")

        self.report_progress(job, stage="symbol_summaries", repo=repo_name)

        from sylvan.indexing.post_processing.summarizer import (
            generate_section_summaries,
            generate_summaries,
        )

        await generate_summaries(repo_id)

        self.report_progress(job, stage="section_summaries", repo=repo_name)

        await generate_section_summaries(repo_id)

        return {"repo": repo_name}
