"""MCP tool: get_section -- retrieve full content of a documentation section."""

from sylvan.context import get_context
from sylvan.database.orm import Section
from sylvan.error_codes import ContentNotAvailableError, SectionNotFoundError
from sylvan.tools.support.response import MetaBuilder, ensure_orm, log_tool_call, record_savings, wrap_response


@log_tool_call
async def get_section(
    section_id: str,
    verify: bool = False,
) -> dict:
    """Retrieve the full content of a documentation section by its ID.

    Args:
        section_id: The stable section identifier.
        verify: Re-hash content and warn if drifted.

    Returns:
        Tool response dict with section content and ``_meta`` envelope.

    Raises:
        SectionNotFoundError: If no section with the given ID exists.
        ContentNotAvailableError: If the section exists but content blob is missing.
    """
    meta = MetaBuilder()
    ensure_orm()

    ctx = get_context()
    cache = ctx.cache
    cache_key = f"Section:{section_id}"
    found, section = cache.get(cache_key)
    if not found:
        section = await Section.where(section_id=section_id).with_("file").first()
        if section is not None:
            cache.put(cache_key, section)

    if section is None:
        raise SectionNotFoundError(section_id=section_id, _meta=meta.build())

    section_text = await section.get_content()
    if not section_text:
        raise ContentNotAvailableError(section_id=section_id, _meta=meta.build())

    file_rec = section.file

    result = {
        **await section.to_summary_dict(include_repo=True),
        "content": section_text,
        "tags": section.tags or [],
        "references": section.references or [],
    }

    session = ctx.session
    session.record_section_access(section_id, await section._resolve_file_path())
    await record_savings(meta, section_text, file_rec, sections_retrieved=1)

    return wrap_response(result, meta.build(), include_hints=True)


@log_tool_call
async def get_sections(section_ids: list[str]) -> dict:
    """Batch retrieve multiple documentation sections.

    Args:
        section_ids: List of section identifiers.

    Returns:
        Tool response dict with ``sections`` list, ``not_found`` list,
        and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    ensure_orm()

    ctx = get_context()
    cache = ctx.cache
    results = []
    not_found = []

    for sid in section_ids:
        cache_key = f"Section:{sid}"
        found, section = cache.get(cache_key)
        if not found:
            section = await Section.where(section_id=sid).with_("file").first()
            if section is not None:
                cache.put(cache_key, section)

        if section is None:
            not_found.append(sid)
            continue

        section_text = await section.get_content()
        if not section_text:
            not_found.append(sid)
            continue

        results.append({
            "section_id": section.section_id,
            "title": section.title,
            "level": section.level,
            "file": await section._resolve_file_path(),
            "content": section_text,
        })

    meta.set("found", len(results))
    meta.set("not_found", len(not_found))
    return wrap_response({"sections": results, "not_found": not_found}, meta.build())
