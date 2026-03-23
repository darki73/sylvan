"""Jupyter Notebook (.ipynb) parser."""

import json
import re

from sylvan.database.validation import Section
from sylvan.indexing.documents.registry import register_parser
from sylvan.indexing.documents.section_builder import (
    compute_section_hash,
    extract_references,
    extract_tags,
    make_hierarchical_slug,
    make_section_id,
    wire_hierarchy,
)

_ATX_RE = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")


def _get_kernel_language(nb: dict) -> str:
    """Extract the kernel language from notebook metadata.

    Args:
        nb: Parsed notebook JSON dictionary.

    Returns:
        Lowercase language name (defaults to "python").
    """
    metadata = nb.get("metadata", {})
    kernelspec = metadata.get("kernelspec", {})
    lang = kernelspec.get("language", "")
    if lang:
        return lang.lower()
    lang_info = metadata.get("language_info", {})
    name = lang_info.get("name", "")
    if name:
        return name.lower()
    return "python"


@register_parser("notebook", [".ipynb"])
def parse_notebook(content: str, doc_path: str, repo: str) -> list[Section]:
    """Parse a Jupyter Notebook into sections.

    Markdown cells become sections (headings within them are detected).
    Code cells are rendered as fenced code blocks within the preceding section
    or as standalone level-1 sections.

    Args:
        content: Raw notebook JSON content.
        doc_path: Path to the notebook file.
        repo: Repository name for section ID generation.

    Returns:
        List of parsed Section objects with hierarchy wired.
    """
    try:
        nb = json.loads(content)
    except json.JSONDecodeError:
        return []

    cells = nb.get("cells", [])
    if not cells:
        return []

    language = _get_kernel_language(nb)
    sections: list[Section] = []
    slug_stack: list[tuple[int, str]] = []
    used_slugs: set[str] = set()
    byte_cursor = 0
    cell_index = 0

    for cell in cells:
        cell_type = cell.get("cell_type", "")
        source_lines = cell.get("source", [])
        if isinstance(source_lines, list):
            source = "".join(source_lines)
        else:
            source = str(source_lines)

        if not source.strip():
            cell_index += 1
            continue

        if cell_type == "markdown":
            title = f"Cell {cell_index + 1}"
            level = 1
            for line in source.split("\n"):
                m = _ATX_RE.match(line)
                if m:
                    level = len(m.group(1))
                    title = m.group(2).strip()
                    break

            body = source
            body_bytes = body.encode("utf-8")
            start = byte_cursor
            byte_cursor += len(body_bytes)

            slug = make_hierarchical_slug(title, level, slug_stack, used_slugs)
            sec = Section(
                section_id=make_section_id(repo, doc_path, slug, level),
                title=title,
                level=level,
                byte_start=start,
                byte_end=byte_cursor,
                content_hash=compute_section_hash(body),
                tags=extract_tags(body),
                references=extract_references(body),
            )
            sections.append(sec)

        elif cell_type == "code":
            body = f"```{language}\n{source}\n```\n"
            body_bytes = body.encode("utf-8")
            start = byte_cursor
            byte_cursor += len(body_bytes)

            title = f"Code cell {cell_index + 1}"
            level = 2

            slug = make_hierarchical_slug(title, level, slug_stack, used_slugs)
            sec = Section(
                section_id=make_section_id(repo, doc_path, slug, level),
                title=title,
                level=level,
                byte_start=start,
                byte_end=byte_cursor,
                content_hash=compute_section_hash(body),
                tags=extract_tags(body),
                references=extract_references(body),
            )
            sections.append(sec)

        elif cell_type == "raw":
            body = source
            body_bytes = body.encode("utf-8")
            start = byte_cursor
            byte_cursor += len(body_bytes)

            title = f"Raw cell {cell_index + 1}"
            level = 2

            slug = make_hierarchical_slug(title, level, slug_stack, used_slugs)
            sec = Section(
                section_id=make_section_id(repo, doc_path, slug, level),
                title=title,
                level=level,
                byte_start=start,
                byte_end=byte_cursor,
                content_hash=compute_section_hash(body),
                tags=extract_tags(body),
                references=extract_references(body),
            )
            sections.append(sec)

        cell_index += 1

    wire_hierarchy(sections)
    return sections
