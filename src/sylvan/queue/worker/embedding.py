"""Embedding worker - generates vector embeddings for symbols and sections."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from sylvan.logging import get_logger
from sylvan.queue.registry import register_worker
from sylvan.queue.worker.base import BaseWorker

if TYPE_CHECKING:
    from sylvan.queue.job import Job

logger = get_logger(__name__)


@register_worker("generate_embeddings")
class EmbeddingWorker(BaseWorker):
    """Generates embeddings for a repository's symbols and sections.

    Runs at lower priority than indexing - only processes when the
    index queue is empty. Automatically detects GPU availability
    via ONNX Runtime's CUDA provider.
    """

    job_type = "generate_embeddings"
    priority = 10
    concurrency = 1

    async def handle(self, job: Job) -> Any:
        """Generate embeddings for a repo.

        Args:
            job: Job with kwargs: repo_id, repo_name.

        Returns:
            Dict with embedding generation stats.
        """
        repo_id = job.kwargs["repo_id"]
        repo_name = job.kwargs.get("repo_name", "")

        self.report_progress(job, stage="loading_provider", repo=repo_name)

        from sylvan.search.embeddings import get_embedding_provider

        provider = get_embedding_provider()
        if provider is None:
            return {"skipped": True, "reason": "no_embedding_provider"}

        from sylvan.database.orm import Symbol
        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()

        all_symbols = (
            await Symbol.query().join("files", "files.id = symbols.file_id").where("files.repo_id", repo_id).get()
        )

        if not all_symbols:
            return {"embedded": 0, "repo": repo_name}

        # Find which symbols already have vec entries (skip those).
        import contextlib

        existing_vec_ids: set[str] = set()
        for sym in all_symbols:
            with contextlib.suppress(Exception):
                rows = await backend.fetch_all(
                    "SELECT symbol_id FROM symbols_vec WHERE symbol_id = ?",
                    [sym.symbol_id],
                )
                if rows:
                    existing_vec_ids.add(sym.symbol_id)

            # Clean up any orphaned unprefixed entries from pre-migration
            unprefixed = sym.symbol_id.split("::", 1)[-1] if "::" in sym.symbol_id else None
            if unprefixed and unprefixed != sym.symbol_id:
                with contextlib.suppress(Exception):
                    await backend.execute("DELETE FROM symbols_vec WHERE symbol_id = ?", [unprefixed])

        symbols = [s for s in all_symbols if s.symbol_id not in existing_vec_ids]

        if not symbols:
            return {"embedded": 0, "skipped": len(all_symbols), "repo": repo_name}

        total = len(symbols)
        self.report_progress(job, stage="embedding", repo=repo_name, total=total, current=0)

        batch_size = _detect_batch_size()
        embedded = 0

        for i in range(0, total, batch_size):
            batch = symbols[i : i + batch_size]
            texts = [f"{s.name} {s.signature or ''} {s.summary or ''}" for s in batch]

            vectors = await asyncio.to_thread(provider.embed, texts)

            for sym, vec in zip(batch, vectors):
                with contextlib.suppress(Exception):
                    await backend.execute(
                        "INSERT INTO symbols_vec (symbol_id, embedding) VALUES (?, ?)",
                        [sym.symbol_id, _serialize_vector(vec)],
                    )

            embedded += len(batch)
            self.report_progress(
                job,
                stage="embedding",
                repo=repo_name,
                total=total,
                current=embedded,
            )

        await backend.commit()

        return {"embedded": embedded, "repo": repo_name}


def _detect_batch_size() -> int:
    """Detect optimal batch size based on available hardware.

    Returns:
        Batch size (larger for GPU, smaller for CPU).
    """
    try:
        import onnxruntime

        providers = onnxruntime.get_available_providers()
        if "CUDAExecutionProvider" in providers:
            return 64
    except ImportError:
        pass
    return 16


def _serialize_vector(vec: list[float]) -> bytes:
    """Serialize a float vector to bytes for sqlite-vec storage.

    Args:
        vec: List of floats.

    Returns:
        Packed bytes.
    """
    import struct

    return struct.pack(f"{len(vec)}f", *vec)
