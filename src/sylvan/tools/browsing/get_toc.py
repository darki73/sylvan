"""MCP tool: get_toc -- table of contents for indexed documentation."""

from sylvan.database.orm import Repo, Section
from sylvan.tools.support.response import MetaBuilder, check_staleness, ensure_orm, log_tool_call, wrap_response


@log_tool_call
async def get_toc(
    repo: str,
    doc_path: str | None = None,
) -> dict:
    """Get a flat table of contents for indexed documentation.

    Args:
        repo: Repository name.
        doc_path: Optional filter to a specific document path.

    Returns:
        Tool response dict with ``toc`` list and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    ensure_orm()

    query_builder = Section.in_repo(repo).with_("file")

    if doc_path:
        query_builder = query_builder.join("files", "files.id = sections.file_id").where("files.path", doc_path)

    query_builder = query_builder.order_by("sections.byte_start").limit(5000)
    sections = await query_builder.get()

    toc = []
    for section in sections:
        entry = await section.to_summary_dict()
        entry["parent_id"] = section.parent_section_id
        toc.append(entry)

    meta.set("section_count", len(toc))
    response = wrap_response({"toc": toc}, meta.build())
    repo_obj = await Repo.where(name=repo).first()
    if repo_obj:
        await check_staleness(repo_obj.id, response)
    return response


@log_tool_call
async def get_toc_tree(repo: str, max_depth: int = 3) -> dict:
    """Get a nested tree table of contents, grouped by document.

    Args:
        repo: Repository name.
        max_depth: Max heading depth to include (1--6, default 3).

    Returns:
        Tool response dict with ``tree`` list and ``_meta`` envelope.
    """
    meta = MetaBuilder()
    ensure_orm()

    max_depth = min(max(max_depth, 1), 6)

    sections = await Section.in_repo(repo).with_("file").order_by("sections.byte_start").limit(5000).get()

    docs: dict[str, list] = {}
    nodes: dict[str, dict] = {}
    truncated = 0

    for section in sections:
        if section.level > max_depth:
            truncated += 1
            continue
        file_rec = section.file
        file_path = file_rec.path if file_rec else ""
        node = {
            "section_id": section.section_id,
            "title": section.title,
            "level": section.level,
            "summary": section.summary or "",
            "children": [],
        }
        nodes[section.section_id] = node

        parent_id = section.parent_section_id
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            docs.setdefault(file_path, []).append(node)

    tree = [{"file": fp, "sections": secs} for fp, secs in docs.items()]

    meta.set("document_count", len(tree))
    meta.set("section_count", len(nodes))
    if truncated:
        meta.set("truncated_sections", truncated)
        meta.set("max_depth", max_depth)
    response = wrap_response({"tree": tree}, meta.build())
    repo_obj = await Repo.where(name=repo).first()
    if repo_obj:
        await check_staleness(repo_obj.id, response)
    return response
