"""Section service - fluent query builder for documentation sections.

Usage::

    # MCP tool: single section with content
    sec = await SectionService().with_content().find("path::heading#section")
    print(sec.title, sec.content)

    # Batch retrieve with content
    secs = await SectionService().with_content().find_many([sid1, sid2])

    # Table of contents
    toc = await SectionService().toc("sylvan")
    tree = await SectionService().toc_tree("sylvan", max_depth=3)
"""

from __future__ import annotations

from sylvan.context import get_context
from sylvan.database.orm import Section
from sylvan.error_codes import ContentNotAvailableError, SectionNotFoundError


class SectionResult:
    """A Section model enriched with optional computed data.

    Model fields (title, level, etc.) are accessible directly
    via attribute proxy. Extra data is None until loaded by the service.
    """

    __slots__ = ("_model", "content", "file_record")

    def __init__(self, model: Section) -> None:
        self._model = model
        self.content: str | None = None
        self.file_record = None

    def __getattr__(self, name: str):
        return getattr(self._model, name)

    def __repr__(self) -> str:
        return f"<SectionResult {self._model.section_id}>"


class SectionService:
    """Fluent query builder for documentation section retrieval.

    Chain ``with_*()`` methods to declare what data to load,
    then call ``find()`` or ``find_many()`` to execute. Same single-use
    contract as QueryBuilder.
    """

    def __init__(self) -> None:
        self._include_content = False
        self._verify = False

    def with_content(self) -> SectionService:
        """Load the section's content blob."""
        self._include_content = True
        return self

    def verified(self) -> SectionService:
        """Reserved for future content hash verification."""
        self._verify = True
        return self

    async def find(self, section_id: str) -> SectionResult | None:
        """Find a single section by its stable identifier.

        Args:
            section_id: The stable section identifier.

        Returns:
            SectionResult with requested data loaded.

        Raises:
            SectionNotFoundError: If no section with the given ID exists.
            ContentNotAvailableError: If content is requested but blob is missing.
        """
        ctx = get_context()
        cache = ctx.cache
        cache_key = f"Section:{section_id}"
        found, section = cache.get(cache_key)
        if not found:
            section = await Section.where(section_id=section_id).with_("file").first()
            if section is not None:
                cache.put(cache_key, section)

        if section is None:
            raise SectionNotFoundError(section_id=section_id)

        return await self._enrich_single(section, ctx)

    async def find_many(self, section_ids: list[str]) -> list[SectionResult]:
        """Batch retrieve multiple sections by their identifiers.

        Args:
            section_ids: List of section identifiers to resolve.

        Returns:
            List of SectionResult for found sections (missing IDs are skipped).
        """
        ctx = get_context()
        cache = ctx.cache
        results = []

        for sid in section_ids:
            cache_key = f"Section:{sid}"
            found, section = cache.get(cache_key)
            if not found:
                section = await Section.where(section_id=sid).with_("file").first()
                if section is not None:
                    cache.put(cache_key, section)

            if section is None:
                continue

            try:
                result = await self._enrich_single(section, ctx)
            except ContentNotAvailableError:
                continue
            results.append(result)

        return results

    async def toc(self, repo_name: str, doc_path: str | None = None) -> dict:
        """Get a flat table of contents for indexed documentation.

        Args:
            repo_name: Repository name.
            doc_path: Optional filter to a specific document path.

        Returns:
            Dict with 'toc' list of section entries and 'section_count'.
        """
        query_builder = Section.in_repo(repo_name).with_("file")

        if doc_path:
            query_builder = query_builder.join("files", "files.id = sections.file_id").where("files.path", doc_path)

        query_builder = query_builder.order_by("sections.byte_start").limit(5000)
        sections = await query_builder.get()

        toc = []
        for section in sections:
            entry = await section.to_summary_dict()
            entry["parent_id"] = section.parent_section_id
            toc.append(entry)

        return {
            "toc": toc,
            "section_count": len(toc),
            "repo_name": repo_name,
        }

    async def toc_tree(self, repo_name: str, max_depth: int = 3) -> dict:
        """Get a nested tree table of contents, grouped by document.

        Args:
            repo_name: Repository name.
            max_depth: Max heading depth to include (1-6, default 3).

        Returns:
            Dict with 'tree' list grouped by document, 'document_count',
            'section_count', and optional 'truncated_sections'.
        """
        max_depth = min(max(max_depth, 1), 6)

        sections = await Section.in_repo(repo_name).with_("file").order_by("sections.byte_start").limit(5000).get()

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

        result: dict = {
            "tree": tree,
            "document_count": len(tree),
            "section_count": len(nodes),
            "repo_name": repo_name,
        }
        if truncated:
            result["truncated_sections"] = truncated
            result["max_depth"] = max_depth

        return result

    async def _enrich_single(self, section: Section, ctx: object) -> SectionResult:
        """Wrap a Section model and load requested extra data.

        Args:
            section: The Section model instance.
            ctx: The SylvanContext for session/cache access.

        Returns:
            SectionResult with content/file populated if requested.
        """
        result = SectionResult(section)
        result.file_record = section.file

        if self._include_content:
            section_text = await section.get_content()
            if not section_text:
                raise ContentNotAvailableError(section_id=section.section_id)
            result.content = section_text

        file_path = await section._resolve_file_path()
        ctx.session.record_section_access(section.section_id, file_path)

        return result
