"""Background summary generation -- runs after indexing without blocking."""

import asyncio

from sylvan.database.orm import Section, Symbol
from sylvan.database.orm.models.blob import Blob
from sylvan.database.orm.runtime.connection_manager import get_backend
from sylvan.logging import get_logger

logger = get_logger(__name__)

_summary_task: asyncio.Task | None = None
"""Reference to the active summary generation task, if any."""

_section_summary_task: asyncio.Task | None = None
"""Reference to the active section summary generation task, if any."""


async def generate_summaries(repo_id: int) -> None:
    """Generate AI summaries for symbols missing them.

    Symbols get heuristic summaries during indexing (instant). This upgrades them
    to AI-generated summaries asynchronously -- never blocks the main pipeline.

    Args:
        repo_id: Database ID of the repository.
    """
    global _summary_task

    if _summary_task is not None and not _summary_task.done():
        logger.debug("Summary task already running, skipping")
        return

    _summary_task = asyncio.current_task()
    await _generate_summaries(repo_id)


def _is_heuristic_provider(provider: object) -> bool:
    """Return True if the provider is the heuristic fallback.

    Args:
        provider: Summary provider instance.

    Returns:
        True if the provider name is "heuristic".
    """
    return provider.name == "heuristic"


def _source_in_bounds(sym: object, content: bytes) -> bool:
    """Return True if the symbol's byte range fits within the content.

    Args:
        sym: Symbol object with byte_offset and byte_length attributes.
        content: Raw file content bytes.

    Returns:
        True if the byte range is valid.
    """
    return sym.byte_offset + sym.byte_length <= len(content)


async def _generate_summaries(repo_id: int) -> None:
    """Worker function for background summary generation.

    Args:
        repo_id: Database ID of the repository.
    """
    try:
        from sylvan.providers import get_summary_provider

        provider = get_summary_provider()

        if _is_heuristic_provider(provider):
            return

        backend = get_backend()
        total_updated = 0

        while True:
            symbols = await (
                Symbol.query()
                .select(
                    "symbols.symbol_id",
                    "symbols.name",
                    "symbols.signature",
                    "symbols.docstring",
                    "symbols.byte_offset",
                    "symbols.byte_length",
                    "f.content_hash",
                )
                .join("files f", "f.id = symbols.file_id")
                .where("f.repo_id", repo_id)
                .where_group(
                    lambda q: (
                        q.where_null("symbols.summary")
                        .or_where_raw("length(symbols.summary) < 20")
                        .or_where_raw("symbols.summary = symbols.signature")
                    )
                )
                .limit(500)
                .get()
            )

            if not symbols:
                break

            logger.info("generating_summaries", count=len(symbols))
            batch_updated = 0

            for sym in symbols:
                content_hash = getattr(sym, "content_hash", None)
                content = await Blob.get(content_hash) if content_hash else None
                if content is None:
                    continue
                if not _source_in_bounds(sym, content):
                    continue

                source = content[sym.byte_offset : sym.byte_offset + sym.byte_length]
                source_text = source.decode("utf-8", errors="replace")

                try:
                    summary = provider.summarize_symbol(
                        sym.signature or "",
                        sym.docstring,
                        source_text,
                    )
                    if summary and len(summary) > 5:
                        sym_record = await Symbol.where(symbol_id=sym.symbol_id).first()
                        if sym_record:
                            await sym_record.update(summary=summary)
                        batch_updated += 1

                        if batch_updated % 20 == 0:
                            await backend.commit()
                except Exception as e:
                    logger.debug("summary_failed", symbol_id=sym.symbol_id, error=str(e))

            await backend.commit()
            total_updated += batch_updated
            logger.info("summaries_batch_complete", batch_updated=batch_updated, total_updated=total_updated)

        if total_updated > 0:
            logger.info("summaries_updated", updated=total_updated)

    except Exception as e:
        logger.debug("background_summarizer_error", error=str(e))


async def generate_section_summaries(repo_id: int) -> None:
    """Generate summaries for sections missing them.

    Mirrors :func:`generate_summaries` but for documentation sections.
    Reads section content from blobs via byte_start/byte_end and calls
    the summary provider's ``summarize_section`` method.

    Args:
        repo_id: Database ID of the repository.
    """
    global _section_summary_task

    if _section_summary_task is not None and not _section_summary_task.done():
        logger.debug("Section summary task already running, skipping")
        return

    _section_summary_task = asyncio.current_task()
    await _generate_section_summaries(repo_id)


def _section_in_bounds(sec: object, content: bytes) -> bool:
    """Return True if the section's byte range fits within the content.

    Args:
        sec: Section object with byte_start and byte_end attributes.
        content: Raw file content bytes.

    Returns:
        True if the byte range is valid.
    """
    return sec.byte_end <= len(content)


def _strip_leading_heading(text: str) -> str:
    """Remove the first heading line from section content.

    Section byte ranges include the heading (e.g. ``# Title``). Stripping it
    ensures the summarizer works on the body, not the title it already has.

    Args:
        text: Raw section content.

    Returns:
        Content with the leading heading removed.
    """
    lines = text.split("\n")
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Markdown ATX heading
        if stripped.startswith("#"):
            start = i + 1
            break
        # RST/AsciiDoc underline (===, ---, ~~~)
        if i > 0 and stripped and all(c == stripped[0] for c in stripped) and stripped[0] in "=-~^":
            start = i + 1
            break
        # Not a heading - body starts here
        break
    return "\n".join(lines[start:]).strip()


async def _generate_section_summaries(repo_id: int) -> None:
    """Worker function for background section summary generation.

    Args:
        repo_id: Database ID of the repository.
    """
    try:
        from sylvan.providers import get_summary_provider

        provider = get_summary_provider()
        backend = get_backend()
        total_updated = 0
        max_iterations = 50

        while max_iterations > 0:
            max_iterations -= 1
            sections = await (
                Section.query()
                .select(
                    "sections.section_id",
                    "sections.title",
                    "sections.byte_start",
                    "sections.byte_end",
                    "f.content_hash",
                )
                .join("files f", "f.id = sections.file_id")
                .where("f.repo_id", repo_id)
                .where_group(lambda q: q.where_null("sections.summary").or_where("sections.summary", ""))
                .limit(500)
                .get()
            )

            if not sections:
                break

            logger.info("generating_section_summaries", count=len(sections))
            batch_updated = 0

            for sec in sections:
                content_hash = getattr(sec, "content_hash", None)
                content = await Blob.get(content_hash) if content_hash else None

                # Fallback helper: set summary to title so it's not retried
                async def _fallback(section_id: str, title: str) -> None:
                    rec = await Section.where(section_id=section_id).first()
                    if rec:
                        await rec.update(summary=title)

                if content is None:
                    await _fallback(sec.section_id, sec.title)
                    batch_updated += 1
                    continue
                if not _section_in_bounds(sec, content):
                    await _fallback(sec.section_id, sec.title)
                    batch_updated += 1
                    continue

                body = content[sec.byte_start : sec.byte_end]
                body_text = body.decode("utf-8", errors="replace")
                body_without_heading = _strip_leading_heading(body_text)

                try:
                    summary = provider.summarize_section(sec.title, body_without_heading)
                    if summary and len(summary) > 5:
                        sec_record = await Section.where(section_id=sec.section_id).first()
                        if sec_record:
                            await sec_record.update(summary=summary)
                        batch_updated += 1
                    else:
                        await _fallback(sec.section_id, sec.title)
                        batch_updated += 1

                    if batch_updated % 20 == 0:
                        await backend.commit()
                except Exception as e:
                    logger.debug(
                        "section_summary_failed",
                        section_id=sec.section_id,
                        error=str(e),
                    )
                    await _fallback(sec.section_id, sec.title)
                    batch_updated += 1

            await backend.commit()
            total_updated += batch_updated
            logger.info("section_summaries_batch_complete", batch_updated=batch_updated, total_updated=total_updated)

        if total_updated > 0:
            logger.info("section_summaries_updated", updated=total_updated)

    except Exception as e:
        logger.debug("background_section_summarizer_error", error=str(e))
