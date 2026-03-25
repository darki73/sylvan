"""Post-indexing background tasks -- embedding generation and AI summaries."""

from sylvan.database.orm.runtime.connection_manager import get_backend
from sylvan.logging import get_logger

logger = get_logger(__name__)


async def start_background_tasks(repo_id: int) -> None:
    """Run embedding generation and AI summaries as an async task.

    Intended to be scheduled via ``asyncio.create_task()`` from the
    indexing orchestrator.

    Args:
        repo_id: Database ID of the repository to process.
    """
    try:
        await generate_embeddings(repo_id)
        backend = get_backend()
        await backend.commit()
    except Exception as exc:
        logger.warning("commit_after_embeddings_failed", error=str(exc))

    try:
        from sylvan.indexing.post_processing.summarizer import generate_summaries

        await generate_summaries(repo_id)
    except Exception as exc:
        logger.warning("commit_after_summaries_failed", error=str(exc))

    try:
        from sylvan.indexing.post_processing.summarizer import (
            generate_section_summaries,
        )

        await generate_section_summaries(repo_id)
    except Exception as exc:
        logger.warning("commit_after_section_summaries_failed", error=str(exc))


async def generate_embeddings(repo_id: int) -> None:
    """Generate embeddings for symbols and sections missing them.

    Args:
        repo_id: Database ID of the repository.
    """
    try:
        from sylvan.search.embeddings import (
            embed_and_store_sections,
            embed_and_store_symbols,
            get_embedding_provider,
            prepare_section_text,
            prepare_symbol_text,
        )

        provider = get_embedding_provider()
        if provider is None:
            return

        backend = get_backend()

        rows = await backend.fetch_all(
            """SELECT s.symbol_id, s.name, s.qualified_name, s.signature, s.docstring, s.summary
               FROM symbols s
               JOIN files f ON f.id = s.file_id
               WHERE f.repo_id = ?
               AND s.symbol_id NOT IN (SELECT symbol_id FROM symbols_vec)""",
            [repo_id],
        )

        if rows:
            symbol_ids = [r["symbol_id"] for r in rows]
            texts = [prepare_symbol_text(dict(r)) for r in rows]
            await embed_and_store_symbols(provider, symbol_ids, texts)

        sec_rows = await backend.fetch_all(
            """SELECT sec.section_id, sec.title, sec.summary
               FROM sections sec
               JOIN files f ON f.id = sec.file_id
               WHERE f.repo_id = ?
               AND sec.section_id NOT IN (SELECT section_id FROM sections_vec)""",
            [repo_id],
        )

        if sec_rows:
            section_ids = [r["section_id"] for r in sec_rows]
            texts = [prepare_section_text(dict(r)) for r in sec_rows]
            await embed_and_store_sections(provider, section_ids, texts)

    except ImportError:
        pass
    except Exception as e:
        logger.debug("embedding_generation_skipped", error=str(e))
