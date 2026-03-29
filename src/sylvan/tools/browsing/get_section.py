"""MCP tool: get_section -- retrieve full content of a documentation section."""

from sylvan.error_codes import SylvanError
from sylvan.services.section import SectionService
from sylvan.tools.support.response import (
    check_staleness,
    ensure_orm,
    get_meta,
    log_tool_call,
    wrap_response,
)


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
    meta = get_meta()
    ensure_orm()

    svc = SectionService().with_content()
    if verify:
        svc = svc.verified()

    try:
        sec = await svc.find(section_id)
    except SylvanError as exc:
        exc._meta = meta.build()
        raise

    result = {
        **await sec._model.to_summary_dict(include_repo=True),
        "content": sec.content,
        "tags": sec._model.tags or [],
        "references": sec._model.references or [],
    }

    if sec.content and sec.file_record:
        from sylvan.tools.support.token_counting import count_tokens

        file_content = await sec.file_record.get_content()
        returned = count_tokens(sec.content)
        if returned is not None and file_content:
            file_text = file_content.decode("utf-8", errors="replace")
            equivalent = count_tokens(file_text)
            if equivalent and returned > 0 and equivalent > 0:
                meta.record_token_efficiency(returned, equivalent)

    response = wrap_response(result, meta.build(), include_hints=True)
    if sec.file_record:
        await check_staleness(sec.file_record.repo_id, response)
    return response


@log_tool_call
async def get_sections(section_ids: list[str]) -> dict:
    """Batch retrieve multiple documentation sections.

    Args:
        section_ids: List of section identifiers.

    Returns:
        Tool response dict with ``sections`` list, ``not_found`` list,
        and ``_meta`` envelope.
    """
    meta = get_meta()
    ensure_orm()

    svc = SectionService().with_content()
    found_results = await svc.find_many(section_ids)

    found_ids = {r.section_id for r in found_results}
    not_found = [sid for sid in section_ids if sid not in found_ids]
    repo_ids: set[int] = set()

    sections = []
    for r in found_results:
        if r.file_record:
            repo_ids.add(r.file_record.repo_id)
        file_path = await r._model._resolve_file_path()
        sections.append(
            {
                "section_id": r.section_id,
                "title": r.title,
                "level": r.level,
                "file": file_path,
                "content": r.content,
            }
        )

    data = {"sections": sections, "not_found": not_found}

    meta.set("found", len(sections))
    meta.set("not_found", len(not_found))

    response = wrap_response(data, meta.build())
    for rid in repo_ids:
        await check_staleness(rid, response)
    return response
