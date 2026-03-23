"""AsciiDoc parser -- ``=`` heading hierarchy."""

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

# AsciiDoc headings: = Title (level 0/document), == Section (level 1), etc.
# We map them: = -> 1, == -> 2, === -> 3, ...
_HEADING_RE = re.compile(r"^(={1,6})\s+(.+)$")


@register_parser("asciidoc", [".adoc"])
def parse_asciidoc(content: str, doc_path: str, repo: str) -> list[Section]:
    """Parse AsciiDoc content into sections.

    Args:
        content: Raw AsciiDoc text.
        doc_path: Path to the document file.
        repo: Repository name for section ID generation.

    Returns:
        List of parsed Section objects with hierarchy wired.
    """
    content_bytes = content.encode("utf-8")
    lines = content.split("\n")

    line_byte_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_byte_offsets.append(offset)
        offset += len(line.encode("utf-8")) + 1

    headings: list[tuple[int, int, str]] = []
    in_block = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^[-=.+*_]{4,}$", stripped):
            in_block = not in_block
            continue
        if in_block:
            continue
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))  # = is 1, == is 2, etc.
            title = m.group(2).strip()
            headings.append((idx, level, title))

    sections: list[Section] = []
    slug_stack: list[tuple[int, str]] = []
    used_slugs: set[str] = set()

    def _make(title: str, level: int, start_line: int, end_line: int) -> Section:
        """Build a Section for the given heading span.

        Args:
            title: Section heading text.
            level: Heading depth level.
            start_line: First line index (inclusive).
            end_line: Last line index (exclusive).

        Returns:
            A populated Section object.
        """
        byte_start = line_byte_offsets[start_line] if start_line < len(line_byte_offsets) else len(content_bytes)
        byte_end = line_byte_offsets[end_line] if end_line < len(line_byte_offsets) else len(content_bytes)
        body = "\n".join(lines[start_line:end_line])
        slug = make_hierarchical_slug(title, level, slug_stack, used_slugs)
        return Section(
            section_id=make_section_id(repo, doc_path, slug, level),
            title=title,
            level=level,
            byte_start=byte_start,
            byte_end=byte_end,
            content_hash=compute_section_hash(body),
            tags=extract_tags(body),
            references=extract_references(body),
        )

    first_heading_line = headings[0][0] if headings else len(lines)
    preamble = "\n".join(lines[:first_heading_line]).strip()
    if preamble:
        sections.append(_make("(root)", 0, 0, first_heading_line))

    for i, (line_idx, level, title) in enumerate(headings):
        next_line = headings[i + 1][0] if i + 1 < len(headings) else len(lines)
        sections.append(_make(title, level, line_idx, next_line))

    wire_hierarchy(sections)
    return sections
